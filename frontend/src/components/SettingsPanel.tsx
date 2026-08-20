import {
  ApiOutlined,
  DeleteOutlined,
  DownloadOutlined,
  SaveOutlined,
  SettingOutlined
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Popconfirm,
  Segmented,
  Select,
  Space,
  Tag,
  Typography
} from "antd";
import { useEffect, useState } from "react";
import {
  exportAudit,
  fetchLLMSettings,
  fetchStateCheck,
  resetWorkspace,
  saveLLMSettings,
  testLLMSettings
} from "../api";
import type { Language, Messages, ThemeMode } from "../locales";
import type { AgentState, ExportAuditResponse, HealthState, LLMSettingsSummary, StateCheckResult } from "../types";
import { JsonSummaryLine } from "./JsonSummary";
import { oneLine } from "./utils";

interface SettingsPanelProps {
  health: HealthState | null;
  state: AgentState | null;
  labels: Messages;
  language: Language;
  themeMode: ThemeMode;
  onLanguageChange: (language: Language) => void;
  onThemeChange: (mode: ThemeMode) => void;
  onShowTour: () => void;
  onWorkspaceReset?: (state: AgentState, message: string) => void;
}

interface LLMSettingsFormValues {
  base_url: string;
  api_key?: string;
  model: string;
  api_mode: string;
}

