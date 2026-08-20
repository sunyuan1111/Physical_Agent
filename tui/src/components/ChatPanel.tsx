import React from "react";
import { Box, Text } from "ink";
import Spinner from "ink-spinner";
import { normalizeTerminalText } from "./textFormat.js";
interface ChatPanelProps {
  hasTranscript: boolean;
  streamingText?: string;
  streaming?: boolean;
  error?: string | null;
}

export function ChatPanel({ hasTranscript, streamingText = "", streaming = false, error }: ChatPanelProps) {
  return (
    <Box flexDirection="column" paddingX={1}>
      <Box gap={1}>
        <Text color="gray">chat</Text>
        {streaming ? <Text color="yellow"><Spinner type="dots" /> streaming</Text> : null}
      </Box>
      {!hasTranscript && !streamingText ? <Text color="gray">No chat yet. Type a message or /help.</Text> : null}
      {streamingText ? (
        <Text>
          <Text color="cyan">assistant </Text>
          {normalizeTerminalText(streamingText)}
        </Text>
      ) : null}
      {error ? <Text color="red">{error}</Text> : null}
    </Box>
  );
}
