import React from "react";
import { Box, Text } from "ink";
import type { AgentState, ConfigResponse } from "../types.js";
import { buildRobotViewModels } from "../formatters/robot.js";
import { summarizeConstraints, summarizeSchema } from "../formatters/schema.js";

interface RobotDetailPanelProps {
  state: AgentState | null;
  config: ConfigResponse | null;
  robotId: string | null;
  mode: "detail" | "capabilities";
}

export function RobotDetailPanel({ state, config, robotId, mode }: RobotDetailPanelProps) {
  const robots = buildRobotViewModels(state, config);
  const robot = robots.find((item) => item.id === robotId);
  if (!robotId) {
    return (
      <Box flexDirection="column" paddingX={1}>
        <Text color="yellow">Select a robot with /robot &lt;robot_id&gt; or /capabilities &lt;robot_id&gt;.</Text>
      </Box>
    );
  }
  if (!robot) {
    return (
      <Box flexDirection="column" paddingX={1}>
        <Text color="yellow">Robot not found: {robotId}</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" paddingX={1}>
      <Text color="cyan">{mode === "capabilities" ? "capabilities" : "robot"} {robot.id}</Text>
      {mode === "detail" ? (
        <>
          <Text>driver: {robot.driver}</Text>
          <Text>kind: {robot.kind}</Text>
          <Text>mode: {robot.mode}</Text>
          <Text>health: {robot.health}</Text>
          <Text>endpoint: {robot.endpoint}</Text>
          <Text>config: {robot.configSummary}</Text>
        </>
      ) : null}
      {robot.capabilities.length ? (
        robot.capabilities.map((capability) => (
          <Box key={capability.name ?? JSON.stringify(capability)} flexDirection="column" marginLeft={1} marginBottom={1}>
            <Text>
              {capability.name ?? "<unnamed>"}{" "}
              <Text color={capability.requires_approval ? "yellow" : "green"}>
                {capability.requires_approval ? "requires_approval" : "auto"}
              </Text>
            </Text>
            {capability.description ? <Text color="gray">{capability.description}</Text> : null}
            <Text color="gray">params_schema: {summarizeSchema(capability.params_schema)}</Text>
            <Text color="gray">constraints: {summarizeConstraints(capability.constraints)}</Text>
          </Box>
        ))
      ) : (
        <Text color="yellow">No capabilities published for this robot. Restart watch if it was just registered.</Text>
      )}
    </Box>
  );
}
