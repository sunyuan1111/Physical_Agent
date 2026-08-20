import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ExclamationCircleOutlined,
  FieldTimeOutlined,
  SafetyCertificateOutlined,
  WarningOutlined
} from "@ant-design/icons";
import { Button, Empty, Space, Timeline, Tag, Typography } from "antd";
import type { ActionItem, AgentState, ChatMessage } from "../types";
import { JsonSummaryLine } from "./JsonSummary";
import { FeedbackStatusTag } from "./FeedbackStatusTag";
import {
  allActions,
  asRecord,
  formatObjectValue,
  formatPrimitive,
  isNonEmptyRecord,
  omitKeys,
  readableDate,
  statusColor,
  statusText
} from "./readableFormatters";

interface FeedbackTimelineProps {
  feedback: AgentState["feedback"] | undefined;
  actions: AgentState["actions"] | undefined;
  chat: AgentState["chat"] | undefined;
  onOpenAction?: (actionId: string) => void;
}

interface TimelineEntry {
  key: string;
  status: string;
  title: string;
  message: string;
  time?: string;
  actionId?: string;
  robot?: string;
  capability?: string;
  source?: string;
  event?: string;
  raw: Record<string, unknown>;
}

const FEEDBACK_KNOWN_KEYS = [
  "action_id",
  "status",
  "robot",
  "robot_id",
  "capability",
  "message",
  "result",
  "artifacts",
  "event",
  "failure_count",
  "threshold",
  "halt_status"
];

export function FeedbackTimeline({
  feedback,
  actions,
  chat,
  onOpenAction
}: FeedbackTimelineProps) {
  const actionIndex = new Map(allActions(actions).map((action) => [action.id, action]));
  const entries = [
    ...feedbackEntries(feedback, actionIndex),
    ...approvalEntries(actions),
    ...refusalEntries(chat)
  ].slice(-30);

  if (!entries.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No feedback" />;
  }

  return (
    <Timeline
      className="feedback-timeline"
      items={entries.reverse().map((entry) => ({
        key: entry.key,
        color: timelineColor(entry.status),
        dot: timelineIcon(entry.status, entry.event),
        children: (
          <FeedbackTimelineItem entry={entry} onOpenAction={onOpenAction} />
        )
      }))}
    />
  );
}

function FeedbackTimelineItem({
  entry,
  onOpenAction
}: {
  entry: TimelineEntry;
  onOpenAction?: (actionId: string) => void;
}) {
  return (
    <Space direction="vertical" size={4} className="full-width feedback-timeline-item">
      <Space size={6} wrap>
        <Typography.Text strong>{entry.title}</Typography.Text>
        <FeedbackStatusTag status={entry.status} />
        {entry.event && <Tag>{entry.event}</Tag>}
        {entry.time && <Typography.Text type="secondary">{entry.time}</Typography.Text>}
      </Space>
      <Typography.Text>{entry.message}</Typography.Text>
      <Space size={6} wrap>
        {entry.actionId && (
          <Button
            size="small"
            type="link"
            className="action-link-button"
            onClick={() => onOpenAction?.(entry.actionId ?? "")}
          >
            action {entry.actionId}
          </Button>
        )}
        {entry.robot && <Tag>{entry.robot}</Tag>}
        {entry.capability && <Tag>{entry.capability}</Tag>}
        {entry.source && <Tag color="blue">source {entry.source}</Tag>}
      </Space>
      {isNonEmptyRecord(entry.raw) && <JsonSummaryLine label="Raw" value={entry.raw} />}
    </Space>
  );
}

function feedbackEntries(
  feedback: AgentState["feedback"] | undefined,
  actionIndex: Map<string, ActionItem>
): TimelineEntry[] {
  const latest = asRecord(feedback?.latest);
  const history = Array.isArray(feedback?.history) ? feedback.history : [];
  const source = history.length ? history : isNonEmptyRecord(latest) ? [latest] : [];
  return source.map((item, index) => feedbackEntry(item, index, actionIndex));
}

function feedbackEntry(
  item: unknown,
  index: number,
  actionIndex: Map<string, ActionItem>
): TimelineEntry {
  const record = asRecord(item);
  const actionId = formatOptional(record.action_id);
  const action = actionId ? actionIndex.get(actionId) : undefined;
  const metadata = asRecord(action?.metadata);
  const event = formatOptional(record.event);
  const status = statusText(record.status);
  const message = formatPrimitive(record.message, fallbackMessage(record));
  const result = asRecord(record.result);
  const raw = {
    ...omitKeys(record, FEEDBACK_KNOWN_KEYS),
    ...(isNonEmptyRecord(result) ? { result } : {}),
    ...(Array.isArray(record.artifacts) && record.artifacts.length ? { artifacts: record.artifacts } : {}),
    ...(isNonEmptyRecord(metadata) ? { action_metadata: metadata } : {})
  };
  return {
    key: `feedback-${index}-${actionId || event || status}`,
    status,
    title: feedbackTitle(record, action, event),
    message,
    actionId,
    robot: formatOptional(record.robot ?? record.robot_id),
    capability: formatOptional(record.capability),
    source: formatOptional(metadata.source),
    event,
    raw
  };
}

