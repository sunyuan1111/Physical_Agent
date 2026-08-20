import type { AgentState } from "../types";
import { asRecord, formatObjectValue, omitKeys, readWorldState } from "./world";

export interface EnvironmentOverview {
  xBounds: string;
  yBounds: string;
  zBounds: string;
  raw: Record<string, unknown>;
}

export const ENVIRONMENT_KNOWN_KEYS = [
  "bounds",
  "x_bounds",
  "y_bounds",
  "z_bounds",
  "x_min",
  "x_max",
  "y_min",
  "y_max",
  "z_min",
  "z_max",
  "min_x",
  "max_x",
  "min_y",
  "max_y",
  "min_z",
  "max_z"
];

export function formatEnvironment(world: AgentState["world"] | undefined): EnvironmentOverview {
  const root = asRecord(world);
  const state = readWorldState(world);
  const environment = asRecord(state.environment ?? root.environment);

  return {
    xBounds: axisBounds("x", environment),
    yBounds: axisBounds("y", environment),
    zBounds: axisBounds("z", environment),
    raw: omitKeys(environment, ENVIRONMENT_KNOWN_KEYS)
  };
}

export function readEnvironment(world: AgentState["world"] | undefined): Record<string, unknown> {
  const root = asRecord(world);
  const state = readWorldState(world);
  return asRecord(state.environment ?? root.environment);
}

function axisBounds(axis: "x" | "y" | "z", environment: Record<string, unknown>): string {
  const bounds = asRecord(environment.bounds);
  const direct = environment[`${axis}_bounds`] ?? bounds[axis] ?? bounds[`${axis}_bounds`];
  const directText = boundsValueText(direct);
  if (directText) {
    return directText;
  }

  const min =
    environment[`${axis}_min`] ??
    environment[`min_${axis}`] ??
    bounds[`${axis}_min`] ??
    bounds[`min_${axis}`];
  const max =
    environment[`${axis}_max`] ??
    environment[`max_${axis}`] ??
    bounds[`${axis}_max`] ??
    bounds[`max_${axis}`];
  if (min !== undefined || max !== undefined) {
    return `${formatObjectValue(min, "?")} to ${formatObjectValue(max, "?")}`;
  }
  return "-";
}

function boundsValueText(value: unknown): string {
  if (Array.isArray(value) && value.length >= 2) {
    return `${formatObjectValue(value[0], "?")} to ${formatObjectValue(value[1], "?")}`;
  }
  const record = asRecord(value);
  const min = record.min ?? record.lower ?? record.from;
  const max = record.max ?? record.upper ?? record.to;
  if (min !== undefined || max !== undefined) {
    return `${formatObjectValue(min, "?")} to ${formatObjectValue(max, "?")}`;
  }
  return "";
}
