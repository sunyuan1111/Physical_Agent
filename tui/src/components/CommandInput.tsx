import React from "react";
import { Box, Text } from "ink";
import TextInput from "ink-text-input";

interface CommandInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (value: string) => void;
  disabled?: boolean;
}

export function CommandInput({ value, onChange, onSubmit, disabled = false }: CommandInputProps) {
  return (
    <Box paddingX={1}>
      <Text color="green">&gt; </Text>
      <TextInput
        value={value}
        onChange={onChange}
        onSubmit={onSubmit}
        placeholder={disabled ? "Working..." : "message or /help"}
      />
    </Box>
  );
}