function approvalEntries(actions: AgentState["actions"] | undefined): TimelineEntry[] {
  return allActions(actions).flatMap((action): TimelineEntry[] => {
      const approval = asRecord(action.metadata?.approval);
      if (!isNonEmptyRecord(approval) && !action.metadata?.source) {
        return [];
      }
      const required = Boolean(approval.required);
      const status = statusText(approval.status, required ? "pending" : "not_required");
      const title =
        status === "approved"
          ? "Execution approved"
          : status === "rejected"
            ? "Execution rejected"
            : required
              ? "Execution approval required"
              : "Action proposed";
      const reason = formatOptional(approval.reason);
      const source = formatOptional(action.metadata?.source);
      const userMessage = formatOptional(action.metadata?.user_message ?? action.metadata?.original_task);
      return [{
        key: `approval-${action.id}-${status}`,
        status,
        title,
        message:
          reason ||
          userMessage ||
          action.reason ||
          `${action.robot}.${action.capability} is in the action board.`,
        time: readableDate(approval.at ?? approval.approved_at ?? approval.rejected_at),
        actionId: action.id,
        robot: action.robot,
        capability: action.capability,
        source,
        event: "approval",
        raw: {
          approval,
          metadata: omitKeys(asRecord(action.metadata), ["approval"])
        }
      }];
    });
}

function refusalEntries(chat: AgentState["chat"] | undefined): TimelineEntry[] {
  return (chat?.messages ?? [])
    .map((message, index) => refusalEntry(message, index))
    .filter((entry): entry is TimelineEntry => entry !== null);
}

function refusalEntry(message: ChatMessage, index: number): TimelineEntry | null {
  const refusalReason = formatOptional(message.metadata?.refusal_reason);
  if (!refusalReason) {
    return null;
  }
  return {
    key: `refusal-${message.created_at ?? index}`,
    status: "skipped",
    title: "No action drafted",
    message: refusalReason,
    time: readableDate(message.created_at),
    event: "refusal_reason",
    source: "chat",
    raw: {
      role: message.role,
      metadata: message.metadata ?? {}
    }
  };
}

function feedbackTitle(record: Record<string, unknown>, action: ActionItem | undefined, event: string): string {
  if (event) {
    return eventTitle(event);
  }
  const capability = formatOptional(record.capability ?? action?.capability);
  const robot = formatOptional(record.robot ?? record.robot_id ?? action?.robot);
  if (capability && robot) {
    return `${capability} on ${robot}`;
  }
  if (formatOptional(record.action_id)) {
    return "Action feedback";
  }
  return "Feedback";
}

function eventTitle(event: string): string {
  if (event === "driver_heartbeat") {
    return "Driver heartbeat failed";
  }
  if (event === "driver_heartbeat_recovered") {
    return "Driver heartbeat recovered";
  }
  if (event === "driver_watchdog_halt") {
    return "Heartbeat watchdog halt";
  }
  if (event === "driver_halt") {
    return "Driver halt failed";
  }
  if (event === "expectation_check") {
    return "Expectation check";
  }
  return event.replace(/^driver_/, "Driver ").replace(/_/g, " ");
}

function fallbackMessage(record: Record<string, unknown>): string {
  const event = formatOptional(record.event);
  const result = asRecord(record.result);
  if (formatOptional(result.error_message)) {
    return formatObjectValue(result.error_message);
  }
  if (event) {
    return eventTitle(event);
  }
  return "No message";
}

function formatOptional(value: unknown): string {
  const text = formatPrimitive(value, "");
  return text === "-" ? "" : text;
}

function timelineColor(status: string): string {
  const color = statusColor(status);
  if (color === "green" || color === "red" || color === "blue" || color === "gold") {
    return color;
  }
  return "gray";
}

function timelineIcon(status: string, event?: string) {
  const normalized = statusText(status);
  if (event === "approval") {
    return <SafetyCertificateOutlined />;
  }
  if (normalized === "completed" || normalized === "approved" || normalized === "verified") {
    return <CheckCircleOutlined />;
  }
  if (normalized === "failed" || normalized === "rejected" || normalized === "cancelled") {
    return <CloseCircleOutlined />;
  }
  if (normalized === "violated" || normalized === "error") {
    return <WarningOutlined />;
  }
  if (normalized === "skipped") {
    return <ExclamationCircleOutlined />;
  }
  return <FieldTimeOutlined />;
}
