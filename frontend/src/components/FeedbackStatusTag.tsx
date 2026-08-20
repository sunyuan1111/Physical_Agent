import { Badge, Tag } from "antd";
import { statusColor, statusText } from "./readableFormatters";

interface FeedbackStatusTagProps {
  status: unknown;
  badge?: boolean;
}

export function FeedbackStatusTag({ status, badge = false }: FeedbackStatusTagProps) {
  const text = statusText(status);
  const color = statusColor(status);
  if (badge) {
    return <Badge color={badgeColor(color)} text={text} />;
  }
  return <Tag color={color}>{text}</Tag>;
}

function badgeColor(color: string): string {
  if (color === "green") {
    return "#52c41a";
  }
  if (color === "red") {
    return "#ff4d4f";
  }
  if (color === "gold") {
    return "#faad14";
  }
  if (color === "blue") {
    return "#1677ff";
  }
  return "#8c8c8c";
}
