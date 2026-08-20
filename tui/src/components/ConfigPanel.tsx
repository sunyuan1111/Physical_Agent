import React from "react";
import { Box, Text } from "ink";
import type { AgentState, ConfigResponse } from "../types.js";
import { buildRobotViewModels, summarizeCapabilities } from "../formatters/robot.js";
import { compactJson, recordOrEmpty, summarizeRecord } from "../formatters/schema.js";

interface ConfigPanelProps {
  config: ConfigResponse | null;
  state: AgentState | null;
  error?: string | null;
}

export function ConfigPanel({ config, state, error }: ConfigPanelProps) {
  if (error) {
    return (
      <Box flexDirection="column" paddingX={1}>
        <Text color="red">config unavailable: {error}</Text>
      </Box>
    );
  }
  const effectiveConfig = config?.config;
  if (!effectiveConfig) {
    return (
      <Box flexDirection="column" paddingX={1}>
        <Text color="gray">config</Text>
        <Text color="yellow">Config snapshot not loaded. Use /config or /refresh.</Text>
      </Box>
    );
  }

  const robots = buildRobotViewModels(state, config);
  const extraKeys = Object.keys(effectiveConfig).filter(
    (key) => !["project", "workspace", "watch", "agent", "memory", "robots"].includes(key)
  );

  return (
    <Box flexDirection="column" paddingX={1}>
      <Text color="cyan">config</Text>
      <Text>path: <Text color="gray">{config.config_path ?? "-"}</Text></Text>
      <Text>
        workspace: {String(effectiveConfig.workspace?.path ?? "-")}{" "}
        <Text color="green">backend {String(effectiveConfig.workspace?.backend ?? "-")}</Text>
      </Text>
      <Text>watch: {summarizeRecord(effectiveConfig.watch)}</Text>
      <Text>agent: {summarizeRecord(effectiveConfig.agent)}</Text>
      <Text>memory: {summarizeRecord(effectiveConfig.memory)}</Text>
      {robots.length ? (
        <>
          <Text color="gray">robots</Text>
          {robots.map((robot) => (
            <Box key={robot.id} flexDirection="column" marginLeft={1}>
              <Text>
                {robot.id}: driver {robot.driver}; mode {robot.mode}; endpoint {robot.endpoint}
              </Text>
              <Text color="gray">config {robot.configSummary}</Text>
              <Text color="gray">
                capability schemas: {summarizeCapabilities(robot.capabilities).slice(0, 2).join(" || ") || "not published"}
              </Text>
            </Box>
          ))}
        </>
      ) : (
        <Text color="yellow">No robots configured.</Text>
      )}
      <Text color="gray">
        config schema: {summarizeConfigSchemaFallback(effectiveConfig)}
      </Text>
      {extraKeys.length ? <Text color="gray">extra keys: {extraKeys.join(", ")}</Text> : null}
      <Text color="gray">raw summary: {compactJson(recordOrEmpty(effectiveConfig), 160)}</Text>
    </Box>
  );
}

function summarizeConfigSchemaFallback(config: NonNullable<ConfigResponse["config"]>): string {
  const robots = Object.values(config.robots ?? {});
  const schemaLike = robots
    .map((robot) => recordOrEmpty(robot.config).config_schema)
    .filter(Boolean);
  if (schemaLike.length) {
    return schemaLike.map((schema) => compactJson(schema, 80)).join(" | ");
  }
  return "not exposed by current config API; showing robot config keys and live capability schemas";
}
