import {
  ApiOutlined,
  CloudSyncOutlined,
  DatabaseOutlined,
  FormOutlined,
  ReloadOutlined,
  SafetyOutlined
} from "@ant-design/icons";
import { Badge, Breadcrumb, Button, Space, Tag, Typography } from "antd";
import type { Messages } from "../locales";
import type { AgentState, HealthState } from "../types";

interface StatusBarProps {
  health: HealthState | null;
  state: AgentState | null;
  sseConnected: boolean;
  watchEnabled: boolean | null;
  loading: boolean;
  activePageLabel: string;
  labels: Messages;
  onRefresh: () => void;
  onOpenInspector: () => void;
}

export function StatusBar({
  health,
  state,
  sseConnected,
  watchEnabled,
  loading,
  activePageLabel,
  labels,
  onRefresh,
  onOpenInspector
}: StatusBarProps) {
  const backend = state?.backend || health?.backend || "-";
  const ready = Boolean(state?.ready ?? health?.ready);

  return (
    <div className="status-bar" data-testid="status-bar">
      <div className="status-title">
        <div>
          <Typography.Title level={1}>{labels.app.name}</Typography.Title>
          <Breadcrumb
            items={[
              { title: labels.app.workbench },
              { title: activePageLabel }
            ]}
          />
        </div>
        <Tag icon={<SafetyOutlined />} color="blue" className="proposal-tag">
          {labels.app.proposalOnly}
        </Tag>
      </div>
      <Space size={8} wrap>
        <Tag icon={<DatabaseOutlined />} color="default">
          {labels.status.backend} {backend}
        </Tag>
        <Tag icon={<ApiOutlined />} color={ready ? "green" : "gold"}>
          {labels.status.workspace} {ready ? labels.status.ready : labels.status.notReady}
        </Tag>
        <Tag icon={<CloudSyncOutlined />} color={watchEnabled ? "cyan" : "default"}>
          {labels.status.watch} {watchEnabled ? labels.status.enabled : labels.status.off}
        </Tag>
        <span data-testid="sse-status">
          <Badge
            status={sseConnected ? "processing" : "warning"}
            text={sseConnected ? labels.status.sseConnected : labels.status.sseDisconnected}
          />
        </span>
        <Button
          className="mobile-inspector-button"
          data-testid="open-proposal-drawer"
          icon={<FormOutlined />}
          size="small"
          onClick={onOpenInspector}
        >
          {labels.app.propose}
        </Button>
        <Button
          icon={<ReloadOutlined />}
          loading={loading}
          onClick={onRefresh}
          size="small"
        >
          {labels.app.refresh}
        </Button>
      </Space>
    </div>
  );
}
