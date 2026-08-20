import { RobotOutlined } from "@ant-design/icons";
import { Card, Empty, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMessages } from "../locales/context";
import type { AgentState } from "../types";

interface RobotRow {
  key: string;
  id: string;
  kind: string;
  driver: string;
  status: string;
  worldStatus: string;
  endpoint: string;
  mode: string;
  capabilities: string[];
}

interface RobotsPanelProps {
  state: AgentState | null;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function firstString(source: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = source[key];
    if (typeof value === "string" && value.trim()) {
      return value;
    }
    if (typeof value === "number") {
      return String(value);
    }
  }
  return "-";
}

export function RobotsPanel({ state }: RobotsPanelProps) {
  const labels = useMessages();
  const worldRobots = asRecord(asRecord(state?.world).robots);

  const rows: RobotRow[] = Object.entries(state?.capabilities?.robots ?? {}).map(
    ([id, robot]) => {
      const worldInfo = asRecord(worldRobots[id]);
      return {
        key: id,
        id,
        kind: robot.kind ?? "robot",
        driver: robot.driver ?? "-",
        status: robot.status ?? "unknown",
        worldStatus: firstString(worldInfo, ["status", "state"]),
        endpoint: firstString(worldInfo, ["endpoint", "url", "port", "serial_port", "address"]),
        mode: firstString(worldInfo, ["mode", "transport"]),
        capabilities:
          robot.capabilities?.map((capability) => capability.name ?? "").filter(Boolean) ?? []
      };
    }
  );

  const columns: ColumnsType<RobotRow> = [
    {
      title: "Robot",
      dataIndex: "id",
      width: 140,
      render: (value: string) => <Typography.Text code>{value}</Typography.Text>
    },
    { title: "Kind", dataIndex: "kind", width: 100 },
    { title: "Driver", dataIndex: "driver", width: 140 },
    {
      title: "Status",
      dataIndex: "status",
      width: 110,
      render: (value: string) => (
        <Tag color={value === "connected" ? "green" : "default"}>{value}</Tag>
      )
    },
    {
      title: "Health",
      dataIndex: "worldStatus",
      width: 110,
      render: (value: string) => {
        const healthy = ["idle", "ok", "connected", "ready"].includes(value.toLowerCase());
        const offline = ["offline", "error", "halted"].includes(value.toLowerCase());
        return (
          <Tag color={healthy ? "green" : offline ? "red" : "default"}>{value}</Tag>
        );
      }
    },
    {
      title: "Endpoint / Port",
      dataIndex: "endpoint",
      width: 170,
      render: (value: string) =>
        value === "-" ? (
          <Typography.Text type="secondary">-</Typography.Text>
        ) : (
          <Typography.Text code>{value}</Typography.Text>
        )
    },
    { title: "Mode", dataIndex: "mode", width: 100 },
    {
      title: "Capabilities",
      dataIndex: "capabilities",
      render: (items: string[]) => (
        <Space size={5} wrap>
          {items.length ? items.map((item) => <Tag key={item}>{item}</Tag>) : "-"}
        </Space>
      )
    }
  ];

  return (
    <Card
      className="panel"
      data-testid="robots-panel"
      title={
        <Space>
          <RobotOutlined />
          <Typography.Text strong>{labels.panels.robots}</Typography.Text>
        </Space>
      }
    >
      {rows.length ? (
        <Table
          size="small"
          pagination={false}
          dataSource={rows}
          columns={columns}
          scroll={{ x: 880 }}
        />
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={labels.panels.noRobots} />
      )}
    </Card>
  );
}
