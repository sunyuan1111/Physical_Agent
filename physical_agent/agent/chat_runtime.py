from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from physical_agent.agent.llm_planner import _json_safe, _normalize_depends_on
from physical_agent.agent.onboarding import HardwareIntegrationAssistant
from physical_agent.agent.rule_based import RuleBasedPlanner
from physical_agent.config import DEFAULT_CONFIG_NAME, PhysicalAgentConfig, load_config, write_default_config
from physical_agent.llm import OpenAICompatibleClient, OpenAICompatibleSettings
from physical_agent.protocol.schemas import Action, ChatMessage, ChatPlan
from physical_agent.protocol.workspace import Workspace
from physical_agent.watch.runtime import WatchRuntime


class ChatRuntime:
    def __init__(
        self,
        config_path: str | Path = DEFAULT_CONFIG_NAME,
        *,
        planner_name: str | None = None,
        model: str | None = None,
    ):
        self.config_path = Path(config_path).resolve()
        self.base_dir = self.config_path.parent
        self.planner_name = planner_name
        self.model = model
        self.config: PhysicalAgentConfig | None = None
        self.workspace: Workspace | None = None
        self.rule_planner = RuleBasedPlanner()
        self.llm_client: OpenAICompatibleClient | None = None

    def setup(self) -> None:
        if not self.config_path.exists():
            write_default_config(self.config_path)
        self.config = load_config(self.config_path)
        self.workspace = Workspace(self.config.workspace_path(self.base_dir))
        self.workspace.initialize()

    def respond(self, message: str, *, auto_step: bool = False) -> dict[str, Any]:
        self.setup()
        workspace = self._workspace()
        workspace.append_chat_message("user", message)

        if self._looks_like_integration_request(message):
            response = self._respond_with_integration(message)
            actions: list[Action] = []
            notes: list[str] = []
            executed = 0
            plan = ChatPlan(
                status="answered",
                intent="integrate",
                summary=response["reply"],
                steps=response.get("steps", []),
                actions=[],
                needs_watch=False,
            )
            workspace.write_plan(plan)
            assistant = workspace.append_chat_message(
                "assistant",
                response["reply"],
                metadata={
                    "intent": plan.intent,
                    "integration": response.get("integration", {}),
                    "needs_watch": False,
                    "executed": 0,
                },
            )
            workspace.append_log("Chat assistant generated an integration plan.", actor="agent")
            return {
                "ok": True,
                "mode": "integration",
                "reply": assistant.content,
                "actions": actions,
                "memory": notes,
                "plan": plan.model_dump(mode="json"),
                "executed": executed,
                "feedback": workspace.read_feedback(),
                "integration": response.get("integration", {}),
            }

        capabilities = workspace.read_capabilities()
        world = workspace.read_world()
        feedback = workspace.read_feedback()
        chat = workspace.read_chat()
        memory = workspace.read_memory()

        mode = self._mode()
        if mode == "llm":
            try:
                response = self._respond_with_llm(
                    message=message,
                    chat_messages=chat["messages"],
                    capabilities=capabilities,
                    world=world,
                    feedback=feedback,
                    memory=memory,
                )
            except Exception as exc:
                if (self.planner_name or "").lower() != "auto":
                    raise
                response = self._respond_with_rules(
                    message=message,
                    capabilities=capabilities,
                    world=world,
                    feedback=feedback,
                    memory=memory,
                )
                response["reply"] = (
                    f"{response['reply']}\n\n"
                    f"LLM chat was unavailable, so I used the rule-based chat fallback. "
                    f"Reason: {exc}"
                )
                mode = "rule_based"
        else:
            response = self._respond_with_rules(
                message=message,
                capabilities=capabilities,
                world=world,
                feedback=feedback,
                memory=memory,
            )

        actions = self._append_actions(response["actions"])
        notes = []
        for note in response.get("memory", []):
            if str(note).strip():
                notes.append(workspace.append_memory_note(str(note).strip()))

        executed = 0
        if auto_step and actions:
            watch = WatchRuntime(self.config_path)
            import asyncio

            asyncio.run(watch.setup())
            executed = asyncio.run(watch.step(setup=False))
            asyncio.run(watch.shutdown())
            feedback = workspace.read_feedback()

        plan = ChatPlan(
            status="proposed_actions" if actions else "answered",
            intent=response.get("intent", "chat"),
            summary=response["reply"],
            steps=response.get("steps", []),
            actions=actions,
            needs_watch=bool(actions and not auto_step),
        )
        workspace.write_plan(plan)
        assistant = workspace.append_chat_message(
            "assistant",
            response["reply"],
            metadata={
                "intent": plan.intent,
                "actions": [action.model_dump(mode="json") for action in actions],
                "needs_watch": plan.needs_watch,
                "executed": executed,
            },
        )
        workspace.append_log("Chat agent replied.", actor="agent")

        return {
            "ok": True,
            "mode": mode,
            "reply": assistant.content,
            "actions": [action.model_dump(mode="json") for action in actions],
            "memory": notes,
            "plan": plan.model_dump(mode="json"),
            "executed": executed,
            "feedback": feedback if auto_step else workspace.read_feedback(),
        }

    def _respond_with_integration(self, message: str) -> dict[str, Any]:
        source = self._extract_integration_source(message)
        if not source:
            return {
                "reply": (
                    "I can help you connect a hardware repo or SDK. "
                    "Give me a GitHub URL, a local path, or a package name, and I will generate "
                    "a driver scaffold, README, and integration notes."
                ),
                "steps": [],
                "integration": {},
            }
        assistant = HardwareIntegrationAssistant(source, base_dir=self.base_dir)
        result = assistant.generate()
        profile = result.source
        steps = [
            f"Source detected: {profile.source_kind}",
            f"Transport detected: {profile.transport}",
            f"Robot kind detected: {profile.robot_kind}",
            f"Generated scaffold at: {result.output_path}",
        ]
        reply = (
            f"I analyzed `{source}` and generated a Physical Agent driver scaffold at "
            f"`{result.output_path}`. "
            f"It detected `{profile.robot_kind}` over `{profile.transport}` and found "
            f"{len(profile.capabilities)} capability template(s)."
        )
        return {
            "reply": reply,
            "steps": steps,
            "integration": {
                "source": profile.model_dump(mode="json"),
                "output_path": str(result.output_path),
                "generated_files": result.generated_files,
            },
        }

    def history(self) -> list[ChatMessage]:
        self.setup()
        return self._workspace().read_chat()["messages"]

    def _respond_with_llm(
        self,
        *,
        message: str,
        chat_messages: list[ChatMessage],
        capabilities: dict[str, Any],
        world: dict[str, Any],
        feedback: dict[str, Any],
        memory: dict[str, Any],
    ) -> dict[str, Any]:
        client = self._llm_client()
        content = client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are the chat brain for Physical Agent. "
                        "You can converse with the human, inspect Markdown workspace state, "
                        "and propose physical actions. You must never claim a physical action "
                        "has been executed unless feedback says it completed. "
                        "Return only JSON with this shape: "
                        '{"reply":"human-facing response","intent":"chat|inspect|act|remember",'
                        '"steps":["..."],"actions":[{"robot":"...","capability":"...",'
                        '"params":{},"reason":"...","depends_on":[]}],"memory":["..."]}. '
                        "Use only listed robots/capabilities. If proposing actions, explain that "
                        "watch will validate and execute them."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "latest_user_message": message,
                            "chat_history": [
                                item.model_dump(mode="json") for item in chat_messages[-12:]
                            ],
                            "memory": memory.get("notes", [])[-20:],
                            "capabilities": _json_safe(capabilities),
                            "world": _json_safe(world),
                            "feedback": _json_safe(feedback),
                        },
                        ensure_ascii=True,
                    ),
                },
            ],
            temperature=0.2,
            max_tokens=1500,
        )
        payload = _extract_json_object(content)
        return _normalize_chat_payload(payload)

    def _respond_with_rules(
        self,
        *,
        message: str,
        capabilities: dict[str, Any],
        world: dict[str, Any],
        feedback: dict[str, Any],
        memory: dict[str, Any],
    ) -> dict[str, Any]:
        text = message.lower().strip()
        notes: list[str] = []
        remember_match = re.search(r"\bremember(?: that)?\s+(.+)", message, re.IGNORECASE)
        if remember_match:
            note = remember_match.group(1).strip()
            notes.append(note)
            return {
                "reply": f"I will remember: {note}",
                "intent": "remember",
                "steps": [],
                "actions": [],
                "memory": notes,
            }

        actions = self.rule_planner.plan(task=message, capabilities=capabilities, world=world)
        if actions:
            names = ", ".join(f"{action.robot}.{action.capability}" for action in actions)
            return {
                "reply": (
                    f"I proposed {len(actions)} action(s): {names}. "
                    "Watch will validate them before anything touches the physical world."
                ),
                "intent": "act",
                "steps": ["Interpret the task.", "Write proposed actions to ACTIONS.md."],
                "actions": [action.model_dump(mode="json") for action in actions],
                "memory": [],
            }

        if "status" in text or "world" in text or "see" in text:
            latest = feedback.get("latest", {})
            reply = world.get("summary") or "No world state has been published yet."
            if latest:
                reply += f" Latest feedback: {latest.get('status')} - {latest.get('message')}"
            return {
                "reply": reply,
                "intent": "inspect",
                "steps": [],
                "actions": [],
                "memory": [],
            }

        if "memory" in text or "remember" in text:
            notes_text = "; ".join(note.get("content", "") for note in memory.get("notes", [])[-5:])
            return {
                "reply": notes_text or "I do not have saved memory notes yet.",
                "intent": "inspect",
                "steps": [],
                "actions": [],
                "memory": [],
            }

        return {
            "reply": (
                "I can chat about the workspace, remember short notes, or propose actions like "
                "`look around` and `pick the red block and place it on the tray`."
            ),
            "intent": "chat",
            "steps": [],
            "actions": [],
            "memory": [],
        }

    def _append_actions(self, actions_data: list[dict[str, Any]]) -> list[Action]:
        if not actions_data:
            return []
        workspace = self._workspace()
        board = workspace.read_actions()
        existing = board["pending"] + board["completed"] + board["cancelled"]
        used_ids = {action.id for action in existing}
        for item in workspace.read_feedback().get("history", []):
            action_id = item.get("action_id")
            if action_id:
                used_ids.add(str(action_id))
        start = _max_action_number(used_ids) + 1
        normalized: list[dict[str, Any]] = []
        for offset, item in enumerate(actions_data):
            action_item = dict(item)
            action_item["id"] = f"act_{start + offset:03d}"
            action_item.setdefault("params", {})
            normalized.append(action_item)
        action_ids = [item["id"] for item in normalized]
        actions = []
        for index, item in enumerate(normalized):
            item["depends_on"] = _normalize_depends_on(
                item.get("depends_on", []),
                action_ids,
                current_index=index,
            )
            actions.append(Action.model_validate(item))
        workspace.write_actions(board["pending"] + actions, board["completed"], board["cancelled"])
        return actions

    def _mode(self) -> str:
        config = self._config()
        mode = (self.planner_name or config.agent.planner or "rule_based").lower()
        if mode == "auto":
            try:
                self._llm_client()
                return "llm"
            except Exception:
                return "rule_based"
        if mode in {"llm", "openai", "openai_compatible", "openai-compatible"}:
            return "llm"
        return "rule_based"

    def _looks_like_integration_request(self, message: str) -> bool:
        text = message.lower()
        has_source = bool(self._extract_integration_source(message))
        direct_phrases = (
            "integrate",
            "onboard",
            "connect this hardware",
            "hardware repo",
            "github",
            "sdk",
            "接入",
            "适配",
            "仓库",
            "驱动",
            "硬件",
        )
        if has_source and any(phrase in text for phrase in direct_phrases):
            return True
        return any(
            phrase in text
            for phrase in (
                "generate a driver",
                "create a driver",
                "new hardware driver",
                "帮我接入",
                "帮我适配",
                "生成驱动",
                "接入硬件",
            )
        )

    def _extract_integration_source(self, message: str) -> str | None:
        url_match = re.search(r"(https?://[^\s]+github\.com/[^\s]+|git@github\.com:[^\s]+)", message, re.IGNORECASE)
        if url_match:
            return url_match.group(1).rstrip(".,)")
        path_match = re.search(r"(?:(?:[A-Za-z]:[\\/])|(?:\./)|(?:\.\\/)|(?:~/)|(?:/))[^\s]+", message)
        if path_match:
            return path_match.group(0).rstrip(".,)")
        package_match = re.search(r"(?:package|sdk|repo|仓库|项目|路径)\s*[:：]?\s*([A-Za-z0-9_.-]+)", message, re.IGNORECASE)
        if package_match:
            return package_match.group(1).strip()
        return None

    def _llm_client(self) -> OpenAICompatibleClient:
        if self.llm_client is None:
            config = self._config()
            model = self.model
            if model is None and config.agent.model != "fake/local":
                model = config.agent.model
            settings = OpenAICompatibleSettings.from_env(
                env_file=self.base_dir / ".env",
                model=model,
            )
            self.llm_client = OpenAICompatibleClient(settings)
        return self.llm_client

    def _workspace(self) -> Workspace:
        if self.workspace is None:
            raise RuntimeError("ChatRuntime has not been set up.")
        return self.workspace

    def _config(self) -> PhysicalAgentConfig:
        if self.config is None:
            raise RuntimeError("ChatRuntime has not been set up.")
        return self.config


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("Chat response must be a JSON object.")
    return value


def _normalize_chat_payload(payload: dict[str, Any]) -> dict[str, Any]:
    actions = payload.get("actions", [])
    if not isinstance(actions, list):
        actions = []
    memory = payload.get("memory", [])
    if isinstance(memory, str):
        memory = [memory]
    if not isinstance(memory, list):
        memory = []
    steps = payload.get("steps", [])
    if isinstance(steps, str):
        steps = [steps]
    if not isinstance(steps, list):
        steps = []
    return {
        "reply": str(payload.get("reply") or "I updated the chat workspace."),
        "intent": str(payload.get("intent") or "chat"),
        "steps": [str(step) for step in steps],
        "actions": [item for item in actions if isinstance(item, dict)],
        "memory": [str(item) for item in memory],
    }


def _max_action_number(action_ids: set[str]) -> int:
    maximum = 0
    for action_id in action_ids:
        if action_id.startswith("act_"):
            try:
                maximum = max(maximum, int(action_id.removeprefix("act_")))
            except ValueError:
                continue
    return maximum
