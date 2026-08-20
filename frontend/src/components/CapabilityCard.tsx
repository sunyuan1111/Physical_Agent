import { SafetyCertificateOutlined, ToolOutlined } from "@ant-design/icons";
import { Card, Empty, Space, Tag, Typography } from "antd";
import type { AgentState, RobotInfo } from "../types";
import { JsonSummaryLine } from "./JsonSummary";
import {
  asRecord,
  compactSchemaSummary,
  formatObjectValue,
  isNonEmptyRecord,
  omitKeys
} from "./readableFormatters";

interface CapabilitiesGridProps {
  capabilities: AgentState["capabilities"] | undefined;
}

const CAPABILITY_KNOWN_KEYS = [
  "name",
  "description",
  "params_schema",
  "requires_approval",
  "constraints"
];

export function CapabilitiesGrid({ capabilities }: CapabilitiesGridProps) {
  const robots = capabilities?.robots ?? {};
  const entries = Object.entries(robots);
  if (!entries.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No capabilities" />;
  }
  return (
    <div className="capability-grid">
      {entries.map(([robotId, robot]) => (
        <RobotCapabilityGroup key={robotId} robotId={robotId} robot={robot} />
      ))}
      {unknownCapabilities(capabilities).length > 0 && (
        <JsonSummaryLine
          label="Raw"
          value={Object.fromEntries(unknownCapabilities(capabilities))}
        />
      )}
    </div>
  );
}

function RobotCapabilityGroup({ robotId, robot }: { robotId: string; robot: RobotInfo }) {
  return (
    <Space direction="vertical" size={8} className="full-width">
      <Space size={6} wrap>
        <Typography.Text code>{robotId}</Typography.Text>
        <Tag>{robot.kind ?? "robot"}</Tag>
        <Tag>{robot.driver ?? "driver unknown"}</Tag>
        <Tag color={robot.status === "connected" ? "green" : "default"}>
          {robot.status ?? "unknown"}
        </Tag>
      </Space>
      <div className="capability-card-list">
        {(robot.capabilities ?? []).map((capability) => {
          const rawFields = omitKeys(asRecord(capability), CAPABILITY_KNOWN_KEYS);
          return (
            <Card
              key={`${robotId}-${capability.name ?? "capability"}`}
              size="small"
              className="capability-card"
            >
              <Space direction="vertical" size={6} className="full-width">
                <Space size={6} wrap>
                  <ToolOutlined />
                  <Typography.Text strong>{capability.name ?? "Unnamed capability"}</Typography.Text>
                  {capability.requires_approval ? (
                    <Tag color="gold" icon={<SafetyCertificateOutlined />}>
                      approval required
                    </Tag>
                  ) : (
                    <Tag>no approval</Tag>
                  )}
                </Space>
                <Typography.Text type="secondary">
                  {capability.description || "No description"}
                </Typography.Text>
                <JsonSummaryLine
                  label="Params"
                  text={compactSchemaSummary(capability.params_schema)}
                />
                {isNonEmptyRecord(asRecord(capability).constraints) && (
                  <JsonSummaryLine
                    label="Constraints"
                    text={formatObjectValue(asRecord(capability).constraints)}
                  />
                )}
                {isNonEmptyRecord(rawFields) && (
                  <JsonSummaryLine label="Raw" value={rawFields} />
                )}
              </Space>
            </Card>
          );
        })}
      </div>
    </Space>
  );
}

function unknownCapabilities(capabilities: AgentState["capabilities"] | undefined) {
  return Object.entries(capabilities ?? {}).filter(([key]) => key !== "robots");
}