export function SettingsPanel({
  health,
  state,
  labels,
  language,
  themeMode,
  onLanguageChange,
  onThemeChange,
  onShowTour,
  onWorkspaceReset
}: SettingsPanelProps) {
  const ready = Boolean(state?.ready ?? health?.ready);
  const [form] = Form.useForm<LLMSettingsFormValues>();
  const [llmSettings, setLlmSettings] = useState<LLMSettingsSummary | null>(null);
  const [stateCheck, setStateCheck] = useState<StateCheckResult | null>(null);
  const [stateCheckError, setStateCheckError] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const [resetFeedback, setResetFeedback] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);
  const [auditFeedback, setAuditFeedback] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; text: string } | null>(
    null
  );
  const [loading, setLoading] = useState(false);
  const [testing, setTesting] = useState(false);
  const [exportingAudit, setExportingAudit] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchStateCheck()
      .then((response) => {
        if (cancelled) {
          return;
        }
        setStateCheck(response);
        setStateCheckError(null);
      })
      .catch((error) => {
        if (!cancelled) {
          setStateCheckError(error instanceof Error ? error.message : String(error));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [state?.backend, state?.workspace_path, health?.backend, health?.workspace_path]);

  useEffect(() => {
    let cancelled = false;
    fetchLLMSettings()
      .then((response) => {
        if (cancelled) {
          return;
        }
        const settings = response.settings ?? response;
        setLlmSettings(settings);
        form.setFieldsValue({
          base_url: settings.base_url,
          model: settings.model,
          api_mode: settings.api_mode
        });
      })
      .catch((error) => {
        if (!cancelled) {
          setFeedback({ type: "error", text: error instanceof Error ? error.message : String(error) });
        }
    });
    return () => {
      cancelled = true;
    };
  }, [form]);

  async function handleExportAudit() {
    setExportingAudit(true);
    setAuditFeedback(null);
    try {
      const response: ExportAuditResponse = await exportAudit();
      const outDir = response.out_dir ?? response.result?.out_dir ?? "workspace/audit";
      setAuditFeedback({
        type: "success",
        text: `${response.message ?? "Exported audit view."} ${outDir}`
      });
    } catch (error) {
      setAuditFeedback({ type: "error", text: error instanceof Error ? error.message : String(error) });
    } finally {
      setExportingAudit(false);
    }
  }

  async function handleSave(values: LLMSettingsFormValues) {
    setLoading(true);
    setFeedback(null);
    try {
      const response = await saveLLMSettings({
        base_url: values.base_url,
        api_key: values.api_key ?? "",
        model: values.model,
        api_mode: values.api_mode
      });
      const settings = response.settings ?? response;
      setLlmSettings(settings);
      form.setFieldsValue({ api_key: "" });
      setFeedback({ type: "success", text: response.message ?? "LLM settings saved." });
    } catch (error) {
      setFeedback({ type: "error", text: error instanceof Error ? error.message : String(error) });
    } finally {
      setLoading(false);
    }
  }

  async function handleWorkspaceReset() {
    setResetting(true);
    setResetFeedback(null);
    try {
      const response = await resetWorkspace();
      setResetFeedback({ type: "success", text: response.message });
      onWorkspaceReset?.(response.state, response.message);
    } catch (error) {
      setResetFeedback({
        type: "error",
        text: error instanceof Error ? error.message : String(error)
      });
    } finally {
      setResetting(false);
    }
  }

  async function handleTest() {
    setTesting(true);
    setFeedback(null);
    try {
      const response = await testLLMSettings();
      const settings = response.settings ?? response;
      setLlmSettings(settings);
      setFeedback({
        type: response.ok ? "success" : "error",
        text: response.message ?? (response.ok ? "LLM connection test passed." : "LLM test failed.")
      });
    } catch (error) {
      setFeedback({ type: "error", text: error instanceof Error ? error.message : String(error) });
    } finally {
      setTesting(false);
    }
  }

  const activeBackend = stateCheck?.backend ?? state?.backend ?? health?.backend ?? "-";
  const backendRole = stateCheck?.backend_role ?? (activeBackend === "sqlite" ? "recommended" : undefined);
  const backendTagColor = backendRole === "recommended" ? "green" : "default";
  const backendNotice =
    backendRole === "recommended"
      ? {
          type: "success" as const,
          message: "Recommended backend",
          description:
            "state.db is source of truth; SQLite payloads are JSON; SAFETY.md remains file source."
        }
      : {
          type: "info" as const,
          message: "State backend",
          description: "State-check is loading or unavailable."
        };
  const stateCheckStatus = stateCheck
    ? stateCheck.ok
      ? "ready"
      : "needs attention"
    : stateCheckError
      ? "unavailable"
      : "loading";

  return (
    <Card
      className="panel settings-panel"
      data-testid="settings-panel"
      title={
        <Space>
          <SettingOutlined />
          <Typography.Text strong>{labels.settings.title}</Typography.Text>
        </Space>
      }
    >
      <Descriptions size="small" column={1} className="tight-descriptions">
        <Descriptions.Item label="Backend">
          <Tag color={backendTagColor}>{activeBackend}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="Workspace">
          <Tag color={ready ? "green" : "gold"}>{ready ? "ready" : "not ready"}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="Config">
          {state?.config_path ?? health?.config_path ?? "-"}
        </Descriptions.Item>
        <Descriptions.Item label="Workspace path">
          {state?.workspace_path ?? health?.workspace_path ?? "-"}
        </Descriptions.Item>
        <Descriptions.Item label="Message">
          {state?.message ?? health?.message ?? "-"}
        </Descriptions.Item>
        <Descriptions.Item label="Task">
          {oneLine(state?.task?.body ?? state?.task?.task ?? state?.task, "-")}
        </Descriptions.Item>
      </Descriptions>
      <div className="panel-divider" />
      <Space direction="vertical" size={8} className="full-width" data-testid="appearance-settings">
        <Typography.Text strong>{labels.settings.appearance}</Typography.Text>
        <div className="two-col">
          <Space direction="vertical" size={4}>
            <Typography.Text type="secondary">{labels.settings.language}</Typography.Text>
            <Segmented
              value={language}
              onChange={(value) => onLanguageChange(value as Language)}
              data-testid="language-switch"
              options={[
                { label: "中文", value: "zh" },
                { label: "English", value: "en" }
              ]}
            />
          </Space>
          <Space direction="vertical" size={4}>
            <Typography.Text type="secondary">{labels.settings.theme}</Typography.Text>
            <Segmented
              value={themeMode}
              onChange={(value) => onThemeChange(value as ThemeMode)}
              data-testid="theme-switch"
              options={[
                { label: labels.settings.light, value: "light" },
                { label: labels.settings.dark, value: "dark" }
              ]}
            />
          </Space>
        </div>
        <Button onClick={onShowTour} data-testid="show-tour-button">
          {labels.settings.showTour}
        </Button>
      </Space>
      <div className="panel-divider" />
      <Space
        direction="vertical"
        size={8}
        className="full-width state-backend-summary"
        data-testid="state-backend-summary"
      >
        <Space wrap>
          <Typography.Text strong>{labels.settings.stateBackend}</Typography.Text>
          <Tag color={backendTagColor}>
            {stateCheck?.backend_label ?? activeBackend}
          </Tag>
          <Tag color={stateCheck?.audit_export_writable ? "green" : "gold"}>
            audit {stateCheck?.audit_export_writable ? "writable" : "check"}
          </Tag>
        </Space>
        <Alert
          type={backendNotice.type}
          showIcon
          message={backendNotice.message}
          description={backendNotice.description}
        />
        <Descriptions size="small" column={1} className="tight-descriptions">
          <Descriptions.Item label="State-check">
            <Tag color={stateCheck?.ok ? "green" : "gold"}>{stateCheckStatus}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Workspace path">
            {stateCheck?.workspace_path ?? state?.workspace_path ?? health?.workspace_path ?? "-"}
          </Descriptions.Item>
          <Descriptions.Item label="Source of truth">
            {stateCheck?.source_of_truth ?? "-"}
          </Descriptions.Item>
          <Descriptions.Item label="Payload">
            {stateCheck?.payload_format ?? "-"}
          </Descriptions.Item>
          <Descriptions.Item label="Human view">
            {stateCheck?.human_view ?? "export-audit"}
          </Descriptions.Item>
          <Descriptions.Item label="Safety source">
            {stateCheck?.safety_source ?? "SAFETY.md"}
          </Descriptions.Item>
          <Descriptions.Item label="SQLite schema">
            {stateCheck?.sqlite_schema_complete == null ? "n/a" : stateCheck.sqlite_schema_complete ? "complete" : "incomplete"}
          </Descriptions.Item>
          <Descriptions.Item label="Switching">
            {stateCheck?.switching_model ?? "Change config and restart; no GUI live backend switch."}
          </Descriptions.Item>
        </Descriptions>
        <Space wrap>
          <Button
            icon={<DownloadOutlined />}
            loading={exportingAudit}
            disabled={!ready || stateCheck?.workspace_initialized === false}
            onClick={handleExportAudit}
            data-testid="export-audit-button"
          >
            {labels.settings.exportAudit}
          </Button>
          <Typography.Text type="secondary">
            Creates a read-only audit view; it does not change backend.
          </Typography.Text>
        </Space>
        {stateCheckError && (
          <Alert
            data-testid="state-check-feedback"
            type="warning"
            showIcon
            message="State-check unavailable"
            description={stateCheckError}
          />
        )}
        {auditFeedback && (
          <Alert
            data-testid="export-audit-feedback"
            type={auditFeedback.type}
            showIcon
            message={auditFeedback.text}
          />
        )}
      </Space>
      <div className="panel-divider" />
      <Space direction="vertical" size={8} className="full-width">
        <Space wrap>
          <Typography.Text strong>{labels.settings.llm}</Typography.Text>
          <Tag color={llmSettings?.has_api_key ? "green" : "gold"}>
            {llmSettings?.has_api_key ? `key ${llmSettings.masked_api_key}` : "no key"}
          </Tag>
        </Space>
        <Form
          form={form}
          layout="vertical"
          className="llm-settings-form"
          initialValues={{ api_mode: "chat_completions" }}
          onFinish={handleSave}
        >
          <Form.Item label="Base URL" name="base_url">
            <Input placeholder="https://api.openai.com/v1" />
          </Form.Item>
          <Form.Item label="API key" name="api_key">
            <Input.Password autoComplete="new-password" placeholder="Leave blank to keep existing key" />
          </Form.Item>
          <div className="two-col">
            <Form.Item label="Model" name="model">
              <Input placeholder="gpt-5.4" />
            </Form.Item>
            <Form.Item label="API mode" name="api_mode">
              <Select
                options={[
                  { value: "chat_completions", label: "chat_completions" },
                  { value: "responses", label: "responses" }
                ]}
              />
            </Form.Item>
          </div>
          <Space wrap>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              icon={<SaveOutlined />}
              data-testid="save-llm-settings"
            >
              {labels.settings.save}
            </Button>
            <Button
              onClick={handleTest}
              loading={testing}
              icon={<ApiOutlined />}
              data-testid="test-llm-settings"
            >
              {labels.settings.testConnection}
            </Button>
          </Space>
        </Form>
        {feedback && (
          <Alert
            data-testid="llm-settings-feedback"
            type={feedback.type}
            showIcon
            message={feedback.text}
          />
        )}
      </Space>
      <div className="panel-divider" />
      <Typography.Text strong>{labels.settings.plan}</Typography.Text>
      <JsonSummaryLine label={labels.settings.plan} value={state?.plan ?? {}} />
      <div className="panel-divider" />
      <Space
        direction="vertical"
        size={8}
        className="full-width"
        data-testid="danger-zone"
      >
        <Typography.Text strong type="danger">
          {labels.settings.dangerZone}
        </Typography.Text>
        <Alert
          type="warning"
          showIcon
          message={labels.settings.resetTitle}
          description={labels.settings.resetDescription}
        />
        <Popconfirm
          title={labels.settings.resetConfirmTitle}
          description={labels.settings.resetConfirmDescription}
          okText={labels.settings.resetOk}
          okButtonProps={{ danger: true }}
          cancelText={labels.settings.cancel}
          onConfirm={() => void handleWorkspaceReset()}
        >
          <Button
            danger
            icon={<DeleteOutlined />}
            loading={resetting}
            data-testid="reset-workspace-button"
          >
            {labels.settings.resetOk}
          </Button>
        </Popconfirm>
        {resetFeedback && (
          <Alert
            data-testid="reset-workspace-feedback"
            type={resetFeedback.type}
            showIcon
            message={resetFeedback.text}
          />
        )}
      </Space>
    </Card>
  );
}
