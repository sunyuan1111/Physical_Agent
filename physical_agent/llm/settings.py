from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from physical_agent.env import load_dotenv


DEFAULT_LLM_SETTINGS_NAME = ".llm.json"
DEFAULT_API_MODE = "chat_completions"
DEFAULT_REASONING_ENABLED = True
DEFAULT_REASONING_EFFORT = "medium"
DEFAULT_REASONING_SUMMARY = "auto"
SUPPORTED_API_MODES = {"chat_completions", "responses"}
LLM_SETTING_KEYS = (
    "base_url",
    "api_key",
    "model",
    "api_mode",
    "reasoning_enabled",
    "reasoning_effort",
    "reasoning_summary",
    "reasoning_extra_body",
)
_TEXT_SETTING_KEYS = (
    "base_url",
    "api_key",
    "model",
    "api_mode",
    "reasoning_effort",
    "reasoning_summary",
)


class LLMSettingsError(ValueError):
    """Raised when local LLM settings cannot be read or written."""


def llm_settings_path(workspace_path: str | Path) -> Path:
    return Path(workspace_path).resolve() / DEFAULT_LLM_SETTINGS_NAME


def default_llm_settings_path(env_file: str | Path = ".env") -> Path:
    env_path = Path(env_file)
    base_dir = env_path.parent if env_path.parent != Path("") else Path(".")
    return (base_dir / "workspace" / DEFAULT_LLM_SETTINGS_NAME).resolve()


