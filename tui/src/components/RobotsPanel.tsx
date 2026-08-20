import React from "react";
import { Box, Text } from "ink";
import type { AgentState, ConfigResponse } from "../types.js";
import { buildRobotViewModels } from "../formatters/robot.js";

interface RobotsPanelProps {
  state: AgentState | null;
  config: ConfigResponse | null;
  selectedRobotId?: string | null;
  error?: string | null;
}

export function RobotsPanel({ state, config, selectedRobotId, error }: RobotsPanelProps) {
  if (error) {
    return (
      <Box flexDirection="column" paddingX={1}>
        <Text color="red">robots unavailable: {error}</Text>
      </Box>
    );
  }
  const rows = buildRobotViewModels(state, config);
  const visibleRows = selectedRobotId ? rows.filter((row) => row.id === selectedRobotId) : rows;

  return (
    <Box flexDirection="column" paddingX={1}>
      <Text color="cyan">robots</Text>
      {selectedRobotId && visibleRows.length === 0 ? (
        <Text color="yellow">Robot not found: {selectedRobotId}</Text>
      ) : null}
      {visibleRows.length ? (
        visibleRows.map((robot) => (
          <Box key={robot.id} flexDirection="column" marginBottom={1}>
            <Box gap={1} flexWrap="wrap">
              <Text color="green">{robot.id}</Text>
              <Text>{robot.driver}</Text>
              <Text>mode {robot.mode}</Text>
              <Text color={healthColor(robot.health)}>health {robot.health}</Text>
              <Text>endpoint {robot.endpoint}</Text>
            </Box>
            <Text color="gray">
              capabilities {robot.capabilityCount}; approval capabilities {robot.requiresApprovalCount}
              {robot.robotRequiresApproval ? "; robot approval flag true" : ""}
            </Text>
            <Text color="gray">config {robot.configSummary}</Text>
          </Box>
        ))
      ) : (
        <Text color="yellow">No robots configured or published.</Text>
      )}
    </Box>
  );
}

function healthColor(value: string): "green" | "red" | "yellow" | "gray" {
  const normalized = value.toLowerCase();
  if (["idle", "ok", "connected", "ready", "healthy"].includes(normalized)) {
    return "green";
  }
  if (["offline", "error", "halted", "failed", "disconnected"].includes(normalized)) {
    return "red";
  }
  if (normalized === "unknown" || normalized === "-") {
    return "yellow";
  }
  return "gray";
}
