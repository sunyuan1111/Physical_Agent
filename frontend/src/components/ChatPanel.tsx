import {
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  RobotOutlined,
  StopOutlined,
  UserOutlined
} from "@ant-design/icons";
import { Bubble, Sender } from "@ant-design/x";
import { Alert, Button, Card, Descriptions, Empty, Popconfirm, Space, Tag, Typography } from "antd";
import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import { parseActionDrafts } from "../actionDraft";
import { useMessages } from "../locales/context";
import type { ActionItem, ChatMessage } from "../types";
import { JsonSummaryLine } from "./JsonSummary";
import { expectedSummary } from "./readableFormatters";

interface ChatPanelProps {
  messages: ChatMessage[];
  loading: boolean;
  error?: string | null;
  onSend: (message: string) => Promise<void>;
  onStop: () => void;
  onReset: () => Promise<void>;
  onAddDraft: (action: ActionItem) => Promise<void>;
  onEditDraft: (action: ActionItem) => void;
  actionLoading?: boolean;
}

export function ChatPanel({
  messages,
  loading,
  error,
  onSend,
  onStop,
  onReset,
  onAddDraft,
  onEditDraft,
  actionLoading = false
}: ChatPanelProps) {
  const labels = useMessages();
  const [draft, setDraft] = useState("");
  const [submittingDraft, setSubmittingDraft] = useState<string | null>(null);
  const items = useMemo(
    () =>
      messages.map((message, index) => {
        const originalMessage = findPreviousUserMessage(messages, index);
        return {
          key: `${message.role}-${message.created_at ?? index}`,
          role: message.role === "user" ? "user" : "assistant",
          content: (
            <MessageContent
              message={message}
              messageIndex={index}
              originalMessage={originalMessage}
              submittingDraft={submittingDraft}
              disabled={loading || actionLoading}
              onAddDraft={async (action, key) => {
                setSubmittingDraft(key);
                try {
                  await onAddDraft(action);
                } finally {
                  setSubmittingDraft(null);
                }
              }}
              onEditDraft={onEditDraft}
            />
          )
        };
      }),
    [actionLoading, loading, messages, onAddDraft, onEditDraft, submittingDraft]
  );

  async function submit(value: string) {
    const text = value.trim();
    if (!text) {
      return;
    }
    await onSend(text);
    setDraft("");
  }

  return (
    <Card
      className="panel chat-panel"
      data-testid="chat-panel"
      title={
        <Space>
          <RobotOutlined />
          <Typography.Text strong>{labels.chat.title}</Typography.Text>
        </Space>
      }
      extra={
        <Popconfirm
          title={labels.chat.clearTitle}
          description={labels.chat.clearDescription}
          okText={labels.chat.clearOk}
          cancelText={labels.settings.cancel}
          onConfirm={() => void onReset()}
        >
          <Button
            aria-label="Clear chat history"
            data-testid="reset-chat-button"
            disabled={loading || messages.length === 0}
            icon={<DeleteOutlined />}
            size="small"
            type="text"
          />
        </Popconfirm>
      }
    >
      <div className="bubble-stage">
        {items.length ? (
          <Bubble.List
            roles={{
              assistant: {
                placement: "start",
                avatar: { icon: <RobotOutlined /> }
              },
              user: {
                placement: "end",
                avatar: { icon: <UserOutlined /> }
              }
            }}
            items={items}
          />
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={labels.chat.noMessages} />
        )}
      </div>
      {error && (
        <Alert
          className="chat-stream-error"
          data-testid="chat-stream-error"
          type="error"
          showIcon
          message={error}
        />
      )}
      <div className="chat-input-row">
        <Sender
          className="chat-sender"
          value={draft}
          loading={loading}
          placeholder={labels.chat.placeholder}
          submitType="enter"
          onChange={setDraft}
          onSubmit={submit}
        />
        <Button
          className="chat-stop-button"
          data-testid="stop-chat-stream"
          icon={<StopOutlined />}
          disabled={!loading}
          onClick={onStop}
        >
          {labels.chat.stop}
        </Button>
      </div>
    </Card>
  );
}

