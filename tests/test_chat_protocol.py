from physical_agent.protocol.chat_summary import summarize_chat_messages
from physical_agent.protocol.parsers import parse_chat, parse_memory, parse_plan
from physical_agent.protocol.renderers import render_chat, render_memory, render_plan
from physical_agent.protocol.schemas import ChatMessage, ChatPlan
from physical_agent.protocol.workspace import Workspace


def test_chat_plan_memory_render_parse_roundtrip():
    chat = render_chat(
        [ChatMessage(role="user", content="hello")],
        running_summary="older chat summary",
    )
    parsed_chat = parse_chat(chat)
    assert parsed_chat["running_summary"] == "older chat summary"
    assert parsed_chat["messages"][0].content == "hello"

    plan = render_plan(
        ChatPlan(
            status="answered",
            intent="chat",
            summary="hello back",
            steps=["read chat"],
        )
    )
    parsed_plan = parse_plan(plan)
    assert parsed_plan["plan"].summary == "hello back"
    assert parsed_plan["plan"].steps == ["read chat"]

    memory = render_memory(
        [
            {
                "content": "prefers cautious execution",
                "source": "test",
                "kind": "preference",
                "tags": ["safety"],
                "importance": 2,
            }
        ]
    )
    parsed_memory = parse_memory(memory)
    assert parsed_memory["notes"][0]["content"] == "prefers cautious execution"
    assert parsed_memory["notes"][0]["kind"] == "preference"
    assert parsed_memory["notes"][0]["tags"] == ["safety"]
    assert parsed_memory["notes"][0]["importance"] == 2


def test_workspace_chat_helpers(tmp_path):
    workspace = Workspace(tmp_path / "workspace")
    workspace.initialize()
    workspace.append_chat_message("user", "remember that I prefer simulation first")
    workspace.append_chat_message("assistant", "Noted.")
    workspace.append_memory_note(
        "User prefers simulation first.",
        kind="preference",
        tags=["simulation"],
        importance=1,
    )
    workspace.write_plan({"status": "answered", "intent": "remember", "summary": "Noted."})

    assert workspace.read_chat()["messages"][0].role == "user"
    assert workspace.read_memory()["notes"][0]["content"] == "User prefers simulation first."
    assert workspace.read_memory(kind="preference", tags=["simulation"])["notes"][0][
        "importance"
    ] == 1
    assert workspace.read_plan()["plan"].intent == "remember"


def test_workspace_chat_generates_running_summary_after_threshold(tmp_path):
    workspace = Workspace(tmp_path / "workspace")
    workspace.initialize()

    for index in range(25):
        workspace.append_chat_message("user", f"message {index}")

    chat = workspace.read_chat()
    assert len(chat["messages"]) == 12
    assert [message.content for message in chat["messages"]] == [
        f"message {index}" for index in range(13, 25)
    ]
    assert "message 0" in chat["running_summary"]
    assert "message 12" in chat["running_summary"]

    workspace.append_chat_message("assistant", "reply after summary")
    chat = workspace.read_chat()
    assert len(chat["messages"]) == 12
    assert [message.content for message in chat["messages"]] == [
        *[f"message {index}" for index in range(14, 25)],
        "reply after summary",
    ]
    assert "message 13" in chat["running_summary"]


def test_chat_summary_trim_respects_tiny_budget():
    summary = summarize_chat_messages(
        [ChatMessage(role="user", content="x" * 100)],
        running_summary="older " * 20,
        max_chars=10,
    )

    assert summary == "[Earlier s"
    assert len(summary) <= 10