def read_llm_settings_file(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    settings_path = Path(path)
    if not settings_path.exists():
        return {}
    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LLMSettingsError(f"Could not parse {settings_path}: {exc.msg}") from exc
    except OSError as exc:
        raise LLMSettingsError(f"Could not read {settings_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise LLMSettingsError(f"{settings_path} must contain a JSON object.")
    return _normalize_settings(raw)


def write_llm_settings_file(
    path: str | Path,
    values: Mapping[str, Any],
    *,
    preserve_existing_api_key: bool = True,
) -> dict[str, Any]:
    settings_path = Path(path)
    existing = read_llm_settings_file(settings_path)
    data: dict[str, Any] = dict(existing)

    for key in ("base_url", "model", "api_mode", "reasoning_effort", "reasoning_summary"):
        if key in values:
            data[key] = _coerce_text(values.get(key))

    if "api_key" in values:
        api_key = _coerce_text(values.get("api_key"))
        if api_key or not preserve_existing_api_key:
            data["api_key"] = api_key

    if "reasoning_enabled" in values:
        data["reasoning_enabled"] = _coerce_bool(
            values.get("reasoning_enabled"),
            key="reasoning_enabled",
        )
    if "reasoning_extra_body" in values:
        extra_body = _coerce_json_object(
            values.get("reasoning_extra_body"),
            key="reasoning_extra_body",
            allow_empty=True,
        )
        if extra_body:
            data["reasoning_extra_body"] = extra_body
        else:
            data.pop("reasoning_extra_body", None)

    if not data.get("api_mode"):
        data["api_mode"] = DEFAULT_API_MODE
    if data["api_mode"] not in SUPPORTED_API_MODES:
        raise LLMSettingsError(
            "Unsupported API mode. Use chat_completions or responses."
        )
    if not data.get("reasoning_effort"):
        data["reasoning_effort"] = DEFAULT_REASONING_EFFORT
    if not data.get("reasoning_summary"):
        data["reasoning_summary"] = DEFAULT_REASONING_SUMMARY
    if "reasoning_enabled" not in data:
        data["reasoning_enabled"] = DEFAULT_REASONING_ENABLED

    output = {
        key: data.get(key, "")
        for key in LLM_SETTING_KEYS
        if data.get(key, "") not in ("", None, {})
    }
    output.setdefault("api_mode", DEFAULT_API_MODE)
    output.setdefault("reasoning_enabled", DEFAULT_REASONING_ENABLED)
    output.setdefault("reasoning_effort", DEFAULT_REASONING_EFFORT)
    output.setdefault("reasoning_summary", DEFAULT_REASONING_SUMMARY)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


def resolve_llm_settings_values(
    *,
    env_file: str | Path = ".env",
    model: str | None = None,
    settings_file: str | Path | None = None,
    workspace_path: str | Path | None = None,
) -> dict[str, Any]:
    loaded = load_dotenv(env_file, override=True)
    local_settings = read_llm_settings_file(
        settings_file
        if settings_file is not None
        else (
            llm_settings_path(workspace_path)
            if workspace_path is not None
            else default_llm_settings_path(env_file)
        )
    )
    reasoning_enabled_value = (
        local_settings["reasoning_enabled"]
        if "reasoning_enabled" in local_settings
        else (
            _env_value(loaded, "OPENAI_REASONING_ENABLED", "GPT_REASONING_ENABLED")
            or DEFAULT_REASONING_ENABLED
        )
    )
    reasoning_extra_body = (
        local_settings.get("reasoning_extra_body")
        if "reasoning_extra_body" in local_settings
        else _env_json_object(
            loaded,
            "OPENAI_REASONING_EXTRA_BODY",
            "GPT_REASONING_EXTRA_BODY",
        )
    )
    return {
        "api_key": (
            local_settings.get("api_key")
            or _env_value(loaded, "OPENAI_API_KEY", "GPT_KEY", "API_KEY")
            or ""
        ).strip(),
        "base_url": (
            local_settings.get("base_url")
            or _env_value(loaded, "OPENAI_BASE_URL", "GPT_URL", "BASE_URL")
            or "https://api.openai.com/v1"
        ).strip(),
        "model": (
            model
            or local_settings.get("model")
            or _env_value(loaded, "OPENAI_MODEL", "GPT_MODEL", "MODEL")
            or "gpt-5.4"
        ).strip(),
        "api_mode": (
            local_settings.get("api_mode")
            or _env_value(loaded, "OPENAI_API_MODE", "GPT_API_MODE", "API_MODE")
            or DEFAULT_API_MODE
        ).strip(),
        "reasoning_enabled": _coerce_bool(
            reasoning_enabled_value,
            key="reasoning_enabled",
        ),
        "reasoning_effort": (
            local_settings.get("reasoning_effort")
            or _env_value(loaded, "OPENAI_REASONING_EFFORT", "GPT_REASONING_EFFORT")
            or DEFAULT_REASONING_EFFORT
        ).strip(),
        "reasoning_summary": (
            local_settings.get("reasoning_summary")
            or _env_value(loaded, "OPENAI_REASONING_SUMMARY", "GPT_REASONING_SUMMARY")
            or DEFAULT_REASONING_SUMMARY
        ).strip(),
        "reasoning_extra_body": reasoning_extra_body,
    }


def public_llm_settings_summary(
    settings: Mapping[str, Any],
    *,
    settings_path: str | Path | None = None,
) -> dict[str, Any]:
    api_key = _coerce_text(settings.get("api_key"))
    summary: dict[str, Any] = {
        "base_url": _coerce_text(settings.get("base_url")),
        "model": _coerce_text(settings.get("model")),
        "api_mode": _coerce_text(settings.get("api_mode")) or DEFAULT_API_MODE,
        "reasoning_enabled": _coerce_bool(
            settings.get("reasoning_enabled", DEFAULT_REASONING_ENABLED),
            key="reasoning_enabled",
        ),
        "reasoning_effort": (
            _coerce_text(settings.get("reasoning_effort"))
            or DEFAULT_REASONING_EFFORT
        ),
        "reasoning_summary": (
            _coerce_text(settings.get("reasoning_summary"))
            or DEFAULT_REASONING_SUMMARY
        ),
        "has_reasoning_extra_body": bool(settings.get("reasoning_extra_body")),
        "has_api_key": bool(api_key),
        "masked_api_key": _mask_api_key(api_key),
    }
    if settings_path is not None:
        summary["settings_path"] = str(Path(settings_path).resolve())
    return summary


def _normalize_settings(raw: Mapping[str, Any]) -> dict[str, Any]:
    data = {
        key: _coerce_text(raw.get(key))
        for key in _TEXT_SETTING_KEYS
        if key in raw
    }
    if "reasoning_enabled" in raw:
        data["reasoning_enabled"] = _coerce_bool(
            raw.get("reasoning_enabled"),
            key="reasoning_enabled",
        )
    if "reasoning_extra_body" in raw:
        data["reasoning_extra_body"] = _coerce_json_object(
            raw.get("reasoning_extra_body"),
            key="reasoning_extra_body",
            allow_empty=True,
        )
    if not data.get("api_mode"):
        data["api_mode"] = DEFAULT_API_MODE
    if data["api_mode"] not in SUPPORTED_API_MODES:
        raise LLMSettingsError(
            "Unsupported API mode. Use chat_completions or responses."
        )
    return data


def _coerce_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _coerce_bool(value: Any, *, key: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    text = _coerce_text(value).lower()
    if text in {"1", "true", "yes", "y", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "n", "off", "disabled"}:
        return False
    raise LLMSettingsError(f"{key} must be a boolean value.")


def _coerce_json_object(value: Any, *, key: str, allow_empty: bool = False) -> dict[str, Any]:
    if value in (None, "") and allow_empty:
        return {}
    if isinstance(value, str):
        text = value.strip()
        if not text and allow_empty:
            return {}
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMSettingsError(f"{key} must be a JSON object: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise LLMSettingsError(f"{key} must be a JSON object.")
    return dict(value)


def _env_value(loaded: Mapping[str, str], *names: str) -> str:
    for name in names:
        value = loaded.get(name)
        if value:
            return value
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return ""


def _env_json_object(loaded: Mapping[str, str], *names: str) -> dict[str, Any]:
    value = _env_value(loaded, *names)
    if not value:
        return {}
    return _coerce_json_object(value, key=names[0], allow_empty=True)


def _mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    suffix = api_key[-4:]
    return f"****{suffix}"
