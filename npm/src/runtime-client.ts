import readline from "node:readline";
import type { ChildProcessWithoutNullStreams } from "node:child_process";

import { parseRuntimeProtocolLine, type RuntimeProtocolEvent, type RuntimeRequest } from "./protocol";

type PythonRunner = {
  spawnPythonModule(moduleName: string, args?: string[]): ChildProcessWithoutNullStreams;
};

const pythonRunner = require("./python-runner") as PythonRunner;

export type RuntimeClient = {
  cancel(): void;
};

export type RuntimeClientEvent =
  | RuntimeProtocolEvent
  | { type: "client_stderr"; text: string }
  | { type: "client_failed"; message: string };

export function runRuntimeGoal(
  goal: string,
  onEvent: (event: RuntimeClientEvent) => void,
  options: { maxIterations?: number } = {},
): RuntimeClient {
  const child = pythonRunner.spawnPythonModule("kagent.cli.stdio_runtime", []);
  let finished = false;

  const stdout = readline.createInterface({ input: child.stdout });
  stdout.on("line", (line) => {
    try {
      const event = parseRuntimeProtocolLine(line);
      if (event) {
        onEvent(event);
        if (event.type === "run_completed" || event.type === "run_failed") {
          finished = true;
        }
      }
    } catch (error) {
      onEvent({ type: "client_failed", message: errorMessage(error) });
    }
  });

  child.stderr.on("data", (chunk: Buffer) => {
    onEvent({ type: "client_stderr", text: chunk.toString("utf8") });
  });
  child.on("error", (error) => {
    onEvent({ type: "client_failed", message: error.message });
  });
  child.on("close", (code) => {
    if (!finished && code !== 0) {
      onEvent({ type: "client_failed", message: `runtime exited with code ${code ?? 1}` });
    }
  });

  const request: RuntimeRequest = {
    type: "run_request",
    goal,
    max_iterations: options.maxIterations ?? 3,
  };
  child.stdin.write(`${JSON.stringify(request)}\n`);
  child.stdin.end();

  return {
    cancel() {
      if (!child.killed) {
        child.kill("SIGTERM");
      }
    },
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
