import { ApiOutlined, CodeOutlined, PlusCircleOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Select,
  Space,
  Tag,
  Typography
} from "antd";
import { useEffect, useState } from "react";
import { integrateHardware, registerRobot } from "../api";
import { useMessages } from "../locales/context";
import type { AgentState, IntegrateResult, SchemaProperty } from "../types";
import { compactSchemaSummary } from "./readableFormatters";

interface HardwarePanelProps {
  onStateChange: (state: AgentState) => void;
  onError: (error: Error) => void;
  onRobotRegistered?: () => void;
}

interface HardwareFormValues {
  source: string;
  name?: string;
  output?: string;
  mode: "scaffold" | "llm";
  model?: string;
}

interface RegisterFormValues {
  robot_id: string;
  driver: string;
  [key: string]: unknown;
}

function coerceSchemaValue(raw: unknown, schema: SchemaProperty | undefined): unknown {
  if (raw == null || raw === "") {
    return undefined;
  }
  const type = schema?.type;
  if (type === "integer" || type === "number") {
    const parsed = Number(raw);
    return Number.isNaN(parsed) ? raw : parsed;
  }
  if (type === "boolean") {
    return raw === true || raw === "true";
  }
  return raw;
}

export function HardwarePanel({ onStateChange, onError, onRobotRegistered }: HardwarePanelProps) {
  const labels = useMessages();
  const [form] = Form.useForm<HardwareFormValues>();
  const [registerForm] = Form.useForm<RegisterFormValues>();
  const [loading, setLoading] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; text: string } | null>(
    null
  );
  const [registerFeedback, setRegisterFeedback] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);
  const [result, setResult] = useState<IntegrateResult | null>(null);
  const mode = Form.useWatch("mode", form) ?? "scaffold";

  async function handleFinish(values: HardwareFormValues) {
    setLoading(true);
    setFeedback(null);
    setResult(null);
    try {
      const response = await integrateHardware({
        source: values.source,
        name: values.name?.trim() || undefined,
        output: values.output?.trim() || undefined,
        llm: values.mode === "llm",
        model: values.mode === "llm" ? values.model?.trim() || undefined : undefined
      });
      setResult(response.result);
      setFeedback({ type: "success", text: response.message });
      onStateChange(response.state);
    } catch (error) {
      const err = error instanceof Error ? error : new Error(String(error));
      setFeedback({ type: "error", text: err.message });
      onError(err);
    } finally {
      setLoading(false);
    }
  }

  const profile = result?.source ?? result?.integration?.source ?? null;
  const generatedFiles =
    result?.generated_files ?? result?.integration?.generated_files ?? [];
  const nextSteps = result?.next_steps ?? profile?.next_steps ?? [];
  const validation = result?.validation ?? null;
  const outputPath = result?.output_path ?? result?.integration?.output_path ?? "";
  const schemaProperties: Record<string, SchemaProperty> = Object.fromEntries(
    Object.entries(profile?.config_schema?.properties ?? {}).filter(
      ([, property]) => property?.type !== "object"
    )
  );

  useEffect(() => {
    if (result) {
      setRegisterFeedback(null);
      registerForm.setFieldsValue({
        robot_id: profile?.name ?? "",
        driver: outputPath,
        ...Object.fromEntries(
          Object.entries(schemaProperties)
            .filter(([, property]) => property.default != null)
            .map(([key, property]) => [key, String(property.default)])
        )
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result]);

  async function handleRegister(values: RegisterFormValues) {
    setRegistering(true);
    setRegisterFeedback(null);
    try {
      const config: Record<string, unknown> = {};
      for (const [key, property] of Object.entries(schemaProperties)) {
        const coerced = coerceSchemaValue(values[key], property);
        if (coerced !== undefined) {
          config[key] = coerced;
        }
      }
      const response = await registerRobot({
        robot_id: values.robot_id.trim(),
        driver: values.driver.trim(),
        config
      });
      setRegisterFeedback({ type: "success", text: response.message });
      onRobotRegistered?.();
    } catch (error) {
      const err = error instanceof Error ? error : new Error(String(error));
      setRegisterFeedback({ type: "error", text: err.message });
      onError(err);
    } finally {
      setRegistering(false);
    }
  }

  return (
    <Card
      className="panel"
      data-testid="hardware-panel"
      title={
        <Space>
          <ApiOutlined />
          <Typography.Text strong>{labels.panels.hardware}</Typography.Text>
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        message={labels.hardware.proposalOnly}
        description={labels.hardware.proposalOnlyDescription}
      />
      <div className="panel-divider" />
      <Form
        form={form}
        layout="vertical"
        initialValues={{ mode: "scaffold" }}
        onFinish={handleFinish}
      >
        <Form.Item
          label={labels.hardware.source}
          name="source"
          rules={[{ required: true, message: labels.hardware.sourceRequired }]}
        >
          <Input
            placeholder="e.g. ./vendor_sdk or https://github.com/vendor/robot-sdk"
            data-testid="integrate-source-input"
          />
        </Form.Item>
        <div className="two-col">
          <Form.Item label={labels.hardware.driverName} name="name">
            <Input placeholder="my_arm_driver" data-testid="integrate-name-input" />
          </Form.Item>
          <Form.Item label={labels.hardware.outputDirectory} name="output">
            <Input placeholder="my_hardware/my_arm_driver" />
          </Form.Item>
        </div>
        <div className="two-col">
          <Form.Item label={labels.hardware.mode} name="mode">
            <Select
              data-testid="integrate-mode-select"
              options={[
                { value: "scaffold", label: labels.hardware.scaffoldMode },
                { value: "llm", label: labels.hardware.llmMode }
              ]}
            />
          </Form.Item>
          {mode === "llm" && (
            <Form.Item label={labels.hardware.modelOverride} name="model">
              <Input placeholder="Leave blank to use configured model" />
            </Form.Item>
          )}
        </div>
        <Button
          type="primary"
          htmlType="submit"
          loading={loading}
          icon={<CodeOutlined />}
          data-testid="integrate-submit-button"
        >
          {labels.hardware.generateDriver}
        </Button>
      </Form>
      {feedback && (
        <>
          <div className="panel-divider" />
          <Alert
            data-testid="integrate-feedback"
            type={feedback.type}
            showIcon
            message={feedback.text}
          />
        </>
      )}
      {result && (
        <>
          <div className="panel-divider" />
          <Space direction="vertical" size={8} className="full-width" data-testid="integrate-result">
            <Space wrap>
              <Typography.Text strong>{labels.hardware.result}</Typography.Text>
              {result.llm_used != null && (
                <Tag color={result.llm_used ? "green" : "gold"}>
                  {result.llm_used ? "LLM draft" : "scaffold"}
                </Tag>
              )}
              {validation && (
                <Tag color={validation.ok ? "green" : "red"}>
                  validation {validation.ok ? "passed" : "failed"}
                </Tag>
              )}
            </Space>
            <Descriptions size="small" column={1} className="tight-descriptions">
              <Descriptions.Item label="Output path">
                <Typography.Text code>
                  {result.output_path ?? result.integration?.output_path ?? "-"}
                </Typography.Text>
              </Descriptions.Item>
              <Descriptions.Item label="Detected transport">
                {profile?.transport ?? "-"}
              </Descriptions.Item>
              <Descriptions.Item label="Robot kind">{profile?.robot_kind ?? "-"}</Descriptions.Item>
              <Descriptions.Item label="Title">{profile?.title ?? "-"}</Descriptions.Item>
            </Descriptions>
            {generatedFiles.length > 0 && (
              <Space size={5} wrap>
                {generatedFiles.map((file) => (
                  <Tag key={file}>{file}</Tag>
                ))}
              </Space>
            )}
            {profile?.capabilities && profile.capabilities.length > 0 && (
              <Space direction="vertical" size={4} className="full-width">
                <Typography.Text strong>Detected capabilities</Typography.Text>
                {profile.capabilities.map((capability, index) => (
                  <Space key={`${String(capability.name ?? "capability")}-${index}`} wrap size={5}>
                    <Tag color={capability.requires_approval ? "gold" : "default"}>
                      {String(capability.name ?? "capability")}
                    </Tag>
                    <Typography.Text type="secondary" className="schema-summary">
                      {compactSchemaSummary(capability.params_schema)}
                    </Typography.Text>
                  </Space>
                ))}
              </Space>
            )}
            {result.llm_error && (
              <Alert type="warning" showIcon message="LLM coding issue" description={result.llm_error} />
            )}
            {validation?.checks && validation.checks.length > 0 && (
              <Typography.Text type="secondary">
                Checks: {validation.checks.join(" · ")}
              </Typography.Text>
            )}
            {validation?.errors && validation.errors.length > 0 && (
              <Alert
                type="error"
                showIcon
                message="Validation errors"
                description={validation.errors.join("; ")}
              />
            )}
            {nextSteps.length > 0 && (
              <Typography.Text type="secondary">
                Next steps: {nextSteps.join(" · ")}
              </Typography.Text>
            )}
          </Space>
          <div className="panel-divider" />
          <Space direction="vertical" size={8} className="full-width" data-testid="register-robot">
            <Space>
              <PlusCircleOutlined />
              <Typography.Text strong>{labels.hardware.registerToConfig}</Typography.Text>
            </Space>
            <Typography.Text type="secondary">
              {labels.hardware.registerDescription}
            </Typography.Text>
            <Form form={registerForm} layout="vertical" onFinish={handleRegister}>
              <div className="two-col">
                <Form.Item
                  label={labels.hardware.robotId}
                  name="robot_id"
                  rules={[{ required: true, message: "Robot ID is required" }]}
                >
                  <Input placeholder="my_arm_1" data-testid="register-robot-id" />
                </Form.Item>
                <Form.Item
                  label={labels.hardware.driver}
                  name="driver"
                  rules={[{ required: true, message: "Driver is required" }]}
                >
                  <Input placeholder="my_hardware/my_driver" />
                </Form.Item>
              </div>
              {Object.entries(schemaProperties).map(([key, property]) => (
                <Form.Item
                  key={key}
                  label={`${key}${property.type ? ` (${property.type})` : ""}`}
                  name={key}
                  tooltip={property.description}
                >
                  {Array.isArray(property.enum) && property.enum.length ? (
                    <Select
                      allowClear
                      options={property.enum.map((option) => ({
                        value: String(option),
                        label: String(option)
                      }))}
                    />
                  ) : (
                    <Input
                      placeholder={
                        property.default != null
                          ? `default: ${String(property.default)}`
                          : property.description ?? ""
                      }
                    />
                  )}
                </Form.Item>
              ))}
              <Button
                type="primary"
                htmlType="submit"
                loading={registering}
                icon={<PlusCircleOutlined />}
                data-testid="register-robot-button"
              >
                {labels.hardware.addToConfig}
              </Button>
            </Form>
            {registerFeedback && (
              <Alert
                data-testid="register-robot-feedback"
                type={registerFeedback.type}
                showIcon
                message={registerFeedback.text}
              />
            )}
          </Space>
        </>
      )}
    </Card>
  );
}
