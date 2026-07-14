"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.createRuntimeActivityState = createRuntimeActivityState;
exports.reduceRuntimeActivity = reduceRuntimeActivity;
exports.toggleRuntimeActivity = toggleRuntimeActivity;
const MAX_TIMELINE_RECORDS = 6;
function createRuntimeActivityState() {
    return {
        phase: "",
        detail: "",
        latestOutcome: "",
        completedCount: 0,
        timeline: [],
        expanded: false,
    };
}
function reduceRuntimeActivity(state, event) {
    const type = safeString(event.type);
    if (type === "planner_started") {
        return applyActivity(state, "Planning next steps");
    }
    if (type === "planner_completed") {
        return applyActivity(state, "Plan ready", "", 1);
    }
    if (type === "tool_started") {
        const presentation = activityPresentation(event.presentation);
        return applyActivity(state, presentation.title || "Working on the next step", presentation.detail);
    }
    if (type === "tool_completed") {
        const presentation = activityPresentation(event.presentation);
        const title = presentation.title || "Reviewing latest result";
        return applyActivity(state, title, presentation.detail, 1, formatOutcome(title, presentation.detail));
    }
    if (type === "answer_started") {
        return applyActivity(state, "Writing the response");
    }
    if (type === "steering_applied") {
        return applyActivity(state, "Updating direction");
    }
    if (type === "approval_required") {
        return applyActivity(state, "Waiting for your decision", joinDetail(safeString(event.title), safeString(event.target)));
    }
    return state;
}
function toggleRuntimeActivity(state) {
    return { ...state, expanded: !state.expanded };
}
function applyActivity(state, phase, detail = "", completedIncrement = 0, latestOutcome = state.latestOutcome) {
    const record = { title: phase, detail };
    return {
        ...state,
        phase,
        detail,
        latestOutcome,
        completedCount: state.completedCount + completedIncrement,
        timeline: state.timeline.concat(record).slice(-MAX_TIMELINE_RECORDS),
    };
}
function activityPresentation(value) {
    if (!isRecord(value)) {
        return { title: "", detail: "" };
    }
    return {
        title: safeString(value.title),
        detail: safeString(value.detail),
    };
}
function isRecord(value) {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}
function safeString(value) {
    return typeof value === "string" ? value.trim() : "";
}
function formatOutcome(title, detail) {
    return detail ? `${title} · ${detail}` : title;
}
function joinDetail(title, target) {
    return [title, target].filter(Boolean).join(" · ");
}
