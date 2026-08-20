import {
  CheckCircleOutlined,
  CompassOutlined,
  DatabaseOutlined,
  RobotOutlined,
  ToolOutlined
} from "@ant-design/icons";
import { Card, Descriptions, Empty, List, Space, Statistic, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMemo } from "react";
import type { AgentState, HealthState } from "../types";
import type { SystemStatusOverview } from "../viewmodels/overview";
import { formatStateOverview } from "../viewmodels/overview";
import type { CapabilityOverview } from "../viewmodels/capability";
import type { EnvironmentOverview } from "../viewmodels/environment";
import type { RobotOverview } from "../viewmodels/robot";
import type { WorldObjectOverview } from "../viewmodels/world";
import { RawDebug } from "./RawDebug";

interface StateOverviewPanelProps {
  state: AgentState | null;
  health: HealthState | null;
}

export function StateOverviewPanel({ state, health }: StateOverviewPanelProps) {
  const viewModel = useMemo(() => formatStateOverview(state, health), [state, health]);

  return (
    <section className="state-overview-panel" data-testid="state-overview-panel">
      <SystemStatusCard system={viewModel.system} />
      <RobotsTable robots={viewModel.robots} />
      <CapabilityCards capabilities={viewModel.capabilities} />
      <EnvironmentDescriptions environment={viewModel.environment} />
      <WorldObjectsTable objects={viewModel.worldObjects} />
      <RawDebug raw={viewModel.rawDebug} />
    </section>
  );
}

function SystemStatusCard({ system }: { system: SystemStatusOverview }) {
  return (
    <Card
      className="panel system-status-card"
      data-testid="system-status-card"
      title={
        <Space>
          <CheckCircleOutlined />
          <Typography.Text strong>System status</Typography.Text>
        </Space>
      }
    >
      <div className="system-status-grid">
        <Statistic
          title="Ready"
          value={system.readyLabel}
          valueStyle={{ color: system.ready ? "#15803d" : "#b91c1c", fontSize: 24 }}
        />
        <Space direction="vertical" size={4}>
          <Typography.Text type="secondary">Backend</Typography.Text>
          <Tag color="blue">{system.backend}</Tag>
        </Space>
        <Space direction="vertical" size={4}>
          <Typography.Text type="secondary">Workspace</Typography.Text>
          <Typography.Text className="overview-path" code>
            {system.workspace}
          </Typography.Text>
        </Space>
        <Space direction="vertical" size={4}>
          <Typography.Text type="secondary">Message</Typography.Text>
          <Space size={6} wrap>
            <Tag color={system.readyTag.color}>{system.readyTag.label}</Tag>
            <Typography.Text>{system.message}</Typography.Text>
          </Space>
        </Space>
      </div>
    </Card>
  );
}

function RobotsTable({ robots }: { robots: RobotOverview[] }) {
  return (
    <Card
      className="panel"
      title={
        <Space>
          <RobotOutlined />
          <Typography.Text strong>Robots</Typography.Text>
        </Space>
      }
    >
      <div data-testid="robots-table">
        {robots.length ? (
          <Table<RobotOverview>
            size="small"
            pagination={false}
            rowKey="key"
            dataSource={robots}
            columns={robotColumns}
            scroll={{ x: 720 }}
          />
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No robots" />
        )}
      </div>
    </Card>
  );
}

const robotColumns: ColumnsType<RobotOverview> = [
  {
    title: "ID",
    dataIndex: "id",
    width: 150,
    render: (value: string) => <Typography.Text code>{value}</Typography.Text>
  },
  { title: "Driver", dataIndex: "driver", width: 150 },
  { title: "Mode", dataIndex: "mode", width: 130 },
  {
    title: "Health",
    dataIndex: "statusTag",
    width: 130,
    render: (tag: RobotOverview["statusTag"]) => <Tag color={tag.color}>{tag.label}</Tag>
  },
  {
    title: "Capability count",
    dataIndex: "capabilityCount",
    width: 150,
    align: "right"
  }
];

