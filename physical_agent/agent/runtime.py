from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from physical_agent.agent.llm_planner import LLMPlanner
from physical_agent.agent.planner import Planner
from physical_agent.agent.rule_based import RuleBasedPlanner
from physical_agent.config import DEFAULT_CONFIG_NAME, PhysicalAgentConfig, load_config
from physical_agent.protocol.schemas import Action
from physical_agent.protocol.workspace import Workspace


class AgentRuntime:
    def __init__(
        self,
        config_path: str | Path = DEFAULT_CONFIG_NAME,
        *,
        planner: Planner | None = None,
        planner_name: str | None = None,
        model: str | None = None,
    ):
        self.config_path = Path(config_path).resolve()
        self.base_dir = self.config_path.parent
        self.config: PhysicalAgentConfig | None = None
        self.workspace: Workspace | None = None
        self.planner = planner
        self.planner_name = planner_name
        self.model = model

    async def setup(self) -> None:
        self.config = load_config(self.config_path)
        self.workspace = Workspace(self.config.workspace_path(self.base_dir))
        if not self.workspace.exists():
            self.workspace.initialize()

    async def run_task(self, task: str, *, wait_for_feedback: bool = True) -> dict[str, Any]:
        await self.setup()
        workspace = self._workspace()
        workspace.write_task(task, owner="human")

        capabilities = workspace.read_capabilities()
        world = workspace.read_world()
        if not capabilities.get("robots"):
            message = "No capabilities are available yet. Start `physical-agent watch` first."
            workspace.append_log(message, actor="agent")
            return {"ok": False, "message": message, "actions": []}

        planner = self._resolve_planner()
        actions = planner.plan(task=task, capabilities=capabilities, world=world)
        if not actions:
            message = "No action could be planned for this task."
            workspace.append_log(message, actor="agent")
            return {"ok": False, "message": message, "actions": []}
        actions = self._renumber_actions(actions, workspace)

        workspace.write_actions(actions, [], [])
        workspace.append_log(
            f"`physical-agent run` submitted {len(actions)} action(s): "
            + ", ".join(f"`{action.id}`" for action in actions),
            actor="agent",
        )

        if not wait_for_feedback:
            return {"ok": True, "message": "Actions submitted.", "actions": actions, "feedback": []}

        timeout_s = self._config().agent.feedback_timeout_s
        feedback = await self.wait_for_feedback(actions, timeout_s=timeout_s)
        all_done = all(item.get("status") == "completed" for item in feedback)
        return {
            "ok": all_done,
            "message": "Task completed." if all_done else "Task did not complete successfully.",
            "actions": actions,
            "feedback": feedback,
        }

    async def wait_for_feedback(self, actions: list[Action], *, timeout_s: int) -> list[dict[str, Any]]:
        workspace = self._workspace()
        wanted = {action.id for action in actions}
        deadline = asyncio.get_running_loop().time() + timeout_s
        terminal_statuses = {"completed", "failed", "cancelled"}
        latest_by_id: dict[str, dict[str, Any]] = {}
        while asyncio.get_running_loop().time() < deadline:
            feedback_doc = workspace.read_feedback()
            for item in feedback_doc.get("history", []):
                if item.get("action_id") in wanted and item.get("status") in terminal_statuses:
                    latest_by_id[item["action_id"]] = item
            if wanted.issubset(latest_by_id):
                return [latest_by_id[action.id] for action in actions]
            await asyncio.sleep(0.1)
        return [latest_by_id[action.id] for action in actions if action.id in latest_by_id]

    async def interactive(self) -> None:
        await self.setup()
        print("Physical Agent interactive mode. Press Ctrl+C or submit an empty task to exit.")
        while True:
            task = input("physical-agent> ").strip()
            if not task:
                return
            result = await self.run_task(task)
            print(result["message"])

    def _workspace(self) -> Workspace:
        if self.workspace is None:
            raise RuntimeError("AgentRuntime has not been set up.")
        return self.workspace

    def _config(self) -> PhysicalAgentConfig:
        if self.config is None:
            raise RuntimeError("AgentRuntime has not been set up.")
        return self.config

    def _resolve_planner(self) -> Planner:
        if self.planner is not None:
            return self.planner
        config = self._config()
        planner_name = (self.planner_name or config.agent.planner or "rule_based").lower()
        if planner_name in {"rule_based", "rules", "offline"}:
            self.planner = RuleBasedPlanner()
            return self.planner
        if planner_name in {"llm", "openai", "openai_compatible", "openai-compatible"}:
            model = self.model
            if model is None and config.agent.model != "fake/local":
                model = config.agent.model
            self.planner = LLMPlanner(env_file=str(self.base_dir / ".env"), model=model)
            return self.planner
        raise ValueError(f"Unsupported planner: {planner_name}")

    def _renumber_actions(self, actions: list[Action], workspace: Workspace) -> list[Action]:
        used_ids: set[str] = set()
        for item in workspace.read_feedback().get("history", []):
            action_id = item.get("action_id")
            if action_id:
                used_ids.add(str(action_id))
        action_board = workspace.read_actions()
        for action in action_board["pending"] + action_board["completed"] + action_board["cancelled"]:
            used_ids.add(action.id)

        max_number = 0
        for action_id in used_ids:
            if action_id.startswith("act_"):
                try:
                    max_number = max(max_number, int(action_id.removeprefix("act_")))
                except ValueError:
                    continue
        if max_number == 0:
            return actions

        mapping: dict[str, str] = {}
        renumbered: list[Action] = []
        for index, action in enumerate(actions, start=max_number + 1):
            new_id = f"act_{index:03d}"
            mapping[action.id] = new_id
            renumbered.append(
                action.model_copy(
                    update={
                        "id": new_id,
                        "depends_on": [mapping.get(dep, dep) for dep in action.depends_on],
                    }
                )
            )
        return renumbered
