import type { AgentState, ConfigResponse, RobotCapability } from "../types.js";
import {
  recordOrEmpty,
  summarizeConstraints,
  summarizeEndpoint,
  summarizeMode,
  summarizeRecord,
  summarizeSchema,
  valueAsShortString
} from "./schema.js";

export interface RobotViewModel {
  id: string;
  driver: string;
  kind: string;
  mode: string;
  health: string;
  endpoint: string;
  configSummary: string;
  capabilityCount: number;
  requiresApprovalCount: number;
  robotRequiresApproval: boolean;
  capabilities: RobotCapability[];
}

export function buildRobotViewModels(state: AgentState | null, configResponse: ConfigResponse | null): RobotViewModel[] {
  const capabilityRobots = state?.capabilities?.robots ?? {};
  const configRobots = configResponse?.config?.robots ?? {};
  const worldRobots = recordOrEmpty(recordOrEmpty(state?.world).robots);
  const ids = Array.from(new Set([...Object.keys(configRobots), ...Object.keys(capabilityRobots)])).sort();

  return ids.map((id) => {
    const configRobot = configRobots[id] ?? {};
    const runtimeRobot = capabilityRobots[id] ?? {};
    const robotConfig = recordOrEmpty(configRobot.config);
    const worldInfo = worldRobots[id];
    const capabilities = runtimeRobot.capabilities ?? [];
    const requiresApprovalCount = capabilities.filter((capability) => Boolean(capability.requires_approval)).length;
    return {
      id,
      driver: runtimeRobot.driver ?? configRobot.driver ?? "-",
      kind: runtimeRobot.kind ?? "robot",
      mode: summarizeMode(robotConfig, worldInfo),
      health: firstStatus(runtimeRobot.status, worldInfo),
      endpoint: summarizeEndpoint(robotConfig, worldInfo),
      configSummary: summarizeRecord(robotConfig, "no config"),
      capabilityCount: capabilities.length,
      requiresApprovalCount,
      robotRequiresApproval: Boolean(runtimeRobot.requires_approval),
      capabilities
    };
  });
}

export function summarizeCapabilities(capabilities: RobotCapability[] | undefined): string[] {
  return (capabilities ?? []).map((capability) => {
    const approval = capability.requires_approval ? "approval required" : "auto";
    return [
      capability.name ?? "<unnamed>",
      approval,
      `params ${summarizeSchema(capability.params_schema)}`,
      `constraints ${summarizeConstraints(capability.constraints)}`
    ].join(" | ");
  });
}

function firstStatus(runtimeStatus: unknown, worldInfo: unknown): string {
  const world = recordOrEmpty(worldInfo);
  return (
    valueAsShortString(world.status) ??
    valueAsShortString(world.state) ??
    valueAsShortString(runtimeStatus) ??
    "unknown"
  );
}
