import React from "react";
import { Box, Text } from "ink";
import { flattenActions } from "../api/client.js";
import type { AgentState, ActionItem } from "../types.js";

interface ActionsPanelProps {
  state: AgentState | null;
  error?: string | null;
  force?: boolean;
}

export function ActionsPanel({ state, error, force = false }: ActionsPanelProps) {
  const actions = flattenActions(state);
  if (!force && !error && state?.ready && actions.length === 0) {
    return null;
  }
  return (
    <Box flexDirection="column" paddingX={1}>
      <Text color="gray">actions</Text>
      {error ? <Text color="red">API unavailable: {error}</Text> : null}
      {!error && !state?.ready ? <Text color="yellow">{state?.message ?? "Workspace is not ready."}</Text> : null}
      {!error && state?.ready && actions.length === 0 ? <Text color="gray">No actions.</Text> : null}
      {actions.slice(0, 8).map((action) => (
        <ActionRow key={`${action.status}-${action.id}`} action={action} />
      ))}
      {actions.length > 8 ? <Text color="gray">+{actions.length - 8} more</Text> : null}
    </Box>
  );
}

function ActionRow({ action }: { action: ActionItem }) {
  const approval = approvalSummary(action);
  return (
    <Box gap={1} flexWrap="wrap">
      <Text color={statusColor(action.status)}>{statusGlyph(action.status)}</Text>
      <Text>{action.id}</Text>
      <Text>{action.robot}.{action.capability}</Text>
      <Text color={approval.includes("required") ? "yellow" : "green"}>{approval}</Text>
      <Text color="gray">{oneLine(action.reason ?? "")}</Text>
    </Box>
  );
}

function statusGlyph(status: string | undefined): string {
  if (status === "completed") {
    return "done";
  }
  if (status === "cancelled" || status === "failed") {
    return "stop";
  }
  return "wait";
}

function approvalSummary(action: ActionItem): string {
  const approval = action.metadata?.approval as Record<string, unknown> | undefined;
  if (!approval) {
    return "approval unknown";
  }
  if (!approval.required) {
    return "not required";
  }
  const status = String(approval.status ?? "required");
  if (status === "approved") {
    return "approved";
  }
  if (status === "rejected") {
    return "rejected";
  }
  return "approval required";
}

function statusColor(status: string | undefined) {
  if (status === "completed") {
    return "green";
  }
  if (status === "cancelled" || status === "failed") {
    return "red";
  }
  return "yellow";
}

function oneLine(value: string): string {
  return value.replace(/\s+/g, " ").slice(0, 80);
}
