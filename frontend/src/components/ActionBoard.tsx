import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  StopOutlined,
  SafetyCertificateOutlined
} from "@ant-design/icons";
import { Button, Card, Popconfirm, Segmented, Space, Table, Tag, Typography } from "antd";
import { useMemo, useState } from "react";
import { useMessages } from "../locales/context";
import type { ActionItem, AgentState } from "../types";
import { JsonSummaryLine } from "./JsonSummary";
import {
  expectedSummary,
  formatObjectValue
} from "./readableFormatters";

type BoardKey = "pending" | "completed" | "cancelled";

const STATUS_ICON = {
  pending: <ClockCircleOutlined />,
  completed: <CheckCircleOutlined />,
  cancelled: <StopOutlined />
};

const STATUS_COLOR = {
  pending: "gold",
  completed: "green",
  cancelled: "red"
};

interface ActionBoardProps {
  actions: AgentState["actions"] | undefined;
  loading?: boolean;
  onApprove?: (actionId: string) => Promise<void>;
  onReject?: (actionId: string, reason: string) => Promise<void>;
}

export function ActionBoard({
  actions,
  loading = false,
  onApprove,
  onReject
}: ActionBoardProps) {
  const labels = useMessages();
  const [active, setActive] = useState<BoardKey>("pending");
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const rows = actions?.[active] ?? [];
  const data = useMemo(
    () => rows.map((item) => ({ ...item, key: item.id })),
    [rows]
  );

  return (
    <Card
      className="panel action-board"
      data-testid="action-board"
      title={
        <Space>
          <Typography.Text strong>{labels.actions.title}</Typography.Text>
          <Tag icon={STATUS_ICON[active]} color={STATUS_COLOR[active]}>
            {rows.length}
          </Tag>
        </Space>
      }
      extra={
        <Segmented
          size="small"
          value={active}
          options={[
            { label: `${labels.actions.pending} ${actions?.pending?.length ?? 0}`, value: "pending" },
            { label: `${labels.actions.completed} ${actions?.completed?.length ?? 0}`, value: "completed" },
            { label: `${labels.actions.cancelled} ${actions?.cancelled?.length ?? 0}`, value: "cancelled" }
          ]}
          onChange={(value) => setActive(value as BoardKey)}
        />
      }
    >
      <Table<ActionItem & { key: string }>
        size="small"
        pagination={false}
        dataSource={data}
        tableLayout="fixed"
        scroll={{ x: 1520, y: 260 }}
        locale={{ emptyText: labels.actions.noActions.replace("{status}", labels.actions[active]) }}
        columns={[
          {
            title: labels.actions.id,
            dataIndex: "id",
            width: 120,
            render: (value: string) => <Typography.Text code>{value}</Typography.Text>
          },
          {
            title: labels.actions.target,
            key: "target",
            width: 180,
            ellipsis: true,
            render: (_, record) => `${record.robot}.${record.capability}`
          },
          {
            title: labels.actions.params,
            dataIndex: "params",
            width: 300,
            render: (value) => (
              <JsonSummaryLine
                label={labels.actions.params}
                value={value}
                fallback={labels.actions.noParams}
              />
            )
          },
          {
            title: labels.actions.depends,
            dataIndex: "depends_on",
            width: 120,
            ellipsis: true,
            render: (value?: string[]) => value?.join(", ") || "-"
          },
          {
            title: labels.actions.approval,
            key: "approval",
            width: 170,
            render: (_, record) => <ApprovalBadge action={record} labels={labels.actions} />
          },
          {
            title: labels.actions.expected,
            key: "expected",
            width: 260,
            ellipsis: true,
            render: (_, record) => {
              const expected = record.metadata?.expected;
              const summary = expectedSummary(expected);
              if (!summary) {
                return <Typography.Text type="secondary">-</Typography.Text>;
              }
              return (
                <JsonSummaryLine label={labels.actions.expected} text={summary} />
              );
            }
          },
          {
            title: labels.actions.source,
            key: "source",
            width: 180,
            ellipsis: true,
            render: (_, record) => (
              <Typography.Text className="source-cell">
                {sourceText(record)}
              </Typography.Text>
            )
          },
          {
            title: labels.actions.review,
            key: "review",
            width: 190,
            fixed: "right",
            render: (_, record) => {
              if (active !== "pending") {
                return rejectedReason(record);
              }
              return (
                <ActionApprovalControls
                  action={record}
                  loading={loading || busyAction === record.id}
                  disabled={Boolean(busyAction && busyAction !== record.id)}
                  onApprove={
                    onApprove
                      ? async () => {
                          setBusyAction(record.id);
                          try {
                            await onApprove(record.id);
                          } finally {
                            setBusyAction(null);
                          }
                        }
                      : undefined
                  }
                  onReject={
                    onReject
                      ? async () => {
                          setBusyAction(record.id);
                          try {
                            await onReject(record.id, "Rejected from Actions board.");
                          } finally {
                            setBusyAction(null);
                          }
                        }
                      : undefined
                  }
                />
              );
            }
          }
        ]}
      />
    </Card>
  );
}

function ApprovalBadge({
  action,
  labels
}: {
  action: ActionItem;
  labels: ReturnType<typeof useMessages>["actions"];
}) {
  const approval = action.metadata?.approval;
  if (approval?.status === "rejected") {
    return <Tag color="red">{labels.approvalRejected}</Tag>;
  }
  if (approval?.required) {
    if (approval.status === "approved") {
      return <Tag color="green">{labels.executionApproved}</Tag>;
    }
    return <Tag color="gold">{labels.approvalRequired}</Tag>;
  }
  return <Tag>{labels.approvalNotRequired}</Tag>;
}

interface ActionApprovalControlsProps {
  action: ActionItem;
  loading: boolean;
  disabled: boolean;
  onApprove?: () => Promise<void>;
  onReject?: () => Promise<void>;
}

function ActionApprovalControls({
  action,
  loading,
  disabled,
  onApprove,
  onReject
}: ActionApprovalControlsProps) {
  const labels = useMessages().actions;
  const approval = action.metadata?.approval;
  const needsApproval = Boolean(approval?.required && approval.status !== "approved");
  return (
    <Space wrap size={6}>
      {needsApproval && (
        <Button
          size="small"
          type="primary"
          icon={<SafetyCertificateOutlined />}
          loading={loading}
          disabled={disabled || !onApprove}
          onClick={() => void onApprove?.()}
        >
          {labels.approveExecution}
        </Button>
      )}
      <Popconfirm
        title={labels.rejectTitle}
        description={labels.rejectDescription}
        okText={labels.rejectOk}
        cancelText={labels.rejectCancel}
        onConfirm={() => void onReject?.()}
      >
        <Button
          size="small"
          danger
          icon={<StopOutlined />}
          loading={loading}
          disabled={disabled || !onReject}
        >
          {labels.reject}
        </Button>
      </Popconfirm>
    </Space>
  );
}

function sourceText(action: ActionItem): string {
  const metadata = action.metadata;
  if (!metadata) {
    return "-";
  }
  return [
    metadata.source,
    metadata.user_message ?? metadata.original_task
  ].filter(Boolean).join(" · ") || "-";
}

function rejectedReason(action: ActionItem) {
  const reason = action.metadata?.approval?.reason;
  return reason ? <Typography.Text>{reason}</Typography.Text> : <Typography.Text type="secondary">-</Typography.Text>;
}