function CapabilityCards({ capabilities }: { capabilities: CapabilityOverview[] }) {
  return (
    <section className="overview-section" data-testid="capability-cards">
      <Space className="overview-section-title" size={6}>
        <ToolOutlined />
        <Typography.Text strong>Capabilities</Typography.Text>
      </Space>
      {capabilities.length ? (
        <List<CapabilityOverview>
          grid={{ gutter: 8, xs: 1, sm: 1, md: 2, lg: 2, xl: 3, xxl: 3 }}
          dataSource={capabilities}
          renderItem={(capability) => (
            <List.Item>
              <Card size="small" className="panel capability-overview-card">
                <Space direction="vertical" size={6} className="full-width">
                  <Space size={6} wrap>
                    <Typography.Text code>{capability.robotId}</Typography.Text>
                    <Typography.Text strong>{capability.name}</Typography.Text>
                    <Tag color={capability.approvalTag.color}>{capability.approvalTag.label}</Tag>
                  </Space>
                  <Typography.Text type="secondary">{capability.description}</Typography.Text>
                  <Typography.Text className="schema-summary">
                    Params: {capability.paramsSummary}
                  </Typography.Text>
                  {capability.constraintsSummary && (
                    <Typography.Text className="schema-summary">
                      Constraints: {capability.constraintsSummary}
                    </Typography.Text>
                  )}
                </Space>
              </Card>
            </List.Item>
          )}
        />
      ) : (
        <Card className="panel">
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No capabilities" />
        </Card>
      )}
    </section>
  );
}

function EnvironmentDescriptions({ environment }: { environment: EnvironmentOverview }) {
  return (
    <Card
      className="panel"
      data-testid="environment-descriptions"
      title={
        <Space>
          <CompassOutlined />
          <Typography.Text strong>Workspace bounds</Typography.Text>
        </Space>
      }
    >
      <Descriptions size="small" column={{ xs: 1, sm: 1, md: 3 }} className="tight-descriptions">
        <Descriptions.Item label="x bounds">{environment.xBounds}</Descriptions.Item>
        <Descriptions.Item label="y bounds">{environment.yBounds}</Descriptions.Item>
        <Descriptions.Item label="z bounds">{environment.zBounds}</Descriptions.Item>
      </Descriptions>
    </Card>
  );
}

function WorldObjectsTable({ objects }: { objects: WorldObjectOverview[] }) {
  return (
    <Card
      className="panel"
      title={
        <Space>
          <DatabaseOutlined />
          <Typography.Text strong>World objects</Typography.Text>
        </Space>
      }
    >
      <div data-testid="world-objects-table">
        {objects.length ? (
          <Table<WorldObjectOverview>
            size="small"
            pagination={false}
            rowKey="key"
            dataSource={objects}
            columns={worldObjectColumns}
            scroll={{ x: 780 }}
          />
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No world objects" />
        )}
      </div>
    </Card>
  );
}

const worldObjectColumns: ColumnsType<WorldObjectOverview> = [
  {
    title: "Object ID",
    dataIndex: "id",
    width: 160,
    render: (value: string) => <Typography.Text code>{value}</Typography.Text>
  },
  { title: "Type", dataIndex: "type", width: 130 },
  { title: "Location", dataIndex: "location", width: 180 },
  { title: "Pose", dataIndex: "pose", width: 220 },
  {
    title: "Status",
    dataIndex: "status",
    width: 130,
    render: (value: string) => {
      const status = value || "unknown";
      const normalized = status.toLowerCase();
      const color = ["ok", "ready", "available", "connected", "idle"].includes(normalized)
        ? "green"
        : ["failed", "error", "blocked", "offline"].includes(normalized)
          ? "red"
          : "default";
      return <Tag color={color}>{status}</Tag>;
    }
  }
];
