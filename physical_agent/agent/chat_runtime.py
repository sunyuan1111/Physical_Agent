from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from physical_agent.agent.code_runtime import CodeSkillRuntime
from physical_agent.agent.code_router import CodeIntentRouter
from physical_agent.agent.driver_coder import DriverCodingAgent
from physical_agent.agent.llm_planner import _json_safe, _normalize_depends_on
from physical_agent.agent.onboarding import HardwareIntegrationAssistant
from physical_agent.agent.rule_based import RuleBasedPlanner
from physical_agent.agent.skills import SkillRouter
from physical_agent.config import DEFAULT_CONFIG_NAME, PhysicalAgentConfig, load_config, write_default_config
from physical_agent.llm import OpenAICompatibleClient, OpenAICompatibleSettings
from physical_agent.protocol.schemas import Action, ChatMessage, ChatPlan, CodeTaskResult
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
        self.code_runtime: CodeSkillRuntime | None = None
        self.skill_router: SkillRouter | None = None

    def setup(self) -> None:
        if not self.config_path.exists():
            write_default_config(self.config_path)
        self.config = load_config(self.config_path)
        self.workspace = Workspace(self.config.workspace_path(self.base_dir))
        self.workspace.initialize()

    def respond(self, message: str, *, auto_step: bool = False) -> dict[str, Any]:
        self.setup()
        workspace = self._workspace()
        continuation_message = self._code_continuation_message(message)
        routed_message = continuation_message or message
        workspace.append_chat_message("user", message)

        code_result = self._maybe_handle_code_task(routed_message)
        if code_result is not None:
            code_result_data = code_result.model_dump(mode="json")
            if code_result.intent_kind == "sdk_integration":
                integration = dict(code_result_data.get("integration") or {})
                plan = ChatPlan(
                    status="answered",
                    intent="integrate",
                    summary=code_result.summary,
                    steps=[
                        f"Generated files: {', '.join(code_result.changed_files) or 'none'}",
                        f"Tests run: {', '.join(code_result.tests_run) or 'none'}",
                    ],
                    actions=[],
                    needs_watch=False,
                )
                workspace.write_plan(plan)
                assistant = workspace.append_chat_message(
                    "assistant",
                    self._format_code_result(code_result, user_message=message),
                    metadata={
                        "intent": "integrate",
                        "integration": integration,
                        "code_result": code_result_data,
                        "needs_watch": False,
                        "executed": 0,
                    },
                )
                workspace.append_log("Chat assistant generated an integration plan.", actor="agent")
                return {
                    "ok": code_result.ok,
                    "mode": "integration",
                    "reply": assistant.content,
                    "actions": [],
                    "memory": [],
                    "plan": plan.model_dump(mode="json"),
                    "executed": 0,
                    "feedback": workspace.read_feedback(),
                    "code_result": code_result_data,
                    "skills": [skill.as_dict() for skill in self._skill_router().list_skills()],
                    "integration": integration,
                }

            workspace.append_log(
                f"Chat code skill ran for {code_result.rounds} round(s).",
                actor="agent",
            )
            assistant = workspace.append_chat_message(
                "assistant",
                self._format_code_result(code_result, user_message=message),
                metadata={
                    "intent": "code_edit",
                    "code_result": code_result_data,
                },
            )
            return {
                "ok": code_result.ok,
                "mode": "code",
                "reply": assistant.content,
                "actions": [],
                "memory": [],
                "plan": None,
                "executed": 0,
                "feedback": workspace.read_feedback(),
                "code_result": code_result_data,
                "skills": [skill.as_dict() for skill in self._skill_router().list_skills()],
            }

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
                "skills": [skill.as_dict() for skill in self._skill_router().list_skills()],
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
            "code_result": None,
            "skills": [skill.as_dict() for skill in self._skill_router().list_skills()],
        }

    def _maybe_handle_code_task(self, message: str):
        match = self._skill_router().match(message)
        if match is None:
            return None
        try:
            return self._skill_router().run(message)
        except Exception as exc:
            runtime = self._code_runtime()
            lesson = runtime.lessons.append(f"Code skill failed: {exc}")
            return CodeTaskResult(
                summary=f"Code skill failed: {exc}",
                changed_files=[],
                tests_run=[],
                test_output=str(exc),
                lessons_written=[lesson] if lesson else [],
                rounds=0,
                ok=False,
                intent_kind=match.intent.kind,
            )

    def _code_continuation_message(self, message: str) -> str | None:
        text = message.strip()
        if not _looks_like_code_followup(text):
            return None
        workspace = self._workspace()
        messages = workspace.read_chat().get("messages", [])[-6:]
        previous_user_messages = [
            item.content
            for item in messages
            if getattr(item, "role", "") == "user" and item.content != message
        ]
        router = CodeIntentRouter(self.base_dir)
        for previous in reversed(previous_user_messages):
            if router.route(previous) is not None or _mentions_code_capability(previous):
                return f"{previous}\n\nFollow-up confirmation: {message}"
        return None

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
        use_llm = self._integration_request_wants_llm(message) or self._mode() == "llm"
        if use_llm:
            coding_result = DriverCodingAgent(
                source,
                base_dir=self.base_dir,
                model=self.model,
            ).generate()
            result = coding_result.integration
            profile = result.source
            steps = [
                f"Source detected: {profile.source_kind}",
                f"Transport detected: {profile.transport}",
                f"Robot kind detected: {profile.robot_kind}",
                f"Generated scaffold at: {coding_result.output_path}",
                f"LLM driver coding used: {coding_result.llm_used}",
            ]
            reply = (
                f"I analyzed `{source}` and generated a Physical Agent driver draft at "
                f"`{coding_result.output_path}`. "
                f"LLM coding {'updated the driver' if coding_result.llm_used else 'fell back to the safe scaffold'}; "
                f"validation status is `{coding_result.validation.get('ok')}`."
            )
            return {
                "reply": reply,
                "steps": steps,
                "integration": {
                    "source": profile.model_dump(mode="json"),
                    "output_path": str(coding_result.output_path),
                    "generated_files": coding_result.generated_files,
                    "llm_used": coding_result.llm_used,
                    "llm_error": coding_result.llm_error,
                    "summary": coding_result.summary,
                    "validation": coding_result.validation,
                    "next_steps": coding_result.next_steps,
                },
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

    def _integration_request_wants_llm(self, message: str) -> bool:
        text = message.lower()
        return any(
            phrase in text
            for phrase in (
                "--llm",
                "llm",
                "write the driver",
                "implement the driver",
                "real sdk",
                "complete driver",
                "自动实现",
                "真实sdk",
                "真实 sdk",
                "实现driver",
                "实现 driver",
                "写完整",
                "生成完整",
                "接入sdk",
                "接入 sdk",
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

    def _code_runtime(self) -> CodeSkillRuntime:
        if self.code_runtime is None:
            config = self._config()
            self.code_runtime = CodeSkillRuntime(
                self.base_dir,
                model=self.model or (config.agent.model if config.agent.model != "fake/local" else None),
                env_file=self.base_dir / ".env",
            )
        return self.code_runtime

    def _skill_router(self) -> SkillRouter:
        if self.skill_router is None:
            config = self._config()
            self.skill_router = SkillRouter(
                self.base_dir,
                model=self.model or (config.agent.model if config.agent.model != "fake/local" else None),
                env_file=self.base_dir / ".env",
                code_runtime=self._code_runtime(),
            )
        return self.skill_router

    def _format_code_result(self, result: Any, *, user_message: str = "") -> str:
        zh = _looks_like_chinese(user_message)
        changed = ", ".join(result.changed_files) or "none"
        tests = ", ".join(result.tests_run) or "none"
        artifacts = ", ".join(getattr(result, "run_artifacts", []) or []) or "none"
        summary = result.summary or "Updated the repository."
        if getattr(result, "intent_kind", "") == "sdk_integration":
            status = "finished" if result.ok else "could not finish"
            integration = getattr(result, "integration", {}) or {}
            output_path = integration.get("output_path")
            if zh:
                head = "我把这条请求识别成硬件接入任务，已经完成。" if result.ok else "我把这条请求识别成硬件接入任务，但还没有完成。"
                lines = [head]
            else:
                lines = [f"I treated that as a hardware integration task and {status}: {summary}"]
            if output_path:
                lines.append(f"生成位置: {output_path}" if zh else f"Generated scaffold: {output_path}")
            if changed != "none":
                lines.append(f"改动文件: {changed}." if zh else f"Files touched: {changed}.")
            if tests != "none":
                lines.append(f"验证: {tests}." if zh else f"Validation: {tests}.")
            if not output_path and changed == "none" and tests == "none":
                lines.append(summary)
            return "\n".join(lines)
        if getattr(result, "intent_kind", "") == "code_run":
            status = "succeeded" if result.ok else "failed"
            if zh:
                lines = [
                    "可以。我把这条请求识别成代码执行任务，已经运行了，结果成功。"
                    if result.ok
                    else "可以。我把这条请求识别成代码执行任务并尝试运行了，但这次失败了。"
                ]
            else:
                lines = [f"Yes. I treated that as a code execution task, ran it, and it {status}."]
            if artifacts != "none":
                lines.append(f"产物: {artifacts}." if zh else f"Artifact: {artifacts}.")
            elif tests != "none":
                lines.append(f"命令: {tests}." if zh else f"Command: {tests}.")
            if not result.ok and summary:
                lines.append(summary)
            return "\n".join(lines)
        status = "succeeded" if result.ok else "needs another round"
        if zh:
            lines = [
                "可以。我把这条请求识别成代码任务，已经处理完成。"
                if result.ok
                else "可以。我把这条请求识别成代码任务，但还需要再处理一轮。"
            ]
        else:
            lines = [f"Yes. I treated that as a code task and it {status}."]
        if summary:
            lines.append(summary)
        if changed != "none":
            lines.append(f"改动文件: {changed}." if zh else f"Changed files: {changed}.")
        if tests != "none":
            lines.append(f"检查: {tests}." if zh else f"Checks run: {tests}.")
        if not result.ok and result.test_output.strip():
            label = "关键输出" if zh else "Most relevant output"
            lines.append(f"{label}: {_summarize_text(result.test_output)}")
        return "\n".join(lines)

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


def _summarize_text(text: str, *, limit: int = 220) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "No output."
    priority = ("traceback", "error", "failed", "exception", "__exitcode__")
    for line in reversed(lines):
        lowered = line.lower()
        if any(term in lowered for term in priority):
            return _truncate(line, limit)
    return _truncate(lines[-1], limit)


def _truncate(text: str, limit: int) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "..."


def _looks_like_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _looks_like_code_followup(text: str) -> bool:
    lowered = text.lower().strip()
    if not lowered:
        return False
    followups = (
        "可以",
        "好",
        "好的",
        "帮我实现",
        "实现一下",
        "继续",
        "写吧",
        "做吧",
        "yes",
        "ok",
        "sure",
        "go ahead",
    )
    return any(item in lowered for item in followups)


def _mentions_code_capability(text: str) -> bool:
    lowered = text.lower()
    markers = (
        "代码",
        "脚本",
        "运行",
        "执行",
        "编写",
        "实现",
        "test",
        "tests",
        "code",
        "script",
        "run",
        "execute",
    )
    return any(marker in lowered for marker in markers)


def _max_action_number(action_ids: set[str]) -> int:
    maximum = 0
    for action_id in action_ids:
        if action_id.startswith("act_"):
            try:
                maximum = max(maximum, int(action_id.removeprefix("act_")))
            except ValueError:
                continue
    return maximum
