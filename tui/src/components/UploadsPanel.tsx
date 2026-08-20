import React from "react";
import { Box, Text } from "ink";
import type { AgentState, UploadMetadata, UploadResponse } from "../types.js";

interface UploadsPanelProps {
  state: AgentState | null;
  lastUpload?: UploadResponse | null;
}

export function UploadsPanel({ state, lastUpload }: UploadsPanelProps) {
  const uploads = state?.uploads?.uploads ?? [];
  return (
    <Box flexDirection="column" paddingX={1}>
      <Text color="cyan">uploads</Text>
      {lastUpload ? <UploadResult response={lastUpload} /> : null}
      {uploads.length ? (
        uploads.slice(-8).reverse().map((upload, index) => (
          <UploadRow key={`${upload.sha256 ?? upload.stored_name ?? index}`} upload={upload} />
        ))
      ) : (
        <Text color="yellow">No uploads recorded.</Text>
      )}
      {uploads.length > 8 ? <Text color="gray">+{uploads.length - 8} older uploads</Text> : null}
    </Box>
  );
}

function UploadResult({ response }: { response: UploadResponse }) {
  const metadata = response.result?.metadata ?? {};
  return (
    <Box flexDirection="column" marginBottom={1}>
      <Text color="green">{response.filename} uploaded</Text>
      <Text color="gray">
        size {response.size_bytes} bytes; id {shortId(metadata.sha256)}; untrusted yes; chunks{" "}
        {String(response.result?.chunks_written ?? 0)}
      </Text>
    </Box>
  );
}

function UploadRow({ upload }: { upload: UploadMetadata }) {
  return (
    <Box flexDirection="column" marginBottom={1}>
      <Text>
        {upload.original_name ?? upload.stored_name ?? "<upload>"}{" "}
        <Text color={upload.status === "stored" || upload.status === "stored_metadata_only" ? "green" : "yellow"}>
          {upload.status ?? "unknown"}
        </Text>
      </Text>
      <Text color="gray">
        size {String(upload.size_bytes ?? "-")} bytes; suffix {upload.suffix ?? "-"}; id {shortId(upload.sha256)};
        untrusted yes{upload.memory_note_created === false ? "; metadata only" : ""}
      </Text>
      {upload.error ? <Text color="red">{upload.error}</Text> : null}
    </Box>
  );
}

function shortId(value: unknown): string {
  if (typeof value !== "string" || !value) {
    return "-";
  }
  return value.slice(0, 12);
}
