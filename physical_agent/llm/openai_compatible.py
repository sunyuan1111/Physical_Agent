from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from physical_agent.env import load_dotenv


DEFAULT_MODEL = "gpt-5.4"


class OpenAICompatibleError(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenAICompatibleSettings:
    api_key: str
    base_url: str
    model: str
    timeout_s: int = 60

    @classmethod
    def from_env(
        cls,
        *,
        env_file: str | Path = ".env",
        model: str | None = None,
        timeout_s: int = 60,
    ) -> "OpenAICompatibleSettings":
        load_dotenv(env_file)
        api_key = (
            os.getenv("OPENAI_API_KEY")
            or os.getenv("GPT_KEY")
            or os.getenv("API_KEY")
            or ""
        ).strip()
        base_url = (
            os.getenv("OPENAI_BASE_URL")
            or os.getenv("GPT_URL")
            or os.getenv("BASE_URL")
            or "https://api.openai.com/v1"
        ).strip()
        resolved_model = (
            model
            or os.getenv("OPENAI_MODEL")
            or os.getenv("GPT_MODEL")
            or os.getenv("MODEL")
            or DEFAULT_MODEL
        ).strip()
        if not api_key:
            raise OpenAICompatibleError(
                "Missing API key. Set OPENAI_API_KEY or GPT_KEY in .env."
            )
        if not base_url:
            raise OpenAICompatibleError(
                "Missing base URL. Set OPENAI_BASE_URL or GPT_URL in .env."
            )
        if not resolved_model:
            raise OpenAICompatibleError(
                "Missing model. Set OPENAI_MODEL or GPT_MODEL in .env."
            )
        return cls(
            api_key=api_key,
            base_url=base_url,
            model=resolved_model,
            timeout_s=timeout_s,
        )

    @property
    def chat_completions_url(self) -> str:
        url = self.base_url.rstrip("/")
        if url.endswith("/chat/completions"):
            return url
        if url.endswith("/v1"):
            return f"{url}/chat/completions"
        return f"{url}/v1/chat/completions"

    def public_summary(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "chat_completions_url": self.chat_completions_url,
            "model": self.model,
            "api_key": "<set>",
            "timeout_s": self.timeout_s,
        }


class OpenAICompatibleClient:
    def __init__(self, settings: OpenAICompatibleSettings):
        self.settings = settings

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        payload = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.settings.chat_completions_url,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.settings.timeout_s) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise OpenAICompatibleError(
                f"API request failed with HTTP {exc.code}: {_short_error(body)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise OpenAICompatibleError(f"API request failed: {exc.reason}") from exc

        try:
            parsed = json.loads(body)
            return parsed["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise OpenAICompatibleError(
                f"API response did not match OpenAI chat completions shape: {_short_error(body)}"
            ) from exc

    def test_connection(self, *, prompt: str = "Reply with exactly: pong") -> dict[str, Any]:
        content = self.chat(
            [
                {
                    "role": "system",
                    "content": "You are a terse connectivity test endpoint.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=32,
        )
        return {
            "ok": True,
            "model": self.settings.model,
            "endpoint": self.settings.chat_completions_url,
            "content": content.strip(),
        }


def _short_error(body: str, *, limit: int = 500) -> str:
    compact = " ".join(body.split())
    if len(compact) > limit:
        return compact[: limit - 3] + "..."
    return compact
