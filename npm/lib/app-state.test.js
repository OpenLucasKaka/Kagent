"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const strict_1 = __importDefault(require("node:assert/strict"));
const node_test_1 = __importDefault(require("node:test"));
const app_state_1 = require("./app-state");
(0, node_test_1.default)("does not render failed run completion as Done", () => {
    const state = (0, app_state_1.appRuntimeReducer)((0, app_state_1.createAppRuntimeState)(), {
        type: "runtime_event",
        channel: "run",
        event: {
            type: "run_completed",
            status: "failed",
            answer: "",
            payload: {
                error: "final_answer is required when actions is empty",
            },
        },
    });
    strict_1.default.equal(state.status, "error");
    strict_1.default.deepEqual(state.transcript.entries.map((entry) => [entry.role, entry.text]), [["system", "final_answer is required when actions is empty"]]);
});
(0, node_test_1.default)("tracks active run lifecycle and clears activity on terminal events", () => {
    let state = (0, app_state_1.createAppRuntimeState)();
    strict_1.default.equal(state.activity, null);
    state = (0, app_state_1.appRuntimeReducer)(state, { type: "submit", text: "Plan a trip", command: false });
    strict_1.default.equal(state.activity?.phase, "Preparing your request");
    state = (0, app_state_1.appRuntimeReducer)(state, {
        type: "runtime_event",
        channel: "run",
        event: { type: "run_started", goal: "Plan a trip", max_iterations: "5" },
    });
    strict_1.default.equal(state.activity?.phase, "Planning next steps");
    state = (0, app_state_1.appRuntimeReducer)(state, {
        type: "runtime_event",
        channel: "run",
        event: {
            type: "run_progress",
            event: {
                type: "tool_completed",
                presentation: { title: "Checked weather", detail: "Three cities" },
            },
        },
    });
    strict_1.default.equal(state.activity?.latestOutcome, "Checked weather · Three cities");
    strict_1.default.equal(state.transcript.entries.at(-1)?.title, "Checked weather");
    state = (0, app_state_1.appRuntimeReducer)(state, {
        type: "runtime_event",
        channel: "run",
        event: {
            type: "approval_required",
            action_id: "approve-1",
            title: "Book flight",
            reason: "This charges your card",
            target: "Shanghai → Tokyo",
        },
    });
    strict_1.default.equal(state.activity?.phase, "Waiting for your decision");
    strict_1.default.equal(state.activity?.detail, "Book flight · Shanghai → Tokyo");
    state = (0, app_state_1.appRuntimeReducer)(state, { type: "approval_response", approved: true });
    strict_1.default.equal(state.activity?.phase, "Continuing");
    state = (0, app_state_1.appRuntimeReducer)(state, { type: "cancel_requested", label: "Stopping" });
    strict_1.default.equal(state.activity?.phase, "Stopping");
    state = (0, app_state_1.appRuntimeReducer)(state, {
        type: "runtime_event",
        channel: "run",
        event: { type: "run_completed", status: "done", answer: "Done", payload: {} },
    });
    strict_1.default.equal(state.activity, null);
    state = (0, app_state_1.appRuntimeReducer)(state, { type: "submit", text: "Again", command: false });
    state = (0, app_state_1.appRuntimeReducer)(state, { type: "error", message: "Disconnected" });
    strict_1.default.equal(state.activity, null);
});
(0, node_test_1.default)("clears activity for each failed run terminal event", () => {
    const activeState = () => (0, app_state_1.appRuntimeReducer)((0, app_state_1.createAppRuntimeState)(), {
        type: "submit",
        text: "Do work",
        command: false,
    });
    const failed = (0, app_state_1.appRuntimeReducer)(activeState(), {
        type: "runtime_event",
        channel: "run",
        event: { type: "run_failed", error_code: "failed", message: "Failed" },
    });
    strict_1.default.equal(failed.activity, null);
    const clientFailed = (0, app_state_1.appRuntimeReducer)(activeState(), {
        type: "runtime_event",
        channel: "run",
        event: { type: "client_failed", message: "Disconnected" },
    });
    strict_1.default.equal(clientFailed.activity, null);
    const invalidCompletion = (0, app_state_1.appRuntimeReducer)(activeState(), {
        type: "runtime_event",
        channel: "run",
        event: { type: "run_completed", status: "failed", answer: "", payload: {} },
    });
    strict_1.default.equal(invalidCompletion.activity, null);
});
(0, node_test_1.default)("clears stale run state when the runtime session becomes ready", () => {
    let state = (0, app_state_1.appRuntimeReducer)((0, app_state_1.createAppRuntimeState)(), {
        type: "submit",
        text: "Book a flight",
        command: false,
    });
    state = (0, app_state_1.appRuntimeReducer)(state, {
        type: "runtime_event",
        channel: "run",
        event: {
            type: "approval_required",
            action_id: "approve-1",
            title: "Book flight",
            reason: "This charges your card",
            target: "Shanghai → Tokyo",
        },
    });
    state = (0, app_state_1.appRuntimeReducer)(state, {
        type: "runtime_event",
        channel: "lifecycle",
        event: {
            type: "runtime_ready",
            provider: {
                configured: true,
                provider: "test",
                display_name: "Test",
                base_url_configured: true,
                model: "model",
                api_key_configured: true,
            },
            provider_options: [],
            session_commands: [],
        },
    });
    strict_1.default.equal(state.activity, null);
    strict_1.default.equal(state.approval, null);
    strict_1.default.equal(state.status, "idle");
});
