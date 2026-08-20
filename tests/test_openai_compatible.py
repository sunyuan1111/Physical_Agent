from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

import physical_agent.llm.openai_compatible as openai_compatible
from physical_agent.agent.llm_planner import LLMPlanner
from physical_agent.env import load_dotenv
from physical_agent.llm import (
    OpenAICompatibleClient,
    OpenAICompatibleError,
    OpenAICompatibleSettings,
    llm_settings_path,
    public_llm_settings_summary,
    read_llm_settings_file,
    write_llm_settings_file,
)
from physical_agent.protocol.schemas import Observation


class FakeBadRequestError(Exception):
    status_code = 400


class FakeRateLimitError(Exception):
    status_code = 429


class FakeTimeoutError(Exception):
    pass


class FakeConnectionError(Exception):
    pass


class FakeStatusError(Exception):
    def __init__(self, message: str, *, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class FakeOpenAI:
    instances: list["FakeOpenAI"] = []
    chat_outputs: list[object] = []
    responses_outputs: list[object] = []

    def __init__(self, *, api_key: str, base_url: str, timeout: int):
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.calls: list[dict[str, object]] = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._chat_completion_create)
        )
        self.responses = SimpleNamespace(create=self._responses_create)
        self.__class__.instances.append(self)

    def _chat_completion_create(self, **payload):
        self.calls.append({"method": "chat.completions.create", "payload": payload})
        output = self.__class__.chat_outputs.pop(0)
        if isinstance(output, BaseException):
            raise output
        return output

    def _responses_create(self, **payload):
        self.calls.append({"method": "responses.create", "payload": payload})
        output = self.__class__.responses_outputs.pop(0)
        if isinstance(output, BaseException):
            raise output
        return output


@pytest.fixture
def fake_openai(monkeypatch):
    FakeOpenAI.instances = []
    FakeOpenAI.chat_outputs = []
    FakeOpenAI.responses_outputs = []
    monkeypatch.setenv("PA_LLM_TRACE", "0")
    monkeypatch.setattr(
        openai_compatible,
        "openai",
        SimpleNamespace(
            OpenAI=FakeOpenAI,
            BadRequestError=FakeBadRequestError,
            RateLimitError=FakeRateLimitError,
            APITimeoutError=FakeTimeoutError,
            APIConnectionError=FakeConnectionError,
            APIStatusError=FakeStatusError,
        ),
    )
    return FakeOpenAI


def _chat_text(text: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


def _chat_delta(text: str) -> dict:
    return {"choices": [{"delta": {"content": text}}]}


def _responses_text(text: str) -> dict:
    return {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": text}],
            }
        ]
    }


def _responses_delta(text: str) -> dict:
    return {"type": "response.output_text.delta", "delta": text}


