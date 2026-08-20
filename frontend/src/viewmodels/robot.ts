import type { AgentState, RobotInfo } from "../types";
import { asRecord, formatPrimitive, readWorldState } from "./world";

export interface StatusTagViewModel {
  label: string;
  color: string;
}

export interface RobotOverview {
  key: string;
  id: string;
  driver: string;
  mode: string;
  health: string;
  statusTag: StatusTagViewModel;
  capabilityCount: number;
}

export const ROBOT_KNOWN_KEYS = [
  "kind",
  "driver",
  "status",
  "mode",
  "health",
  "capabilities"
];

export function formatRobots(state: AgentState | null | undefined): RobotOverview[] {
  const capabilityRobots = state?.capabilities?.robots ?? {};
  const worldRobots = readWorldRobots(state?.world);
  const ids = new Set([...Object.keys(capabilityRobots), ...Object.keys(worldRobots)]);

  return Array.from(ids)
    .sort()
    .map((id) => {
      const robot = capabilityRobots[id] as RobotInfo | undefined;
      const robotRecord = asRecord(robot);
      const worldRobot = asRecord(worldRobots[id]);
      const health = firstString(
        [worldRobot.health, worldRobot.status, worldRobot.state, robotRecord.health, robot?.status],
        "unknown"
      );

      return {
        key: id,
        id,
        driver: firstString([robot?.driver, worldRobot.driver], "-"),
        mode: firstString(
          [robotRecord.mode, worldRobot.mode, worldRobot.transport, robot?.kind],
          "-"
        ),
        health,
        statusTag: statusTag(health),
        capabilityCount: robot?.capabilities?.length ?? 0
      };
    });
}

export function readWorldRobots(world: AgentState["world"] | undefined): Record<string, unknown> {
  const root = asRecord(world);
  const state = readWorldState(world);
  return asRecord(state.robots ?? root.robots);
}

export function statusTag(status: unknown): StatusTagViewModel {
  const label = formatPrimitive(status, "unknown");
  const normalized = label.toLowerCase();
  if (["ok", "ready", "connected", "idle", "completed", "verified"].includes(normalized)) {
    return { label, color: "green" };
  }
  if (["failed", "error", "offline", "halted", "rejected", "violated"].includes(normalized)) {
    return { label, color: "red" };
  }
  if (["pending", "running", "in_progress", "thinking"].includes(normalized)) {
    return { label, color: "gold" };
  }
  return { label, color: normalized && normalized !== "unknown" ? "blue" : "default" };
}

function firstString(values: unknown[], fallback: string): string {
  for (const value of values) {
    const rendered = formatPrimitive(value, "");
    if (rendered) {
      return rendered;
    }
  }
  return fallback;
}
