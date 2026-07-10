"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.parseRuntimeProtocolLine = parseRuntimeProtocolLine;
function parseRuntimeProtocolLine(line) {
    const trimmed = line.trim();
    if (!trimmed) {
        return null;
    }
    const payload = JSON.parse(trimmed);
    if (!payload || typeof payload !== "object" || typeof payload.type !== "string") {
        throw new Error("runtime event must include a type");
    }
    return payload;
}