def test_load_dotenv_sets_gpt_env_names(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("GPT_URL=http://example.test/v1\nGPT_KEY=secret\n", encoding="utf-8")
    monkeypatch.delenv("GPT_URL", raising=False)
    monkeypatch.delenv("GPT_KEY", raising=False)
    loaded = load_dotenv(env_file)
    assert loaded["GPT_URL"] == "http://example.test/v1"
    assert loaded["GPT_KEY"] == "secret"


def test_openai_settings_reads_gpt_env_names(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GPT_URL=https://ark.cn-beijing.volces.com/api/v3\n"
        "GPT_KEY=project-key\n"
        "GPT_MODEL=doubao-seed-2.1-pro\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GPT_URL", "http://global.test/v1")
    monkeypatch.setenv("GPT_KEY", "global-key")
    monkeypatch.setenv("GPT_MODEL", "global-model")
    monkeypatch.delenv("OPENAI_API_MODE", raising=False)
    monkeypatch.delenv("GPT_API_MODE", raising=False)
    monkeypatch.delenv("API_MODE", raising=False)

    settings = OpenAICompatibleSettings.from_env(env_file=env_file)

    assert settings.base_url == "https://ark.cn-beijing.volces.com/api/v3"
    assert settings.api_key == "project-key"
    assert settings.model == "doubao-seed-2.1-pro"
    assert settings.api_mode == "chat_completions"
    assert settings.chat_completions_url == (
        "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
    )
    assert settings.responses_url == "https://ark.cn-beijing.volces.com/api/v3/responses"


def test_llm_settings_file_round_trips_and_public_summary_masks_key(tmp_path):
    workspace = tmp_path / "workspace"
    settings_path = llm_settings_path(workspace)

    written = write_llm_settings_file(
        settings_path,
        {
            "base_url": "http://local.test/v1",
            "api_key": "sk-local-secret-1234",
            "model": "local-model",
            "api_mode": "chat_completions",
            "reasoning_extra_body": {"thinking": {"type": "enabled"}},
        },
    )

    assert read_llm_settings_file(settings_path) == written
    summary = public_llm_settings_summary(written, settings_path=settings_path)
    summary_text = json.dumps(summary)
    assert summary["has_api_key"] is True
    assert summary["masked_api_key"] == "****1234"
    assert summary["reasoning_enabled"] is True
    assert summary["reasoning_effort"] == "medium"
    assert summary["reasoning_summary"] == "auto"
    assert summary["has_reasoning_extra_body"] is True
    assert "sk-local-secret-1234" not in summary_text
    assert settings_path.exists()


def test_llm_settings_file_takes_priority_over_env(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GPT_URL=http://env.test/v1\n"
        "GPT_KEY=env-key\n"
        "GPT_MODEL=env-model\n"
        "OPENAI_API_MODE=responses\n",
        encoding="utf-8",
    )
    workspace = tmp_path / "workspace"
    write_llm_settings_file(
        llm_settings_path(workspace),
        {
            "base_url": "http://settings.test/v1",
            "api_key": "settings-key",
            "model": "settings-model",
            "api_mode": "chat_completions",
        },
    )
    for key in (
        "GPT_URL",
        "GPT_KEY",
        "GPT_MODEL",
        "OPENAI_API_MODE",
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = OpenAICompatibleSettings.from_env(
        env_file=env_file,
        workspace_path=workspace,
    )
    override = OpenAICompatibleSettings.from_env(
        env_file=env_file,
        workspace_path=workspace,
        model="override-model",
    )

    assert settings.base_url == "http://settings.test/v1"
    assert settings.api_key == "settings-key"
    assert settings.model == "settings-model"
    assert settings.api_mode == "chat_completions"
    assert settings.reasoning_enabled is True
    assert settings.reasoning_effort == "medium"
    assert settings.reasoning_summary == "auto"
    assert settings.reasoning_extra_body == {}
    assert override.model == "override-model"
    for key in (
        "GPT_URL",
        "GPT_KEY",
        "GPT_MODEL",
        "OPENAI_API_MODE",
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "GPT_API_MODE",
        "API_MODE",
        "OPENAI_REASONING_ENABLED",
        "GPT_REASONING_ENABLED",
        "OPENAI_REASONING_EFFORT",
        "GPT_REASONING_EFFORT",
        "OPENAI_REASONING_SUMMARY",
        "GPT_REASONING_SUMMARY",
        "OPENAI_REASONING_EXTRA_BODY",
        "GPT_REASONING_EXTRA_BODY",
    ):
        os.environ.pop(key, None)


def test_openai_settings_reads_reasoning_env_names(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GPT_URL=http://project.test/v1\n"
        "GPT_KEY=project-key\n"
        "GPT_MODEL=project-model\n"
        "GPT_REASONING_ENABLED=false\n"
        "GPT_REASONING_EFFORT=high\n"
        "GPT_REASONING_SUMMARY=none\n"
        'GPT_REASONING_EXTRA_BODY={"thinking":{"type":"enabled"}}\n',
        encoding="utf-8",
    )
    for key in (
        "GPT_REASONING_ENABLED",
        "GPT_REASONING_EFFORT",
        "GPT_REASONING_SUMMARY",
        "GPT_REASONING_EXTRA_BODY",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = OpenAICompatibleSettings.from_env(env_file=env_file)

    assert settings.reasoning_enabled is False
    assert settings.reasoning_effort == "high"
    assert settings.reasoning_summary == "none"
    assert settings.reasoning_extra_body == {"thinking": {"type": "enabled"}}
    for key in (
        "OPENAI_REASONING_ENABLED",
        "GPT_REASONING_ENABLED",
        "OPENAI_REASONING_EFFORT",
        "GPT_REASONING_EFFORT",
        "OPENAI_REASONING_SUMMARY",
        "GPT_REASONING_SUMMARY",
        "OPENAI_REASONING_EXTRA_BODY",
        "GPT_REASONING_EXTRA_BODY",
    ):
        os.environ.pop(key, None)


def test_openai_settings_can_select_responses_mode(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GPT_URL=http://project.test/v1\n"
        "GPT_KEY=project-key\n"
        "GPT_MODEL=project-model\n"
        "OPENAI_API_MODE=responses\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENAI_API_MODE", raising=False)

    settings = OpenAICompatibleSettings.from_env(env_file=env_file)

    assert settings.api_mode == "responses"
    assert settings.responses_url == "http://project.test/v1/responses"
    for key in ("OPENAI_API_MODE", "GPT_API_MODE", "API_MODE"):
        os.environ.pop(key, None)


def test_openai_settings_rejects_full_endpoint_base_url():
    with pytest.raises(OpenAICompatibleError, match="API root"):
        OpenAICompatibleSettings(
            api_key="test-key",
            base_url="https://provider.test/v1/chat/completions",
            model="test-model",
        )


def test_sdk_client_receives_ark_api_root_without_extra_v1(fake_openai):
    settings = OpenAICompatibleSettings(
        api_key="test-key",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model="doubao-seed-2.1-pro",
    )

    OpenAICompatibleClient(settings)

    assert fake_openai.instances[0].base_url == "https://ark.cn-beijing.volces.com/api/v3"
    assert not fake_openai.instances[0].base_url.endswith("/v1")


def test_chat_completion_create_calls_openai_sdk(fake_openai):
    fake_openai.chat_outputs = [_chat_text("pong")]
    settings = OpenAICompatibleSettings(
        api_key="test-key",
        base_url="http://project.test/v1",
        model="test-model",
    )

    result = OpenAICompatibleClient(settings).chat_completion_create(
        [{"role": "user", "content": "ping"}],
        metadata={"physical_agent_surface": "test"},
    )

    assert result["choices"][0]["message"]["content"] == "pong"
    call = fake_openai.instances[0].calls[0]
    assert call["method"] == "chat.completions.create"
    payload = call["payload"]
    assert payload["model"] == "test-model"
    assert payload["messages"][0]["role"] == "user"
    assert payload["metadata"]["physical_agent_surface"] == "test"
    assert "extra_body" not in payload


def test_llm_trace_records_chat_completion_jsonl(fake_openai, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PA_LLM_TRACE", raising=False)
    fake_openai.chat_outputs = [
        {
            "choices": [{"message": {"role": "assistant", "content": "pong"}}],
            "usage": {"total_tokens": 7},
        }
    ]
    settings = OpenAICompatibleSettings(
        api_key="test-key",
        base_url="http://project.test/v1",
        model="test-model",
    )

    OpenAICompatibleClient(settings).chat_completion_create(
        [{"role": "user", "content": "ping"}],
        metadata={"physical_agent_surface": "trace_test"},
    )

    files = list((tmp_path / "workspace" / "llm-trace").glob("*.jsonl"))
    assert len(files) == 1
    record = json.loads(files[0].read_text(encoding="utf-8").strip())
    assert record["surface"] == "trace_test"
    assert record["model"] == "test-model"
    assert record["messages"][0]["content"] == "ping"
    assert record["response"]["choices"][0]["message"]["content"] == "pong"
    assert record["usage"] == {"total_tokens": 7}
    assert isinstance(record["latency_ms"], int)
    assert record["error"] is None


def test_llm_trace_records_structured_json_and_stream(fake_openai, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PA_LLM_TRACE", raising=False)
    fake_openai.chat_outputs = [
        _chat_text(json.dumps({"answer": "pong"})),
        [_chat_delta("hel"), _chat_delta("lo")],
    ]
    settings = OpenAICompatibleSettings(
        api_key="test-key",
        base_url="http://project.test/v1",
        model="test-model",
    )
    client = OpenAICompatibleClient(settings)

    assert client.structured_json(
        [{"role": "user", "content": "ping"}],
        schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
        },
        schema_name="ping_response",
        metadata={"physical_agent_surface": "structured_trace"},
    ) == {"answer": "pong"}
    assert list(
        client.stream_chat_text(
            [{"role": "user", "content": "hello"}],
            metadata={"physical_agent_surface": "stream_trace"},
        )
    ) == ["hel", "lo"]

    records = []
    for path in (tmp_path / "workspace" / "llm-trace").glob("*.jsonl"):
        records.extend(
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        )
    assert [record["surface"] for record in records] == [
        "structured_trace",
        "stream_trace",
    ]
    assert records[1]["response"] == {"text": "hello"}


def test_llm_trace_disabled_writes_nothing(fake_openai, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PA_LLM_TRACE", "0")
    fake_openai.chat_outputs = [_chat_text("pong")]
    settings = OpenAICompatibleSettings(
        api_key="test-key",
        base_url="http://project.test/v1",
        model="test-model",
    )

    OpenAICompatibleClient(settings).chat_completion_create(
        [{"role": "user", "content": "ping"}],
        metadata={"physical_agent_surface": "trace_disabled"},
    )

    assert not (tmp_path / "workspace" / "llm-trace").exists()


def test_chat_completion_create_passes_reasoning_extra_body_when_configured(fake_openai):
    fake_openai.chat_outputs = [_chat_text("pong")]
    settings = OpenAICompatibleSettings(
        api_key="test-key",
        base_url="http://project.test/v1",
        model="test-model",
        reasoning_extra_body={"thinking": {"type": "enabled"}},
    )

    OpenAICompatibleClient(settings).chat_completion_create(
        [{"role": "user", "content": "ping"}]
    )

    payload = fake_openai.instances[0].calls[0]["payload"]
    assert payload["extra_body"] == {"thinking": {"type": "enabled"}}


def test_stream_chat_text_aggregates_chat_completion_deltas(fake_openai):
    fake_openai.chat_outputs = [
        [
            {"choices": [{"delta": {"role": "assistant"}}]},
            _chat_delta("hel"),
            _chat_delta("lo"),
            {"choices": [{"delta": {}}]},
        ]
    ]
    settings = OpenAICompatibleSettings(
        api_key="test-key",
        base_url="http://project.test/v1",
        model="test-model",
    )

    chunks = list(
        OpenAICompatibleClient(settings).stream_chat_text(
            [{"role": "user", "content": "ping"}],
            metadata={"physical_agent_surface": "test_stream"},
        )
    )

    assert chunks == ["hel", "lo"]
    call = fake_openai.instances[0].calls[0]
    assert call["method"] == "chat.completions.create"
    assert call["payload"]["stream"] is True
    assert call["payload"]["metadata"]["physical_agent_surface"] == "test_stream"
    assert "extra_body" not in call["payload"]


def test_stream_chat_text_passes_chat_reasoning_extra_body_when_configured(fake_openai):
    fake_openai.chat_outputs = [[_chat_delta("pong")]]
    settings = OpenAICompatibleSettings(
        api_key="test-key",
        base_url="http://project.test/v1",
        model="test-model",
        reasoning_extra_body={"thinking": {"type": "enabled"}},
    )

    chunks = list(
        OpenAICompatibleClient(settings).stream_chat_text(
            [{"role": "user", "content": "ping"}]
        )
    )

    assert chunks == ["pong"]
    payload = fake_openai.instances[0].calls[0]["payload"]
    assert payload["stream"] is True
    assert payload["extra_body"] == {"thinking": {"type": "enabled"}}


def test_stream_chat_text_aggregates_responses_deltas(fake_openai):
    fake_openai.responses_outputs = [
        [
            {"type": "response.created"},
            _responses_delta("hel"),
            _responses_delta("lo"),
            {"type": "response.completed"},
        ]
    ]
    settings = OpenAICompatibleSettings(
        api_key="test-key",
        base_url="http://project.test/v1",
        model="test-model",
        api_mode="responses",
    )

    chunks = list(
        OpenAICompatibleClient(settings).stream_chat_text(
            [
                {"role": "system", "content": "Return text."},
                {"role": "user", "content": "ping"},
            ],
            metadata={"physical_agent_surface": "test_stream"},
        )
    )

    assert chunks == ["hel", "lo"]
    call = fake_openai.instances[0].calls[0]
    assert call["method"] == "responses.create"
    assert call["payload"]["stream"] is True
    assert call["payload"]["instructions"] == "Return text."
    assert call["payload"]["metadata"]["physical_agent_surface"] == "test_stream"
    assert call["payload"]["reasoning"] == {"effort": "medium", "summary": "auto"}


def test_stream_chat_text_error_redacts_api_key(fake_openai):
    fake_openai.responses_outputs = [
        [
            _responses_delta("partial"),
            {
                "type": "error",
                "error": {"message": "Bearer sk-test-key failed"},
            },
        ]
    ]
    settings = OpenAICompatibleSettings(
        api_key="sk-test-key",
        base_url="http://project.test/v1",
        model="test-model",
        api_mode="responses",
    )
    stream = OpenAICompatibleClient(settings).stream_chat_text(
        [{"role": "user", "content": "ping"}]
    )

    assert next(stream) == "partial"
    with pytest.raises(OpenAICompatibleError) as info:
        next(stream)

    assert "sk-test-key" not in str(info.value)
    assert "<redacted>" in str(info.value)


def test_responses_create_input_calls_openai_sdk(fake_openai):
    fake_openai.responses_outputs = [_responses_text("pong")]
    settings = OpenAICompatibleSettings(
        api_key="test-key",
        base_url="http://project.test/v1",
        model="test-model",
        api_mode="responses",
    )

    result = OpenAICompatibleClient(settings).responses_create_input(
        [{"role": "user", "content": "ping"}],
        instructions="Return text.",
        text_format={"type": "json_object"},
        metadata={"physical_agent_surface": "test"},
    )

    assert result["output"][0]["content"][0]["text"] == "pong"
    call = fake_openai.instances[0].calls[0]
    assert call["method"] == "responses.create"
    payload = call["payload"]
    assert payload["input"][0]["role"] == "user"
    assert payload["instructions"] == "Return text."
    assert payload["text"]["format"]["type"] == "json_object"
    assert payload["metadata"]["physical_agent_surface"] == "test"
    assert payload["reasoning"] == {"effort": "medium", "summary": "auto"}


def test_responses_create_input_passes_configured_reasoning(fake_openai):
    fake_openai.responses_outputs = [_responses_text("pong")]
    settings = OpenAICompatibleSettings(
        api_key="test-key",
        base_url="http://project.test/v1",
        model="test-model",
        api_mode="responses",
        reasoning_effort="high",
        reasoning_summary="detailed",
    )

    OpenAICompatibleClient(settings).responses_create_input(
        [{"role": "user", "content": "ping"}]
    )

    payload = fake_openai.instances[0].calls[0]["payload"]
    assert payload["reasoning"] == {"effort": "high", "summary": "detailed"}


def test_responses_create_input_omits_reasoning_when_disabled(fake_openai):
    fake_openai.responses_outputs = [_responses_text("pong")]
    settings = OpenAICompatibleSettings(
        api_key="test-key",
        base_url="http://project.test/v1",
        model="test-model",
        api_mode="responses",
        reasoning_enabled=False,
    )

    OpenAICompatibleClient(settings).responses_create_input(
        [{"role": "user", "content": "ping"}]
    )

    assert "reasoning" not in fake_openai.instances[0].calls[0]["payload"]


def test_chat_completion_reasoning_400_falls_back_without_extra_body(fake_openai):
    fake_openai.chat_outputs = [
        FakeBadRequestError("unknown parameter: thinking"),
        _chat_text("pong"),
    ]
    settings = OpenAICompatibleSettings(
        api_key="test-key",
        base_url="http://project.test/v1",
        model="test-model",
        reasoning_extra_body={"thinking": {"type": "enabled"}},
    )

    result = OpenAICompatibleClient(settings).chat_completion_create(
        [{"role": "user", "content": "ping"}],
        metadata={"physical_agent_surface": "test"},
    )

    assert result["choices"][0]["message"]["content"] == "pong"
    assert result["physical_agent_metadata"]["reasoning_fallback"] is True
    calls = fake_openai.instances[0].calls
    assert calls[0]["payload"]["extra_body"] == {"thinking": {"type": "enabled"}}
    assert "extra_body" not in calls[1]["payload"]
    assert calls[1]["payload"]["metadata"]["reasoning_fallback"] == "true"


def test_responses_reasoning_400_falls_back_without_reasoning(fake_openai):
    fake_openai.responses_outputs = [
        FakeBadRequestError("unsupported parameter: reasoning"),
        _responses_text("pong"),
    ]
    settings = OpenAICompatibleSettings(
        api_key="test-key",
        base_url="http://project.test/v1",
        model="test-model",
        api_mode="responses",
    )

    result = OpenAICompatibleClient(settings).responses_create_input(
        [{"role": "user", "content": "ping"}],
        metadata={"physical_agent_surface": "test"},
    )

    assert result["output"][0]["content"][0]["text"] == "pong"
    assert result["physical_agent_metadata"]["reasoning_fallback"] is True
    calls = fake_openai.instances[0].calls
    assert calls[0]["payload"]["reasoning"] == {"effort": "medium", "summary": "auto"}
    assert "reasoning" not in calls[1]["payload"]
    assert calls[1]["payload"]["metadata"]["reasoning_fallback"] == "true"


def test_stream_chat_reasoning_400_falls_back_without_extra_body(fake_openai):
    fake_openai.chat_outputs = [
        FakeBadRequestError("invalid thinking field"),
        [_chat_delta("pong")],
    ]
    settings = OpenAICompatibleSettings(
        api_key="test-key",
        base_url="http://project.test/v1",
        model="test-model",
        reasoning_extra_body={"thinking": {"type": "enabled"}},
    )

    chunks = list(
        OpenAICompatibleClient(settings).stream_chat_text(
            [{"role": "user", "content": "ping"}]
        )
    )

    assert chunks == ["pong"]
    calls = fake_openai.instances[0].calls
    assert calls[0]["payload"]["extra_body"] == {"thinking": {"type": "enabled"}}
    assert "extra_body" not in calls[1]["payload"]
    assert calls[1]["payload"]["metadata"]["reasoning_fallback"] == "true"


def test_stream_responses_reasoning_400_falls_back_without_reasoning(fake_openai):
    fake_openai.responses_outputs = [
        FakeBadRequestError("invalid reasoning field"),
        [_responses_delta("pong"), {"type": "response.completed"}],
    ]
    settings = OpenAICompatibleSettings(
        api_key="test-key",
        base_url="http://project.test/v1",
        model="test-model",
        api_mode="responses",
    )

    chunks = list(
        OpenAICompatibleClient(settings).stream_chat_text(
            [{"role": "user", "content": "ping"}]
        )
    )

    assert chunks == ["pong"]
    calls = fake_openai.instances[0].calls
    assert calls[0]["payload"]["reasoning"] == {"effort": "medium", "summary": "auto"}
    assert "reasoning" not in calls[1]["payload"]
    assert calls[1]["payload"]["metadata"]["reasoning_fallback"] == "true"


def test_structured_json_strict_json_schema_success(fake_openai):
    fake_openai.chat_outputs = [_chat_text(json.dumps({"answer": "pong"}))]
    settings = OpenAICompatibleSettings(
        api_key="test-key",
        base_url="http://project.test/v1",
        model="test-model",
    )

    result = OpenAICompatibleClient(settings).structured_json(
        [{"role": "user", "content": "ping"}],
        schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
        },
        schema_name="ping_response",
    )

    assert result == {"answer": "pong"}
    payload = fake_openai.instances[0].calls[0]["payload"]
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["name"] == "ping_response"
    assert payload["response_format"]["json_schema"]["strict"] is True


def test_structured_json_strict_400_falls_back_to_json_object(fake_openai):
    fake_openai.chat_outputs = [
        FakeBadRequestError("schema unsupported for test-key"),
        _chat_text(json.dumps({"answer": "pong"})),
    ]
    settings = OpenAICompatibleSettings(
        api_key="test-key",
        base_url="http://project.test/v1",
        model="test-model",
    )

    result = OpenAICompatibleClient(settings).structured_json(
        [{"role": "user", "content": "ping"}],
        schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
        },
        schema_name="ping_response",
    )

    assert result == {"answer": "pong"}
    calls = fake_openai.instances[0].calls
    assert calls[0]["payload"]["response_format"]["type"] == "json_schema"
    assert calls[1]["payload"]["response_format"] == {"type": "json_object"}
    assert "JSON" in calls[1]["payload"]["messages"][0]["content"]
    assert "test-key" not in str(calls)


def test_structured_json_json_object_400_falls_back_to_plain_json_prompt(fake_openai):
    fake_openai.chat_outputs = [
        FakeBadRequestError("schema unsupported"),
        FakeBadRequestError("response_format.type json_object is not supported"),
        _chat_text(json.dumps({"answer": "pong"})),
    ]
    settings = OpenAICompatibleSettings(
        api_key="test-key",
        base_url="http://project.test/v1",
        model="test-model",
    )

    result = OpenAICompatibleClient(settings).structured_json(
        [{"role": "user", "content": "ping"}],
        schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
        },
        schema_name="ping_response",
    )

    assert result == {"answer": "pong"}
    calls = fake_openai.instances[0].calls
    assert calls[0]["payload"]["response_format"]["type"] == "json_schema"
    assert calls[1]["payload"]["response_format"] == {"type": "json_object"}
    assert "response_format" not in calls[2]["payload"]
    assert "JSON" in calls[2]["payload"]["messages"][0]["content"]


def test_structured_json_fallback_still_validates_schema(fake_openai):
    fake_openai.chat_outputs = [
        FakeBadRequestError("schema unsupported"),
        _chat_text(json.dumps({"answer": 123})),
    ]
    settings = OpenAICompatibleSettings(
        api_key="test-key",
        base_url="http://project.test/v1",
        model="test-model",
    )

    with pytest.raises(OpenAICompatibleError, match="did not match schema"):
        OpenAICompatibleClient(settings).structured_json(
            [{"role": "user", "content": "ping"}],
            schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["answer"],
                "properties": {"answer": {"type": "string"}},
            },
            schema_name="ping_response",
        )


def test_responses_structured_json_uses_responses_text_format(fake_openai):
    fake_openai.responses_outputs = [_responses_text(json.dumps({"answer": "pong"}))]
    settings = OpenAICompatibleSettings(
        api_key="test-key",
        base_url="http://project.test/v1",
        model="test-model",
        api_mode="responses",
    )

    result = OpenAICompatibleClient(settings).structured_json(
        [
            {"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "ping"},
        ],
        schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
        },
        schema_name="ping_response",
        metadata={"physical_agent_surface": "test"},
    )

    assert result == {"answer": "pong"}
    payload = fake_openai.instances[0].calls[0]["payload"]
    assert payload["instructions"] == "Return JSON."
    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["text"]["format"]["name"] == "ping_response"
    assert payload["metadata"]["physical_agent_surface"] == "test"


def test_structured_json_responses_strict_400_falls_back_to_json_object(fake_openai):
    fake_openai.responses_outputs = [
        FakeBadRequestError("strict schema unsupported"),
        _responses_text(json.dumps({"answer": "pong"})),
    ]
    settings = OpenAICompatibleSettings(
        api_key="test-key",
        base_url="http://project.test/v1",
        model="test-model",
        api_mode="responses",
    )

    result = OpenAICompatibleClient(settings).structured_json(
        [{"role": "user", "content": "ping"}],
        schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
        },
        schema_name="ping_response",
    )

    assert result == {"answer": "pong"}
    calls = fake_openai.instances[0].calls
    assert calls[0]["payload"]["text"]["format"]["type"] == "json_schema"
    assert calls[1]["payload"]["text"]["format"] == {"type": "json_object"}
    assert "JSON" in calls[1]["payload"]["instructions"]


