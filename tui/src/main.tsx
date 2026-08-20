#!/usr/bin/env node
import React from "react";
import { render } from "ink";
import { App } from "./App.js";
import { helpText, parseArgs } from "./cli/args.js";

try {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    console.log(helpText());
  } else {
    render(
      <App
        apiBase={options.apiBase}
        pollIntervalMs={options.pollIntervalMs}
        useSse={options.sse}
      />
    );
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
}
