import { InboxOutlined } from "@ant-design/icons";
import { Alert, Card, Input, InputNumber, Space, Upload, Typography } from "antd";
import type { UploadProps } from "antd";
import { useState } from "react";
import { uploadBrowserFile } from "../api";
import type { AgentState, UploadResponse } from "../types";

interface UploadPanelProps {
  onUploaded: (state: AgentState, response: UploadResponse) => void;
  onError: (error: Error) => void;
}

const ACCEPTED_SUFFIXES = ".txt,.md,.markdown,.py,.json,.yaml,.yml,.toml,.csv,.log";
const ACCEPTED_SUFFIX_LIST = ACCEPTED_SUFFIXES.split(",");
const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;

interface UploadFeedback {
  type: "success" | "error";
  message: string;
  description?: string;
}

export function UploadPanel({ onUploaded, onError }: UploadPanelProps) {
  const [tags, setTags] = useState("");
  const [importance, setImportance] = useState(0);
  const [feedback, setFeedback] = useState<UploadFeedback | null>(null);

  const uploadProps: UploadProps = {
    name: "file",
    multiple: false,
    accept: ACCEPTED_SUFFIXES,
    showUploadList: { showRemoveIcon: true },
    beforeUpload: (file) => {
      const validationError = validateUploadFile(file);
      if (!validationError) {
        return true;
      }
      setFeedback({
        type: "error",
        message: validationError.message,
        description: "Choose a supported text file no larger than 5MB."
      });
      onError(validationError);
      return Upload.LIST_IGNORE;
    },
    customRequest: async (options) => {
      setFeedback(null);
      try {
        const file = options.file as File;
        const response = await uploadBrowserFile(file, tags, importance);
        options.onSuccess?.(response, file);
        setFeedback({
          type: "success",
          message: `${response.filename} uploaded`,
          description: `${response.size_bytes} bytes stored as untrusted proposal context.`
        });
        onUploaded(response.state, response);
      } catch (error) {
        const normalized = error instanceof Error ? error : new Error(String(error));
        options.onError?.(normalized);
        setFeedback({
          type: "error",
          message: normalized.message,
          description: "The file was not ingested."
        });
        onError(normalized);
      }
    }
  };

  return (
    <Card
      className="panel"
      data-testid="upload-panel"
      title={
        <Space>
          <InboxOutlined />
          <Typography.Text strong>Upload</Typography.Text>
        </Space>
      }
    >
      <div className="two-col">
        <Input
          value={tags}
          onChange={(event) => setTags(event.target.value)}
          placeholder="tags"
        />
        <InputNumber
          value={importance}
          min={0}
          max={10}
          onChange={(value) => setImportance(Number(value ?? 0))}
          className="full-width"
        />
      </div>
      <Upload.Dragger {...uploadProps} className="upload-drop">
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text">Drop text files here</p>
        <p className="ant-upload-hint">5MB max</p>
      </Upload.Dragger>
      {feedback && (
        <Alert
          className="upload-feedback"
          data-testid="upload-feedback"
          type={feedback.type}
          showIcon
          message={feedback.message}
          description={feedback.description}
        />
      )}
    </Card>
  );
}

function validateUploadFile(file: File): Error | null {
  const suffix = file.name.includes(".")
    ? `.${file.name.split(".").pop()?.toLowerCase() ?? ""}`
    : "";
  if (!ACCEPTED_SUFFIX_LIST.includes(suffix)) {
    return new Error(
      `Unsupported upload type: ${suffix || "<none>"}. ` +
        `Supported text suffixes: ${ACCEPTED_SUFFIX_LIST.join(", ")}.`
    );
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return new Error("Uploaded file exceeds the 5MB limit.");
  }
  return null;
}