def test_structured_json_responses_json_object_400_falls_back_to_plain_json_prompt(fake_openai):
    fake_openai.responses_outputs = [
        FakeBadRequestError("strict schema unsupported"),
        FakeBadRequestError("text.format.type json_object is not supported"),
        _responses_text(json.dumps({"answer": "pong"})),
    ]
    settings = OpenAICompatibleSettings(
        api_key="test-key",
        base_url="http://project.test/v1",
        model="test-model",
        api_mode="responses",
    )

    result = OpenAICompatibleClient(settings).structured_json(
        [{"role": "user", "content": "ping"}],
        schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
        },
        schema_name="ping_response",
    )

    assert result == {"answer": "pong"}
    calls = fake_openai.instances[0].calls
    assert calls[0]["payload"]["text"]["format"]["type"] == "json_schema"
    assert calls[1]["payload"]["text"]["format"] == {"type": "json_object"}
    assert "text" not in calls[2]["payload"]
    assert "JSON" in calls[2]["payload"]["instructions"]


def test_error_mapping_redacts_api_key(fake_openai):
    fake_openai.chat_outputs = [FakeRateLimitError("Bearer sk-test-key was limited")]
    settings = OpenAICompatibleSettings(
        api_key="sk-test-key",
        base_url="http://project.test/v1",
        model="test-model",
    )

    with pytest.raises(OpenAICompatibleError) as info:
        OpenAICompatibleClient(settings).chat_completion_create(
            [{"role": "user", "content": "ping"}]
        )

    assert info.value.status_code == 429
    assert info.value.kind == "rate_limit"
    assert "sk-test-key" not in str(info.value)
    assert "<redacted>" in str(info.value)