interface MessageContentProps {
  message: ChatMessage;
  messageIndex: number;
  originalMessage: string;
  submittingDraft: string | null;
  disabled: boolean;
  onAddDraft: (action: ActionItem, key: string) => Promise<void>;
  onEditDraft: (action: ActionItem) => void;
}

function MessageContent({
  message,
  messageIndex,
  originalMessage,
  submittingDraft,
  disabled,
  onAddDraft,
  onEditDraft
}: MessageContentProps) {
  const labels = useMessages();
  const parsed = message.role === "assistant" ? parseActionDrafts(message.content) : null;
  const markdown = parsed?.markdown ?? message.content;
  return (
    <div className="chat-message-content">
      <div className="markdown-body">
        <ReactMarkdown>{markdown}</ReactMarkdown>
      </div>
      {parsed?.drafts.map((draft, draftIndex) => {
        const key = `${message.created_at ?? messageIndex}-${draftIndex}`;
        const action = withDraftMetadata(draft, {
          originalMessage,
          draftId: key
        });
        return (
          <DraftActionCard
            key={key}
            action={action}
            originalMessage={originalMessage}
            loading={submittingDraft === key}
            disabled={disabled || submittingDraft !== null}
            onAdd={() => onAddDraft(action, key)}
            onEdit={() => onEditDraft(action)}
            labels={labels}
          />
        );
      })}
    </div>
  );
}

interface DraftActionCardProps {
  action: ActionItem;
  originalMessage: string;
  loading: boolean;
  disabled: boolean;
  onAdd: () => Promise<void>;
  onEdit: () => void;
  labels: ReturnType<typeof useMessages>;
}

function DraftActionCard({
  action,
  originalMessage,
  loading,
  disabled,
  onAdd,
  onEdit,
  labels
}: DraftActionCardProps) {
  const expected = action.metadata?.expected;
  const expectedText = expectedSummary(expected);
  return (
    <Card size="small" className="draft-action-card">
      <Space direction="vertical" size={8} className="full-width">
        <Space wrap>
          <Tag color="blue">{labels.chat.draft}</Tag>
          <Typography.Text strong>
            {action.robot}.{action.capability}
          </Typography.Text>
        </Space>
        <Descriptions size="small" column={1} className="tight-descriptions">
          <Descriptions.Item label={labels.chat.task}>
            <Typography.Text>{originalMessage || "-"}</Typography.Text>
          </Descriptions.Item>
          <Descriptions.Item label={labels.chat.action}>
            <Typography.Text>
              {action.robot}.{action.capability}
            </Typography.Text>
          </Descriptions.Item>
          <Descriptions.Item label={labels.chat.params}>
            <JsonSummaryLine
              label={labels.chat.params}
              value={action.params}
              fallback={labels.chat.noParams}
            />
          </Descriptions.Item>
          <Descriptions.Item label={labels.chat.reason}>
            <Typography.Text>{action.reason || "-"}</Typography.Text>
          </Descriptions.Item>
          {expectedText && (
            <Descriptions.Item label={labels.chat.expected}>
              <JsonSummaryLine label={labels.chat.expected} text={expectedText} />
            </Descriptions.Item>
          )}
        </Descriptions>
        <Space wrap>
          <Button
            type="primary"
            size="small"
            icon={<PlusOutlined />}
            loading={loading}
            disabled={disabled}
            onClick={() => void onAdd()}
          >
            {labels.chat.addToActions}
          </Button>
          <Button
            size="small"
            icon={<EditOutlined />}
            disabled={disabled}
            onClick={onEdit}
          >
            {labels.chat.edit}
          </Button>
        </Space>
      </Space>
    </Card>
  );
}

function findPreviousUserMessage(messages: ChatMessage[], index: number): string {
  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    const message = messages[cursor];
    if (message?.role === "user") {
      return message.content;
    }
  }
  return "";
}

function withDraftMetadata(
  action: ActionItem,
  {
    originalMessage,
    draftId
  }: {
    originalMessage: string;
    draftId: string;
  }
): ActionItem {
  return {
    ...action,
    metadata: {
      ...(action.metadata ?? {}),
      source: "chat_draft",
      proposed_by: "gui",
      user_message: originalMessage,
      draft_reason: action.reason ?? undefined,
      draft_id: draftId
    }
  };
}
