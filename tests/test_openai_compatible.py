from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from physical_agent.agent.llm_planner import LLMPlanner
from physical_agent.env import load_dotenv
from physical_agent.llm import OpenAICompatibleClient, OpenAICompatibleSettings
from physical_agent.protocol.schemas import Observation


class _ChatHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []
    content = "pong"

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        self.__class__.requests.append(payload)
        response = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": self.__class__.content,
                    }
                }
            ]
        }
        body = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


def _server():
    _ChatHandler.requests = []
    _ChatHandler.content = "pong"
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ChatHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_load_dotenv_sets_gpt_env_names(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("GPT_URL=http://example.test/v1\nGPT_KEY=secret\n", encoding="utf-8")
    monkeypatch.delenv("GPT_URL", raising=False)
    monkeypatch.delenv("GPT_KEY", raising=False)
    loaded = load_dotenv(env_file)
    assert loaded["GPT_URL"] == "http://example.test/v1"
    assert loaded["GPT_KEY"] == "secret"


def test_openai_settings_prefers_project_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GPT_URL=http://project.test/v1\n"
        "GPT_KEY=project-key\n"
        "GPT_MODEL=project-model\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GPT_URL", "http://global.test/v1")
    monkeypatch.setenv("GPT_KEY", "global-key")
    monkeypatch.setenv("GPT_MODEL", "global-model")

    settings = OpenAICompatibleSettings.from_env(env_file=env_file)

    assert settings.base_url == "http://project.test/v1"
    assert settings.api_key == "project-key"
    assert settings.model == "project-model"


def test_openai_compatible_client_posts_chat_completion():
    server = _server()
    try:
        settings = OpenAICompatibleSettings(
            api_key="test-key",
            base_url=f"http://127.0.0.1:{server.server_address[1]}/v1",
            model="test-model",
        )
        result = OpenAICompatibleClient(settings).test_connection()
        assert result["ok"] is True
        assert result["content"] == "pong"
        assert _ChatHandler.requests[0]["model"] == "test-model"
        assert _ChatHandler.requests[0]["messages"][0]["role"] == "system"
    finally:
        server.shutdown()
        server.server_close()


def test_llm_planner_parses_actions_from_chat_completion():
    server = _server()
    _ChatHandler.content = json.dumps(
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
                },
            ]
        }
    )
    try:
        settings = OpenAICompatibleSettings(
            api_key="test-key",
            base_url=f"http://127.0.0.1:{server.server_address[1]}/v1",
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
    finally:
        server.shutdown()
        server.server_close()
