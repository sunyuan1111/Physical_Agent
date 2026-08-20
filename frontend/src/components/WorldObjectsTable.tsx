import { ApartmentOutlined, CompassOutlined } from "@ant-design/icons";
import { Descriptions, Empty, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { ReactNode } from "react";
import type { AgentState } from "../types";
import { JsonSummaryLine } from "./JsonSummary";
import { FeedbackStatusTag } from "./FeedbackStatusTag";
import {
  asRecord,
  formatObjectValue,
  formatPrimitive,
  isNonEmptyRecord,
  omitKeys,
  pickFirstString
} from "./readableFormatters";

interface WorldObjectsTableProps {
  world: AgentState["world"] | undefined;
}

interface WorldObjectRow {
  key: string;
  id: string;
  type: string;
  location: string;
  pose: string;
  status: string;
  relations: string;
  raw: Record<string, unknown>;
}

const OBJECT_KNOWN_KEYS = [
  "id",
  "type",
  "location",
  "pose",
  "position",
  "status",
  "state",
  "held_by",
  "attached_to",
  "container",
  "availability",
  "held",
  "holding"
];

export function WorldObjectsTable({ world }: WorldObjectsTableProps) {
  const worldRecord = asRecord(world);
  const state = asRecord(worldRecord.state);
  const objects = asRecord(state.objects ?? worldRecord.objects);
  const environment = asRecord(state.environment ?? worldRecord.environment);
  const robots = asRecord(state.robots ?? worldRecord.robots);
  const artifacts = state.artifacts ?? worldRecord.artifacts;
  const raw = asRecord(state.raw ?? worldRecord.raw);
  const rows = objectRows(objects);

  return (
    <Space direction="vertical" size={10} className="full-width world-readable">
      <Typography.Paragraph className="summary-text">
        {formatPrimitive(worldRecord.summary, "No world summary")}
      </Typography.Paragraph>
      {rows.length ? (
        <Table<WorldObjectRow>
          size="small"
          pagination={false}
          dataSource={rows}
          columns={columns}
          scroll={{ x: 940 }}
        />
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No world objects" />
      )}
      <WorldDescriptions
        title="Environment"
        icon={<CompassOutlined />}
        value={environment}
        emptyText="No environment fields"
      />
      <WorldDescriptions
        title="Robots in world"
        icon={<ApartmentOutlined />}
        value={robots}
        emptyText="No robot world fields"
      />
      {Array.isArray(artifacts) && artifacts.length > 0 && (
        <Space size={5} wrap>
          <Typography.Text type="secondary">Artifacts</Typography.Text>
          {artifacts.map((item) => (
            <Tag key={String(item)}>{String(item)}</Tag>
          ))}
        </Space>
      )}
      {isNonEmptyRecord(raw) && <JsonSummaryLine label="Raw" value={raw} />}
    </Space>
  );
}

const columns: ColumnsType<WorldObjectRow> = [
  {
    title: "ID",
    dataIndex: "id",
    width: 150,
    render: (value: string) => <Typography.Text code>{value}</Typography.Text>
  },
  { title: "Type", dataIndex: "type", width: 120 },
  { title: "Location", dataIndex: "location", width: 180 },
  { title: "Pose", dataIndex: "pose", width: 220 },
  {
    title: "Status",
    dataIndex: "status",
    width: 120,
    render: (value: string) => <FeedbackStatusTag status={value === "-" ? "unknown" : value} />
  },
  { title: "Relations", dataIndex: "relations", width: 170 },
  {
    title: "Details",
    dataIndex: "raw",
    width: 220,
    render: (value: Record<string, unknown>) =>
      isNonEmptyRecord(value) ? (
        <JsonSummaryLine label="Raw" value={value} />
      ) : (
        <Typography.Text type="secondary">-</Typography.Text>
      )
  }
];

function objectRows(objects: Record<string, unknown>): WorldObjectRow[] {
  return Object.entries(objects).map(([id, value]) => {
    const record = asRecord(value);
    const locationValue = record.location ?? record.position;
    const status = pickFirstString(record, ["status", "state", "availability"]) || "-";
    const relation = relationText(record);
    return {
      key: id,
      id: formatPrimitive(record.id, id),
      type: formatPrimitive(record.type, "object"),
      location: formatObjectValue(locationValue, "-"),
      pose: formatObjectValue(record.pose, "-"),
      status,
      relations: relation || "-",
      raw: omitKeys(record, OBJECT_KNOWN_KEYS)
    };
  });
}

function relationText(record: Record<string, unknown>): string {
  const relations = [
    ["held_by", record.held_by],
    ["attached_to", record.attached_to],
    ["container", record.container],
    ["availability", record.availability],
    ["holding", record.holding],
    ["held", record.held]
  ]
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([key, value]) => `${key}=${formatObjectValue(value)}`);
  return relations.join(" · ");
}

function WorldDescriptions({
  title,
  icon,
  value,
  emptyText
}: {
  title: string;
  icon: ReactNode;
  value: Record<string, unknown>;
  emptyText: string;
}) {
  const entries = Object.entries(value);
  if (!entries.length) {
    return <Typography.Text type="secondary">{emptyText}</Typography.Text>;
  }
  return (
    <div className="world-section">
      <Space size={6}>
        {icon}
        <Typography.Text strong>{title}</Typography.Text>
      </Space>
      <Descriptions size="small" column={1} className="tight-descriptions">
        {entries.map(([key, item]) => (
          <Descriptions.Item key={key} label={key}>
            {typeof item === "object" && item !== null ? (
              <JsonSummaryLine label={key} value={item} />
            ) : (
              formatObjectValue(item)
            )}
          </Descriptions.Item>
        ))}
      </Descriptions>
    </div>
  );
}
