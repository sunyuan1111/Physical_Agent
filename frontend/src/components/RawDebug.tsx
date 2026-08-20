import { CodeOutlined } from "@ant-design/icons";
import { Card, Collapse, Empty, Space, Tag, Tree, Typography } from "antd";
import type { DataNode } from "antd/es/tree";
import { useMessages } from "../locales/context";
import type { AgentState } from "../types";
import { formatRawDebugFields } from "../viewmodels/overview";
import { formatObjectValue } from "./readableFormatters";

interface RawDebugProps {
  state?: AgentState | null;
  raw?: Record<string, unknown>;
}

export function RawDebug({ state, raw }: RawDebugProps) {
  const labels = useMessages();
  const debugValue = raw ?? formatRawDebugFields(state);
  const hasRawFields = Object.keys(debugValue).length > 0;
  return (
    <Card
      className="panel"
      data-testid="raw-debug-panel"
      title={
        <Space>
          <CodeOutlined />
          <Typography.Text strong>{labels.panels.rawDebug}</Typography.Text>
        </Space>
      }
    >
      {hasRawFields ? (
        <AntdRawDebugTree value={debugValue} />
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No raw debug fields" />
      )}
    </Card>
  );
}

function AntdRawDebugTree({ value }: { value: Record<string, unknown> }) {
  const treeData = buildRawDebugNodes(value, "raw");
  const expandedKeys = collectExpandedKeys(treeData, 2);
  return (
    <Collapse
      ghost
      size="small"
      destroyOnHidden
      className="raw-debug-collapse"
      data-testid="raw-debug-collapse"
      items={[
        {
          key: "raw",
          label: (
            <span className="raw-debug-label">
              <CodeOutlined />
              Unknown/raw fields
            </span>
          ),
          children: (
            <Tree
              blockNode
              selectable={false}
              treeData={treeData}
              defaultExpandedKeys={expandedKeys}
              className="raw-debug-tree"
            />
          )
        }
      ]}
    />
  );
}

function buildRawDebugNodes(value: unknown, path: string): DataNode[] {
  if (Array.isArray(value)) {
    return value.map((item, index) => buildRawDebugNode(`[${index}]`, item, `${path}.${index}`));
  }
  if (isRecord(value)) {
    return Object.entries(value).map(([key, item]) =>
      buildRawDebugNode(key, item, `${path}.${encodeKey(key)}`)
    );
  }
  return [buildRawDebugNode("value", value, `${path}.value`)];
}

function buildRawDebugNode(label: string, value: unknown, key: string): DataNode {
  if (Array.isArray(value)) {
    return {
      key,
      title: <RawDebugNodeTitle label={label} badge={`${value.length} items`} />,
      children: value.map((item, index) => buildRawDebugNode(`[${index}]`, item, `${key}.${index}`))
    };
  }

  if (isRecord(value)) {
    const entries = Object.entries(value);
    return {
      key,
      title: (
        <RawDebugNodeTitle
          label={label}
          badge={entries.length ? `${entries.length} fields` : "{}"}
        />
      ),
      children: entries.map(([childKey, item]) =>
        buildRawDebugNode(childKey, item, `${key}.${encodeKey(childKey)}`)
      )
    };
  }

  return {
    key,
    isLeaf: true,
    title: (
      <RawDebugNodeTitle
        label={label}
        badge={valueType(value)}
        value={formatRawScalarValue(value)}
      />
    )
  };
}

function RawDebugNodeTitle({
  label,
  badge,
  value
}: {
  label: string;
  badge: string;
  value?: string;
}) {
  return (
    <Space size={8} className="raw-debug-node" wrap>
      <Typography.Text code className="raw-debug-key">
        {label}
      </Typography.Text>
      <Tag>{badge}</Tag>
      {value !== undefined && (
        <Typography.Text className="raw-debug-value">{value}</Typography.Text>
      )}
    </Space>
  );
}

function collectExpandedKeys(nodes: DataNode[], maxDepth: number, depth = 0): string[] {
  if (depth >= maxDepth) {
    return [];
  }
  return nodes.flatMap((node) => {
    const children = node.children ?? [];
    if (!children.length) {
      return [];
    }
    return [String(node.key), ...collectExpandedKeys(children, maxDepth, depth + 1)];
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function encodeKey(key: string): string {
  return encodeURIComponent(key).replace(/\./g, "%2E");
}

function valueType(value: unknown): string {
  if (value === null) {
    return "null";
  }
  if (value === undefined) {
    return "undefined";
  }
  return typeof value;
}

function formatRawScalarValue(value: unknown): string {
  if (value === null) {
    return "null";
  }
  if (value === undefined) {
    return "undefined";
  }
  return formatObjectValue(value);
}
