from __future__ import annotations

import re
from typing import Any

from physical_agent.protocol.schemas import ChatMessage


DEFAULT_RECENT_CHAT_MESSAGES = 12
DEFAULT_CHAT_SUMMARIZE_THRESHOLD = 24
DEFAULT_RUNNING_SUMMARY_CHARS = 6000
DEFAULT_SUMMARY_MESSAGE_CHARS = 220


def compact_chat_messages(
    messages: list[ChatMessage | dict[str, Any]],
    *,
    running_summary: str = "",
    max_recent: int = DEFAULT_RECENT_CHAT_MESSAGES,
    threshold: int = DEFAULT_CHAT_SUMMARIZE_THRESHOLD,
) -> tuple[str, list[ChatMessage]]:
    normalized = [
        item if isinstance(item, ChatMessage) else ChatMessage.model_validate(item)
        for item in messages
    ]
    has_summary = bool(running_summary.strip())
    over_threshold = len(normalized) > threshold
    over_recent_after_summary = has_summary and len(normalized) > max(1, max_recent)
    if not over_threshold and not over_recent_after_summary:
        return running_summary.strip(), normalized

    recent_count = max(1, max_recent)
    older = normalized[:-recent_count]
    recent = normalized[-recent_count:]
    updated_summary = summarize_chat_messages(
        older,
        running_summary=running_summary,
    )
    return updated_summary, recent


def summarize_chat_messages(
    messages: list[ChatMessage],
    *,
    running_summary: str = "",
    max_chars: int = DEFAULT_RUNNING_SUMMARY_CHARS,
) -> str:
    parts: list[str] = []
    existing = running_summary.strip()
    if existing:
        parts.append(existing)
    if messages:
        parts.append("Earlier chat messages:")
        parts.extend(f"- {_message_summary_line(message)}" for message in messages)
    summary = "\n".join(part for part in parts if part).strip()
    return _trim_summary(summary, max_chars=max_chars)


def recent_chat_messages(
    messages: list[ChatMessage],
    *,
    max_recent: int = DEFAULT_RECENT_CHAT_MESSAGES,
) -> list[ChatMessage]:
    recent_count = max(1, max_recent)
    return list(messages[-recent_count:])


def _message_summary_line(message: ChatMessage) -> str:
    content = _collapse_whitespace(message.content)
    role = message.role
    created = f" @ {message.created_at}" if message.created_at else ""
    return f"{role}{created}: {_truncate(content, DEFAULT_SUMMARY_MESSAGE_CHARS)}"


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _trim_summary(summary: str, *, max_chars: int) -> str:
    if len(summary) <= max_chars:
        return summary
    marker = "[Earlier summary trimmed]\n"
    budget = max_chars - len(marker)
    if budget <= 0:
        return marker[:max_chars]
    return marker + summary[-budget:].lstrip()
