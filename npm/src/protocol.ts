export type RuntimeRequest = {
  type: "run_request";
  goal: string;
  max_iterations?: number;
  runtime_plan?: string;
};

export type RunStartedEvent = {
  type: "run_started";
  goal: string;
  max_iterations: string;
};

export type RunProgressEvent = {
  type: "run_progress";
  event: Record<string, unknown>;
};

export type RunCompletedEvent = {
  type: "run_completed";
  status: string;
  answer: string;
  payload: Record<string, unknown>;
};

export type RunFailedEvent = {
  type: "run_failed";
  error_code: string;
  message: string;
};

export type RuntimeProtocolEvent =
  | RunStartedEvent
  | RunProgressEvent
  | RunCompletedEvent
  | RunFailedEvent;

export function parseRuntimeProtocolLine(line: string): RuntimeProtocolEvent | null {
  const trimmed = line.trim();
  if (!trimmed) {
    return null;
  }
  const payload = JSON.parse(trimmed) as RuntimeProtocolEvent;
  if (!payload || typeof payload !== "object" || typeof payload.type !== "string") {
    throw new Error("runtime event must include a type");
  }
  return payload;
}
