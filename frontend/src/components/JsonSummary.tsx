import { Space, Typography } from "antd";
import type { ReactNode } from "react";
import { formatObjectValue } from "./readableFormatters";

interface JsonSummaryLineProps {
  label: string;
  value?: unknown;
  text?: string;
  fallback?: string;
  icon?: ReactNode;
  className?: string;
}

export function JsonSummaryLine({
  label,
  value,
  text,
  fallback = "-",
  icon,
  className
}: JsonSummaryLineProps) {
  const summary = text ?? formatObjectValue(value, fallback);
  return (
    <Typography.Text className={className ?? "schema-summary json-summary-line"}>
      {icon}
      {label}: {summary}
    </Typography.Text>
  );
}

interface JsonSummaryStackProps {
  items: Array<{
    key: string;
    label: string;
    value?: unknown;
    text?: string;
    fallback?: string;
  }>;
  className?: string;
}

export function JsonSummaryStack({ items, className }: JsonSummaryStackProps) {
  const visible = items.filter((item) => {
    const text = item.text ?? formatObjectValue(item.value, "");
    return text !== "";
  });
  if (!visible.length) {
    return null;
  }
  return (
    <Space direction="vertical" size={2} className={className ?? "full-width"}>
      {visible.map((item) => (
        <JsonSummaryLine
          key={item.key}
          label={item.label}
          value={item.value}
          text={item.text}
          fallback={item.fallback}
        />
      ))}
    </Space>
  );
}
