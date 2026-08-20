import {
  ApiOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  DeploymentUnitOutlined,
  GlobalOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  ThunderboltOutlined
} from "@ant-design/icons";
import { Layout, Menu, Typography } from "antd";
import type { MenuProps } from "antd";
import type { ReactNode } from "react";
import type { Messages } from "../locales";

export type PageKey =
  | "overview"
  | "actions"
  | "world"
  | "robots"
  | "hardware"
  | "memory"
  | "safety"
  | "events"
  | "settings";

export const PAGE_LABELS: Record<PageKey, string> = {
  overview: "Overview",
  actions: "Actions",
  world: "World",
  robots: "Robots",
  hardware: "Hardware",
  memory: "Memory",
  safety: "Safety",
  events: "Events",
  settings: "Settings"
};

function navLabel(key: PageKey, labels: Messages["nav"]) {
  return <span>{labels[key]}</span>;
}

function navIcon(key: PageKey, icon: ReactNode) {
  return <span data-testid={`nav-${key}`}>{icon}</span>;
}

function navItems(labels: Messages["nav"]): MenuProps["items"] {
  return [
    {
      key: "overview",
      icon: navIcon("overview", <DashboardOutlined />),
      label: navLabel("overview", labels)
    },
    {
      key: "actions",
      icon: navIcon("actions", <DeploymentUnitOutlined />),
      label: navLabel("actions", labels)
    },
    { key: "world", icon: navIcon("world", <GlobalOutlined />), label: navLabel("world", labels) },
    { key: "robots", icon: navIcon("robots", <RobotOutlined />), label: navLabel("robots", labels) },
    {
      key: "hardware",
      icon: navIcon("hardware", <ApiOutlined />),
      label: navLabel("hardware", labels)
    },
    { key: "memory", icon: navIcon("memory", <DatabaseOutlined />), label: navLabel("memory", labels) },
    {
      key: "safety",
      icon: navIcon("safety", <SafetyCertificateOutlined />),
      label: navLabel("safety", labels)
    },
    {
      key: "events",
      icon: navIcon("events", <ThunderboltOutlined />),
      label: navLabel("events", labels)
    },
    {
      key: "settings",
      icon: navIcon("settings", <SettingOutlined />),
      label: navLabel("settings", labels)
    }
  ];
}

interface SidebarNavProps {
  activePage: PageKey;
  collapsed: boolean;
  labels: Messages["nav"];
  onChange: (page: PageKey) => void;
  onCollapse: (collapsed: boolean) => void;
}

export function SidebarNav({
  activePage,
  collapsed,
  labels,
  onChange,
  onCollapse
}: SidebarNavProps) {
  return (
    <Layout.Sider
      className="app-sidebar"
      data-testid="sidebar-nav"
      width={216}
      collapsedWidth={56}
      collapsible
      breakpoint="lg"
      collapsed={collapsed}
      onCollapse={onCollapse}
    >
      <div className="sidebar-brand">
        <div className="brand-mark">PA</div>
        {!collapsed && (
          <div className="brand-copy">
            <Typography.Text strong>Physical Agent</Typography.Text>
            <Typography.Text type="secondary">Workbench</Typography.Text>
          </div>
        )}
      </div>
      <Menu
        mode="inline"
        selectedKeys={[activePage]}
        items={navItems(labels)}
        onClick={({ key }) => onChange(key as PageKey)}
      />
    </Layout.Sider>
  );
}
