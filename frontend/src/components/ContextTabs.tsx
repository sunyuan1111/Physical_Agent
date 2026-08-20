import {
  AlertOutlined,
  CompassOutlined,
  SafetyCertificateOutlined,
  ToolOutlined
} from "@ant-design/icons";
import { Descriptions, Empty, Space, Tabs, Tag, Typography } from "antd";
import type { TabsProps } from "antd";
import { useMessages } from "../locales/context";
import type { AgentState } from "../types";
import { CapabilitiesGrid } from "./CapabilityCard";
import { FeedbackTimeline } from "./FeedbackTimeline";
import { JsonSummaryLine } from "./JsonSummary";
import { WorldObjectsTable } from "./WorldObjectsTable";
import { FeedbackStatusTag } from "./FeedbackStatusTag";
import { asRecord, formatObjectValue, isNonEmptyRecord, statusText } from "./readableFormatters";

interface ContextTabsProps {
  state: AgentState | null;
  defaultActiveKey?: "world" | "feedback" | "safety" | "capabilities";
  onOpenAction?: (actionId: string) => void;
}

export function ContextTabs({
  state,
  defaultActiveKey = "world",
  onOpenAction
}: ContextTabsProps) {
  const labels = useMessages();
  const items: TabsProps["items"] = [
    {
      key: "world",
      label: (
        <Space size={6}>
          <CompassOutlined />
          {labels.panels.world}
        </Space>
      ),
      children: <WorldObjectsTable world={state?.world} />
    },
    {
      key: "feedback",
      label: (
        <Space size={6}>
          <AlertOutlined />
          {labels.panels.feedback}
        </Space>
      ),
      children: (
        <FeedbackTimeline
          feedback={state?.feedback}
          actions={state?.actions}
          chat={state?.chat}
          onOpenAction={onOpenAction}
        />
      )
    },
    {
      key: "safety",
      label: (
        <Space size={6}>
          <SafetyCertificateOutlined />
          {labels.panels.safety}
        </Space>
      ),
      children: <SafetyView safety={state?.safety} />
    },
    {
      key: "capabilities",
      label: (
        <Space size={6}>
          <ToolOutlined />
          {labels.panels.capabilities}
        </Space>
      ),
      children: <CapabilitiesGrid capabilities={state?.capabilities} />
    }
  ];

  return (
    <div className="panel context-tabs" data-testid="context-tabs">
      <Tabs defaultActiveKey={defaultActiveKey} items={items} />
    </div>
  );
}

function SafetyView({ safety }: { safety: AgentState["safety"] | undefined }) {
  const labels = useMessages();
  const rules = asRecord(asRecord(safety).rules ?? safety);
  const entries = Object.entries(rules).filter(([key]) => key !== "metadata");
  if (!entries.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={labels.panels.noSafetyRules} />;
  }
  return (
    <Space direction="vertical" size={8} className="full-width">
      <Descriptions size="small" column={1} className="tight-descriptions">
        {entries.map(([key, value]) => (
          <Descriptions.Item key={key} label={key}>
            {typeof value === "boolean" ? (
              <FeedbackStatusTag status={value ? "ok" : "disabled"} />
            ) : key.toLowerCase().includes("backend") ? (
              <Tag>{statusText(value)}</Tag>
            ) : (
              <Typography.Text>{formatObjectValue(value)}</Typography.Text>
            )}
          </Descriptions.Item>
        ))}
      </Descriptions>
      {isNonEmptyRecord(asRecord(safety)) && (
        <JsonSummaryLine label="Raw" value={safety ?? {}} />
      )}
    </Space>
  );
}
