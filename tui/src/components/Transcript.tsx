import React from "react";
import { Box, Static, Text } from "ink";
import type { TranscriptEntry } from "../types.js";
import { normalizeTerminalText } from "./textFormat.js";

interface TranscriptProps {
  entries: TranscriptEntry[];
}

export function Transcript({ entries }: TranscriptProps) {
  return (
    <Static items={entries}>
      {(entry) => (
        <Box key={entry.id} paddingX={1}>
          <Text>
            <Text color={roleColor(entry.role)}>{rolePrefix(entry.role)} </Text>
            {normalizeTerminalText(entry.content)}
          </Text>
        </Box>
      )}
    </Static>
  );
}

function rolePrefix(role: string): string {
  if (role === "user") {
    return ">";
  }
  if (role === "assistant") {
    return "assistant";
  }
  return role;
}

function roleColor(role: string): "cyan" | "green" | "gray" {
  if (role === "assistant") {
    return "cyan";
  }
  if (role === "user") {
    return "green";
  }
  return "gray";
}