def test_llm_planner_parses_actions_from_chat_completion(fake_openai):
    fake_openai.chat_outputs = [
        _chat_text(
            json.dumps(
                {
                    "actions": [
                        {
                            "robot": "arm_1",
                            "capability": "pick",
                            "params": {"object_id": "red_block"},
                            "reason": "Pick the requested object.",
                            "depends_on": [],
                        },
                        {
                            "robot": "arm_1",
                            "capability": "place",
                            "params": {"target": "tray"},
                            "reason": "Place it on the tray.",
                            "depends_on": ["arm_1:pick:red_block"],
                            "metadata": {
                                "expected": [
                                    {
                                        "path": "objects.red_block.location",
                                        "op": "eq",
                                        "value": "tray",
                                    }
                                ]
                            },
                        },
                    ]
                }
            )
        )
    ]
    settings = OpenAICompatibleSettings(
        api_key="test-key",
        base_url="http://project.test/v1",
        model="test-model",
    )

    planner = LLMPlanner(settings=settings)
    actions = planner.plan(
        task="pick the red block and place it on the tray",
        capabilities={
            "robots": {
                "arm_1": {
                    "capabilities": [
                        {"name": "pick"},
                        {"name": "place"},
                    ]
                }
            }
        },
        world={
            "state": {"objects": {"red_block": {}, "tray": {}}},
            "observation": Observation(summary="Arm sees a red block and a tray."),
        },
    )

    assert [action.capability for action in actions] == ["pick", "place"]
    assert actions[0].id == "act_001"
    assert actions[1].depends_on == ["act_001"]
    assert actions[1].metadata["expected"][0]["value"] == "tray"
    payload = fake_openai.instances[0].calls[0]["payload"]
    assert payload["response_format"]["type"] == "json_schema"


def test_llm_planner_parses_actions_from_responses_api(fake_openai):
    fake_openai.responses_outputs = [
        _responses_text(
            json.dumps(
                {
                    "actions": [
                        {
                            "robot": "arm_1",
                            "capability": "observe",
                            "params": {},
                            "reason": "Inspect world state.",
                            "depends_on": [],
                        }
                    ]
                }
            )
        )
    ]
    settings = OpenAICompatibleSettings(
        api_key="test-key",
        base_url="http://project.test/v1",
        model="test-model",
        api_mode="responses",
    )

    planner = LLMPlanner(settings=settings)
    actions = planner.plan(
        task="look around",
        capabilities={"robots": {"arm_1": {"capabilities": [{"name": "observe"}]}}},
        world={"state": {}, "observation": Observation(summary="")},
    )

    assert [action.capability for action in actions] == ["observe"]
    payload = fake_openai.instances[0].calls[0]["payload"]
    assert "JSON action intents" in payload["instructions"]
    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["metadata"]["physical_agent_surface"] == "planner"
