import type { AgentState } from "../types";
import { asRecord, formatObjectValue, formatPrimitive, omitKeys } from "./world";
import type { StatusTagViewModel } from "./robot";

export interface CapabilityOverview {
  key: string;
  robotId: string;
  name: string;
  description: string;
  paramsSummary: string;
  requiresApproval: boolean;
  approvalTag: StatusTagViewModel;
  constraintsSummary: string;
  raw: Record<string, unknown>;
}

export const CAPABILITY_KNOWN_KEYS = [
  "name",
  "description",
  "params_schema",
  "requires_approval",
  "constraints"
];

export function formatCapabilities(
  capabilities: AgentState["capabilities"] | undefined
): CapabilityOverview[] {
  const robots = capabilities?.robots ?? {};
  return Object.entries(robots).flatMap(([robotId, robot]) =>
    (robot.capabilities ?? []).map((capability, index) => {
      const record = asRecord(capability);
      const name = formatPrimitive(capability.name, `capability_${index + 1}`);
      const requiresApproval = Boolean(capability.requires_approval);
      return {
        key: `${robotId}:${name}:${index}`,
        robotId,
        name,
        description: formatPrimitive(capability.description, "No description"),
        paramsSummary: compactSchemaSummary(capability.params_schema),
        requiresApproval,
        approvalTag: requiresApproval
          ? { label: "approval required", color: "gold" }
          : { label: "no approval", color: "default" },
        constraintsSummary: formatObjectValue(record.constraints, ""),
        raw: omitKeys(record, CAPABILITY_KNOWN_KEYS)
      };
    })
  );
}

function compactSchemaSummary(schema: unknown): string {
  const record = asRecord(schema);
  const properties = asRecord(record.properties);
  const required = asStringArray(record.required);
  const propertyNames = Object.keys(properties);
  if (!propertyNames.length) {
    const type = formatPrimitive(record.type, "");
    return type ? `type: ${type}` : "No params";
  }

  return propertyNames
    .slice(0, 6)
    .map((name) => {
      const property = asRecord(properties[name]);
      const type = formatPrimitive(property.type, "value");
      return `${name}${required.includes(name) ? "*" : ""}: ${type}`;
    })
    .join(" · ");
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}
