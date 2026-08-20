import { AimOutlined, FormOutlined, PlusOutlined } from "@ant-design/icons";
import { Button, Card, Form, Input, Select, Space, Typography } from "antd";
import { useEffect, useMemo } from "react";
import type { ActionItem, AgentState, RobotInfo } from "../types";

interface ProposalPanelProps {
  state: AgentState | null;
  loading: boolean;
  onSubmitTask: (task: string) => Promise<void>;
  onProposeAction: (action: ActionItem) => Promise<void>;
  prefillAction?: ActionItem | null;
  prefillVersion?: number;
}

interface TaskValues {
  task: string;
}

interface ActionValues {
  id?: string;
  robot?: string;
  capability?: string;
  params?: string;
  reason?: string;
  depends_on?: string;
}

export function ProposalPanel({
  state,
  loading,
  onSubmitTask,
  onProposeAction,
  prefillAction = null,
  prefillVersion = 0
}: ProposalPanelProps) {
  const [taskForm] = Form.useForm<TaskValues>();
  const [actionForm] = Form.useForm<ActionValues>();
  const robots = state?.capabilities?.robots ?? {};
  const robotId = Form.useWatch("robot", actionForm);
  const robotOptions = useMemo(
    () =>
      Object.entries(robots).map(([id, robot]) => ({
        value: id,
        label: `${id} (${robot.kind ?? "robot"})`
      })),
    [robots]
  );
  const capabilityOptions = useMemo(() => {
    const robot = robotId ? (robots[robotId] as RobotInfo | undefined) : undefined;
    return (
      robot?.capabilities?.map((capability) => ({
        value: capability.name ?? "",
        label: capability.name ?? ""
      })) ?? []
    ).filter((item) => item.value);
  }, [robotId, robots]);

  useEffect(() => {
    if (!prefillAction) {
      return;
    }
    actionForm.setFieldsValue({
      id: prefillAction.id,
      robot: prefillAction.robot,
      capability: prefillAction.capability,
      params: JSON.stringify(prefillAction.params ?? {}, null, 2),
      reason: prefillAction.reason ?? undefined,
      depends_on: prefillAction.depends_on?.join(", ") ?? ""
    });
  }, [actionForm, prefillAction, prefillVersion]);

  async function submitTask(values: TaskValues) {
    await onSubmitTask(values.task.trim());
    taskForm.resetFields();
  }

  async function submitAction(values: ActionValues) {
    if (!values.robot || !values.capability) {
      throw new Error("Robot and capability are required.");
    }
    let parsedParams: Record<string, unknown>;
    try {
      parsedParams = parseParams(values.params);
    } catch (error) {
      actionForm.setFields([
        {
          name: "params",
          errors: [error instanceof Error ? error.message : String(error)]
        }
      ]);
      return;
    }
    await onProposeAction({
      id: values.id?.trim() || `act_gui_${Date.now()}`,
      robot: values.robot,
      capability: values.capability,
      params: parsedParams,
      reason: values.reason?.trim() || "Proposed from GUI.",
      depends_on: splitList(values.depends_on),
      metadata: prefillAction?.metadata
    });
    actionForm.resetFields(["id", "params", "reason", "depends_on"]);
  }

  return (
    <Card
      className="panel"
      data-testid="proposal-panel"
      title={
        <Space>
          <FormOutlined />
          <Typography.Text strong>Task / Action Proposal</Typography.Text>
        </Space>
      }
    >
      <Form<TaskValues>
        form={taskForm}
        layout="vertical"
        onFinish={submitTask}
        requiredMark={false}
      >
        <Form.Item
          name="task"
          label="Task"
          rules={[{ required: true, message: "Task is required." }]}
        >
          <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} />
        </Form.Item>
        <Button htmlType="submit" type="primary" icon={<AimOutlined />} loading={loading}>
          Submit Task
        </Button>
      </Form>

      <div className="panel-divider" />

      <Form<ActionValues>
        form={actionForm}
        layout="vertical"
        initialValues={{ params: "{}" }}
        onFinish={submitAction}
        requiredMark={false}
      >
        <div className="two-col">
          <Form.Item name="robot" label="Robot" rules={[{ required: true }]}>
            <Select
              data-testid="proposal-robot-select"
              options={robotOptions}
              placeholder="robot"
            />
          </Form.Item>
          <Form.Item name="capability" label="Capability" rules={[{ required: true }]}>
            <Select
              data-testid="proposal-capability-select"
              options={capabilityOptions}
              placeholder="capability"
            />
          </Form.Item>
        </div>
        <Form.Item name="id" label="Action ID">
          <Input placeholder="auto" />
        </Form.Item>
        <Form.Item name="params" label="Params JSON">
          <Input.TextArea
            data-testid="proposal-params-input"
            autoSize={{ minRows: 3, maxRows: 6 }}
          />
        </Form.Item>
        <Form.Item name="reason" label="Reason">
          <Input />
        </Form.Item>
        <Form.Item name="depends_on" label="Depends on">
          <Input placeholder="act_001, act_002" />
        </Form.Item>
        <Button
          data-testid="propose-action-button"
          htmlType="submit"
          icon={<PlusOutlined />}
          loading={loading}
        >
          Propose Action
        </Button>
      </Form>
    </Card>
  );
}

function parseParams(value?: string): Record<string, unknown> {
  if (!value?.trim()) {
    return {};
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error('Params JSON is invalid. Enter an object such as {"key":"value"}.');
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Params JSON must be an object.");
  }
  return parsed as Record<string, unknown>;
}

function splitList(value?: string): string[] {
  return value
    ? value.split(",").map((item) => item.trim()).filter(Boolean)
    : [];
}
