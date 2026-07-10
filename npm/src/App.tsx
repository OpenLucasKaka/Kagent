import type ReactNamespace from "react";

import { runRuntimeGoal, type RuntimeClient, type RuntimeClientEvent } from "./runtime-client";

type InkApi = {
  Box: ReactNamespace.ElementType;
  Text: ReactNamespace.ElementType;
  useApp: () => { exit: () => void };
  useInput: (handler: (input: string, key: Record<string, boolean | undefined>) => void) => void;
};

type AppProps = {
  React: typeof ReactNamespace;
  Ink: InkApi;
  runtimeClientFactory?: typeof runRuntimeGoal;
};

type Message = {
  role: "user" | "assistant" | "system";
  text: string;
};

const FRAMES = ["∙  ", "∙∙ ", "∙∙∙", " ∙∙", "  ∙"];

export function KagentInkApp({
  React,
  Ink,
  runtimeClientFactory = runRuntimeGoal,
}: AppProps): ReactNamespace.ReactElement {
  const { Box, Text } = Ink;
  const app = Ink.useApp();
  const [input, setInput] = React.useState("");
  const [cursor, setCursor] = React.useState(0);
  const [messages, setMessages] = React.useState<Message[]>([]);
  const [status, setStatus] = React.useState<"idle" | "thinking" | "done" | "error">("idle");
  const [statusText, setStatusText] = React.useState("ready");
  const [frame, setFrame] = React.useState(0);
  const runtimeRef = React.useRef<RuntimeClient | null>(null);

  React.useEffect(() => {
    if (status !== "thinking") {
      return undefined;
    }
    const timer = setInterval(() => {
      setFrame((current) => (current + 1) % FRAMES.length);
    }, 140);
    return () => clearInterval(timer);
  }, [React, status]);

  Ink.useInput((value, key) => {
    if (key.ctrl && value === "c") {
      if (runtimeRef.current) {
        runtimeRef.current.cancel();
        runtimeRef.current = null;
        setStatus("idle");
        setStatusText("cancelled");
        return;
      }
      app.exit();
      return;
    }
    if (status === "thinking") {
      return;
    }
    if (key.return) {
      submit();
      return;
    }
    if (key.backspace || key.delete) {
      if (cursor > 0) {
        setInput((current) => current.slice(0, cursor - 1) + current.slice(cursor));
        setCursor((current) => Math.max(0, current - 1));
      }
      return;
    }
    if (key.leftArrow) {
      setCursor((current) => Math.max(0, current - 1));
      return;
    }
    if (key.rightArrow) {
      setCursor((current) => Math.min(input.length, current + 1));
      return;
    }
    if (value) {
      setInput((current) => current.slice(0, cursor) + value + current.slice(cursor));
      setCursor((current) => current + value.length);
    }
  });

  function submit(): void {
    const goal = input.trim();
    if (!goal) {
      return;
    }
    if (["exit", "quit", ":q"].includes(goal.toLowerCase())) {
      app.exit();
      return;
    }
    setMessages((current) => current.concat({ role: "user", text: goal }));
    setInput("");
    setCursor(0);
    setStatus("thinking");
    setStatusText("working");
    runtimeRef.current = runtimeClientFactory(goal, handleRuntimeEvent);
  }

  function handleRuntimeEvent(event: RuntimeClientEvent): void {
    if (event.type === "run_started") {
      setStatus("thinking");
      setStatusText("thinking");
      return;
    }
    if (event.type === "run_progress") {
      setStatusText(progressLabel(event.event));
      return;
    }
    if (event.type === "run_completed") {
      runtimeRef.current = null;
      setStatus(event.status === "done" ? "done" : "error");
      setStatusText(event.status === "done" ? "done" : event.status);
      setMessages((current) => current.concat({ role: "assistant", text: event.answer || "完成" }));
      return;
    }
    if (event.type === "run_failed" || event.type === "client_failed") {
      runtimeRef.current = null;
      setStatus("error");
      setStatusText("failed");
      setMessages((current) => current.concat({ role: "system", text: event.message }));
      return;
    }
    if (event.type === "client_stderr") {
      setStatusText(compactLine(event.text));
    }
  }

  return React.createElement(
    Box,
    { flexDirection: "column", paddingX: 1 },
    React.createElement(Header, { React, Box, Text }),
    React.createElement(MessageList, { React, Box, Text, messages }),
    React.createElement(StatusLine, { React, Text, frame, status, statusText }),
    React.createElement(PromptLine, { React, Box, Text, cursor, input, disabled: status === "thinking" }),
  );
}

function Header({ React, Box, Text }: RenderProps): ReactNamespace.ReactElement {
  return React.createElement(
    Box,
    { flexDirection: "column", marginBottom: 1 },
    React.createElement(Text, { bold: true, color: "cyan" }, "kagent"),
    React.createElement(Text, { color: "gray" }, "local agent runtime"),
  );
}

function MessageList({ React, Box, Text, messages }: RenderProps & { messages: Message[] }) {
  const recent = messages.slice(-8);
  return React.createElement(
    Box,
    { flexDirection: "column" },
    ...recent.map((message, index) => {
      const marker = message.role === "user" ? "›" : message.role === "assistant" ? "k" : "!";
      const color = message.role === "user" ? "cyan" : message.role === "assistant" ? "green" : "yellow";
      return React.createElement(
        Text,
        { key: `${message.role}-${index}`, color },
        `${marker} ${message.text}`,
      );
    }),
  );
}

function StatusLine({
  React,
  Text,
  frame,
  status,
  statusText,
}: StatusRenderProps & { frame: number; status: string; statusText: string }) {
  const color = status === "error" ? "red" : status === "thinking" ? "cyan" : "gray";
  const prefix = status === "thinking" ? FRAMES[frame] : "";
  return React.createElement(Text, { color }, `${prefix}${statusText}`);
}

function PromptLine({
  React,
  Box,
  Text,
  cursor,
  disabled,
  input,
}: RenderProps & { cursor: number; disabled: boolean; input: string }) {
  const before = input.slice(0, cursor);
  const active = input.slice(cursor, cursor + 1) || " ";
  const after = input.slice(cursor + 1);
  return React.createElement(
    Box,
    { marginTop: 1 },
    React.createElement(Text, { color: disabled ? "gray" : "cyan" }, "› "),
    input
      ? React.createElement(
          Text,
          null,
          before,
          React.createElement(Text, { inverse: !disabled }, active),
          after,
        )
      : React.createElement(Text, { color: "gray" }, disabled ? "working" : "ask kagent"),
  );
}

type RenderProps = {
  React: typeof ReactNamespace;
  Box: ReactNamespace.ElementType;
  Text: ReactNamespace.ElementType;
};

type StatusRenderProps = {
  React: typeof ReactNamespace;
  Text: ReactNamespace.ElementType;
};

function progressLabel(event: Record<string, unknown>): string {
  const type = String(event.type || "");
  if (type === "planner_started") {
    return "thinking";
  }
  if (type === "plan_ready") {
    return "planning done";
  }
  if (type === "tool_completed") {
    return "working";
  }
  if (type === "approval_required") {
    return "needs approval";
  }
  if (type === "run_completed") {
    return "done";
  }
  if (type.endsWith("failed")) {
    return "retrying";
  }
  return "working";
}

function compactLine(text: string): string {
  return text.replace(/\s+/g, " ").trim().slice(0, 100);
}
