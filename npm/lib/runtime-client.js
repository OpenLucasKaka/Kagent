"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.runRuntimeGoal = runRuntimeGoal;
const node_readline_1 = __importDefault(require("node:readline"));
const protocol_1 = require("./protocol");
const pythonRunner = require("./python-runner");
function runRuntimeGoal(goal, onEvent, options = {}) {
    const child = pythonRunner.spawnPythonModule("kagent.cli.stdio_runtime", []);
    let finished = false;
    const stdout = node_readline_1.default.createInterface({ input: child.stdout });
    stdout.on("line", (line) => {
        try {
            const event = (0, protocol_1.parseRuntimeProtocolLine)(line);
            if (event) {
                onEvent(event);
                if (event.type === "run_completed" || event.type === "run_failed") {
                    finished = true;
                }
            }
        }
        catch (error) {
            onEvent({ type: "client_failed", message: errorMessage(error) });
        }
    });
    child.stderr.on("data", (chunk) => {
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
    const request = {
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
function errorMessage(error) {
    return error instanceof Error ? error.message : String(error);
}
