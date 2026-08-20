import { ThunderboltOutlined } from "@ant-design/icons";
import { Card, Empty, List, Space, Tag, Typography } from "antd";
import type { ApiEvent } from "../types";
import { JsonSummaryLine } from "./JsonSummary";
import { FeedbackStatusTag } from "./FeedbackStatusTag";
import { asRecord, formatObjectValue, formatPrimitive, readableDate } from "./readableFormatters";

interface EventsPanelProps {
  events: ApiEvent[];
}

export function EventsPanel({ events }: EventsPanelProps) {
  return (
    <Card
      className="panel events-panel"
      data-testid="events-panel"
      title={
        <Space>
          <ThunderboltOutlined />
          <Typography.Text strong>Events</Typography.Text>
        </Space>
      }
    >
      {events.length ? (
        <List
          size="small"
          dataSource={events}
          renderItem={(event) => (
            <List.Item className="event-row">
              <ReadableApiEvent event={event} />
            </List.Item>
          )}
        />
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No events" />
      )}
    </Card>
  );
}

function ReadableApiEvent({ event }: { event: ApiEvent }) {
  const payload = asRecord(event.payload);
  const state = asRecord(payload.state);
  const latestFeedback = asRecord(asRecord(state.feedback).latest);
  const status = event.type === "error" ? "error" : latestFeedback.status ?? payload.status ?? "ok";
  return (
    <Space direction="vertical" size={4} className="full-width">
      <Space size={6} wrap>
        <Tag color={event.type === "error" ? "red" : "blue"}>{event.type}</Tag>
        <FeedbackStatusTag status={status} />
        <Typography.Text type="secondary">#{event.id}</Typography.Text>
        <Typography.Text type="secondary">{readableDate(event.ts) || event.ts}</Typography.Text>
      </Space>
      <Typography.Text>{eventMessage(event, payload, latestFeedback)}</Typography.Text>
      <Space size={6} wrap>
        {payload.reason !== undefined && <Tag>{`reason ${formatObjectValue(payload.reason)}`}</Tag>}
        {payload.phase !== undefined && <Tag>{`phase ${formatObjectValue(payload.phase)}`}</Tag>}
        {payload.executed !== undefined && <Tag>{`executed ${formatObjectValue(payload.executed)}`}</Tag>}
        {latestFeedback.action_id !== undefined && (
          <Tag>{`action ${formatObjectValue(latestFeedback.action_id)}`}</Tag>
        )}
      </Space>
      <JsonSummaryLine label="Payload" value={event.payload} />
    </Space>
  );
}

function eventMessage(
  event: ApiEvent,
  payload: Record<string, unknown>,
  latestFeedback: Record<string, unknown>
): string {
  if (event.type === "error") {
    return formatPrimitive(payload.message, "API event error");
  }
  if (event.type === "hello") {
    return `API stream connected; watch ${payload.watch_enabled ? "enabled" : "disabled"}.`;
  }
  if (event.type === "watch_step") {
    const executed = formatObjectValue(payload.executed, "0");
    const message = formatPrimitive(latestFeedback.message, "");
    return message || `Watch step completed; executed ${executed} action(s).`;
  }
  if (event.type === "state") {
    return `State snapshot refreshed${payload.reason ? `: ${formatObjectValue(payload.reason)}` : "."}`;
  }
  return formatPrimitive(payload.message, `${event.type} event`);
}
