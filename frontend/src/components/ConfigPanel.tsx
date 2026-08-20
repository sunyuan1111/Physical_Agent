import { FileTextOutlined, ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Descriptions, Empty, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useEffect, useState } from "react";
import { fetchConfig } from "../api";
import { useMessages } from "../locales/context";
import type { ConfigResponse } from "../types";
import { JsonSummaryLine } from "./JsonSummary";

interface ConfigPanelProps {
  refreshToken?: number;
}

interface ConfigRobotRow {
  key: string;
  id: string;
  driver: string;
  config: Record<string, unknown>;
}

export function ConfigPanel({ refreshToken = 0 }: ConfigPanelProps) {
  const labels = useMessages();
  const [response, setResponse] = useState<ConfigResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const next = await fetchConfig();
      setResponse(next);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshToken]);

  const config = response?.config;
  const watch = config?.watch ?? {};
  const robots: ConfigRobotRow[] = Object.entries(config?.robots ?? {}).map(([id, robot]) => ({
    key: id,
    id,
    driver: robot.driver,
    config: robot.config ?? {}
  }));

  const columns: ColumnsType<ConfigRobotRow> = [
    {
      title: labels.config.robot,
      dataIndex: "id",
      width: 140,
      render: (value: string) => <Typography.Text code>{value}</Typography.Text>
    },
    { title: labels.config.driver, dataIndex: "driver", width: 200 },
    {
      title: labels.config.config,
      dataIndex: "config",
      ellipsis: true,
      render: (value: Record<string, unknown>) => (
        <JsonSummaryLine
          label={labels.config.config}
          value={value}
          fallback={labels.config.noConfig}
        />
      )
    }
  ];

  return (
    <Card
      className="panel"
      data-testid="config-panel"
      title={
        <Space>
          <FileTextOutlined />
          <Typography.Text strong>{labels.panels.config}</Typography.Text>
        </Space>
      }
      extra={
        <Button
          size="small"
          icon={<ReloadOutlined />}
          loading={loading}
          onClick={() => void load()}
          data-testid="config-refresh-button"
        >
          {labels.config.refresh}
        </Button>
      }
    >
      {error ? (
        <Alert type="warning" showIcon message="Config unavailable" description={error} />
      ) : (
        <Space direction="vertical" size={8} className="full-width">
          <Descriptions size="small" column={1} className="tight-descriptions">
            <Descriptions.Item label={labels.config.configFile}>
              <Typography.Text code>{response?.config_path ?? "-"}</Typography.Text>
            </Descriptions.Item>
            <Descriptions.Item label={labels.config.workspace}>
              {config?.workspace?.path ?? "-"}{" "}
              <Tag color="blue">{config?.workspace?.backend ?? "-"}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label={labels.config.watch}>
              tick {String(watch.tick_ms ?? "-")}ms · approval{" "}
              {String(watch.require_human_approval ?? "-")} · heartbeat{" "}
              {String(watch.heartbeat_enabled ?? "-")} · halt-on-failure{" "}
              {String(watch.halt_on_heartbeat_failure ?? "-")}
            </Descriptions.Item>
          </Descriptions>
          {robots.length ? (
            <Table
              size="small"
              pagination={false}
              dataSource={robots}
              columns={columns}
              scroll={{ x: 560 }}
            />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={labels.panels.noRobotsConfigured} />
          )}
          <Typography.Text type="secondary">
            This is the effective configuration watch loads at startup. To change existing
            entries, edit physical-agent.yaml and restart watch.
          </Typography.Text>
        </Space>
      )}
    </Card>
  );
}
