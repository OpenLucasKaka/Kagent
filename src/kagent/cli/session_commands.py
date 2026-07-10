from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from difflib import get_close_matches
from typing import Any

from kagent.cli.commands import runtime_interactive_commands
from kagent.cli.conversation import compact_runtime_conversation_memory
from kagent.cli.memory import (
    RuntimeSessionMemory,
    clear_runtime_history,
    default_runtime_history_path,
    save_runtime_session_memory,
)
from kagent.providers.llm import (
    LLMProviderConfig,
    missing_provider_config_fields,
    provider_display_name,
)
from kagent.runtime.tools import registered_runtime_tool_metadata

_SUPPORTED_COMMANDS = {
    "/help",
    "/pwd",
    "/cd",
    "/status",
    "/config",
    "/tools",
    "/memory",
    "/compact-memory",
    "/clear",
    "/reset",
}

_ACTION_GROUPS = (
    (
        "Workspace files",
        {"apply_patch", "list_files", "read_file"},
        "Read, browse, create, and update files in the active workspace.",
    ),
    (
        "Documents and planning",
        {"artifact", "decision_matrix", "rubric_score", "task_list", "task_transition"},
        "Create deliverables, compare options, score results, and track tasks.",
    ),
    (
        "Browser and applications",
        {"open_app", "open_url"},
        "Open approved websites and local macOS applications.",
    ),
    (
        "External web requests",
        {"http_request"},
        "Fetch public web content after approval.",
    ),
    (
        "Shell commands",
        {"shell_command"},
        "Run bounded non-interactive commands after approval.",
    ),
    (
        "Skills and delegation",
        {"delegate_task", "skill_get", "skill_list"},
        "Use installed skills and delegate bounded subtasks.",
    ),
    (
        "Connected memory",
        {
            "memory_get",
            "memory_put",
            "memory_recall",
            "memory_remember",
            "memory_search",
            "memory_upsert",
        },
        "Read and write configured short-term or semantic memory stores.",
    ),
    (
        "Runtime workspace",
        {
            "workspace_diff",
            "workspace_history",
            "workspace_list",
            "workspace_read",
            "workspace_search",
            "workspace_write",
        },
        "Manage versioned runtime assets, reports, logs, and policies.",
    ),
)


@dataclass(frozen=True)
class SessionCommandResult:
    command: str
    title: str
    message: str
    data: dict[str, Any]
    clear_messages: bool = False

    def event(self) -> dict[str, Any]:
        return {
            "type": "session_command_completed",
            "command": self.command,
            "title": self.title,
            "message": self.message,
            "data": self.data,
            "clear_messages": self.clear_messages,
        }


class SessionCommandError(ValueError):
    def __init__(self, error_code: str, message: str, *, command: str = "") -> None:
        super().__init__(message)
        self.error_code = error_code
        self.command = command


def execute_session_command(
    raw_command: str,
    *,
    memory: RuntimeSessionMemory,
    memory_path: str,
    provider_config: LLMProviderConfig,
    last_payload: dict[str, Any] | None = None,
    history_path: str = "",
) -> SessionCommandResult:
    command = str(raw_command).strip()
    if not command:
        raise SessionCommandError("missing_command", "command is required")
    command_name = command.split(maxsplit=1)[0].lower()
    canonical = _canonical_command(command_name)
    if not canonical:
        suggestions = _command_suggestions(command_name)
        detail = f" Try {', '.join(suggestions)}." if suggestions else " Try /help."
        raise SessionCommandError(
            "unknown_command",
            f"Unknown command: {command_name}.{detail}",
            command=command_name,
        )

    if canonical == "/help":
        return _help_result(canonical)
    if canonical == "/pwd":
        cwd = os.getcwd()
        return SessionCommandResult(canonical, "Working directory", cwd, {"cwd": cwd})
    if canonical == "/cd":
        return _change_directory(command, canonical)
    if canonical == "/status":
        return _status_result(canonical, memory, provider_config, last_payload)
    if canonical == "/config":
        return _config_result(canonical, provider_config)
    if canonical == "/tools":
        return _tools_result(canonical)
    if canonical == "/memory":
        return _memory_result(canonical, memory)
    if canonical == "/compact-memory":
        compacted_now = compact_runtime_conversation_memory(memory)
        save_runtime_session_memory(memory_path, memory)
        detail = (
            f"Compacted {compacted_now} remembered turn"
            f"{'s' if compacted_now != 1 else ''}."
            if compacted_now
            else "Memory is already compact."
        )
        return SessionCommandResult(
            canonical,
            "Memory compacted",
            detail,
            _memory_snapshot(memory),
        )
    if canonical == "/clear":
        memory.clear()
        save_runtime_session_memory(memory_path, memory)
        return SessionCommandResult(
            canonical,
            "Memory cleared",
            "Remembered context was cleared.",
            {},
        )
    if canonical == "/reset":
        memory.clear()
        save_runtime_session_memory(memory_path, memory)
        clear_runtime_history(history_path or default_runtime_history_path())
        return SessionCommandResult(
            canonical,
            "Session reset",
            "Conversation memory and prompt history were cleared.",
            {},
            clear_messages=True,
        )
    raise AssertionError(f"unhandled session command: {canonical}")


def redacted_provider_snapshot(config: LLMProviderConfig) -> dict[str, Any]:
    configured = not missing_provider_config_fields(config)
    return {
        "configured": configured,
        "provider": config.provider.value if configured else "unconfigured",
        "display_name": provider_display_name(config.provider) if configured else "Unconfigured",
        "base_url_configured": bool(config.base_url),
        "model": config.model,
        "api_key_configured": bool(config.api_key),
    }


def runtime_session_command_catalog() -> list[dict[str, Any]]:
    return [
        {
            "command": command.primary,
            "description": command.description,
            "aliases": list(command.aliases),
        }
        for command in runtime_interactive_commands()
        if command.primary.split()[0] in _SUPPORTED_COMMANDS
    ]


def _canonical_command(command_name: str) -> str:
    for command in runtime_interactive_commands():
        primary = command.primary.split()[0]
        if primary not in _SUPPORTED_COMMANDS:
            continue
        if command_name == primary or command_name in command.aliases:
            return primary
    return ""


def _command_suggestions(command_name: str) -> list[str]:
    names = []
    for command in runtime_interactive_commands():
        primary = command.primary.split()[0]
        if primary in _SUPPORTED_COMMANDS:
            names.extend((primary, *command.aliases))
    return get_close_matches(command_name, names, n=3, cutoff=0.55)


def _help_result(command_name: str) -> SessionCommandResult:
    commands = [
        command
        for command in runtime_interactive_commands()
        if command.primary.split()[0] in _SUPPORTED_COMMANDS
    ]
    width = max(len(command.primary) for command in commands)
    lines = [f"{command.primary.ljust(width)}  {command.description}" for command in commands]
    data = {
        "commands": [
            {"command": command.primary, "description": command.description}
            for command in commands
        ]
    }
    return SessionCommandResult(command_name, "Commands", "\n".join(lines), data)


def _change_directory(raw_command: str, command_name: str) -> SessionCommandResult:
    try:
        parts = shlex.split(raw_command)
    except ValueError as exc:
        raise SessionCommandError("invalid_command", str(exc), command=command_name) from exc
    target_text = " ".join(parts[1:]).strip() or "~"
    target = os.path.abspath(os.path.expanduser(target_text))
    if not os.path.isdir(target):
        raise SessionCommandError(
            "directory_not_found",
            f"Directory not found: {target}",
            command=command_name,
        )
    try:
        os.chdir(target)
    except OSError as exc:
        raise SessionCommandError(
            "directory_unavailable",
            f"Cannot use directory: {exc}",
            command=command_name,
        ) from exc
    cwd = os.getcwd()
    return SessionCommandResult(command_name, "Working directory", cwd, {"cwd": cwd})


def _status_result(
    command_name: str,
    memory: RuntimeSessionMemory,
    provider_config: LLMProviderConfig,
    last_payload: dict[str, Any] | None,
) -> SessionCommandResult:
    provider = redacted_provider_snapshot(provider_config)
    memory_snapshot = _memory_snapshot(memory)
    last_status = str((last_payload or {}).get("status", "")).strip() or "none"
    lines = [
        f"Directory  {os.getcwd()}",
        f"Provider   {provider['display_name']}",
        f"Model      {provider['model'] or '-'}",
        f"Memory     {memory_snapshot['recent_turns']} recent, "
        f"{memory_snapshot['compacted_turns']} compacted",
        f"Last run   {last_status}",
    ]
    return SessionCommandResult(
        command_name,
        "Session",
        "\n".join(lines),
        {
            "cwd": os.getcwd(),
            "provider": provider,
            "memory": memory_snapshot,
            "last_status": last_status,
        },
    )


def _config_result(
    command_name: str,
    provider_config: LLMProviderConfig,
) -> SessionCommandResult:
    provider = {
        **redacted_provider_snapshot(provider_config),
        "timeout_seconds": provider_config.timeout_seconds,
        "max_retries": provider_config.max_retries,
        "retry_backoff_seconds": provider_config.retry_backoff_seconds,
    }
    lines = [
        f"Provider   {provider['display_name']}",
        f"Model      {provider['model'] or '-'}",
        f"Endpoint   {'configured' if provider['base_url_configured'] else 'not configured'}",
        f"API key    {'configured' if provider['api_key_configured'] else 'not configured'}",
        f"Timeout    {provider['timeout_seconds']}s",
        f"Retries    {provider['max_retries']}",
    ]
    return SessionCommandResult(command_name, "Provider", "\n".join(lines), provider)


def _tools_result(command_name: str) -> SessionCommandResult:
    metadata = registered_runtime_tool_metadata()
    by_name = {str(item.get("name", "")): item for item in metadata}
    capabilities = []
    for label, names, description in _ACTION_GROUPS:
        available = [by_name[name] for name in names if name in by_name]
        if not available:
            continue
        approval = any(
            str(item.get("approval_required_by_default", "")).lower() == "true"
            for item in available
        )
        capabilities.append(
            {
                "label": label,
                "access": "approval required" if approval else "available",
                "description": description,
            }
        )
    width = max(len(item["label"]) for item in capabilities)
    lines = [
        f"{item['label'].ljust(width)}  {item['access']}"
        for item in capabilities
    ]
    return SessionCommandResult(
        command_name,
        "Capabilities",
        "\n".join(lines),
        {"capabilities": capabilities},
    )


def _memory_result(command_name: str, memory: RuntimeSessionMemory) -> SessionCommandResult:
    snapshot = _memory_snapshot(memory)
    if not memory:
        return SessionCommandResult(command_name, "Memory", "Memory is empty.", snapshot)
    lines = []
    if memory.summary:
        lines.extend(("Summary", memory.summary))
    if memory.facts:
        lines.append("Facts")
        lines.extend(f"- {fact}" for fact in memory.facts)
    if memory.open_items:
        lines.append("Open items")
        lines.extend(f"- {item}" for item in memory.open_items)
    if memory.turns:
        lines.append("Recent turns")
        for turn in memory.turns:
            lines.append(f"You: {turn.get('user', '')}")
            if turn.get("assistant"):
                lines.append(f"kagent: {turn['assistant']}")
    return SessionCommandResult(command_name, "Memory", "\n".join(lines), snapshot)


def _memory_snapshot(memory: RuntimeSessionMemory) -> dict[str, int]:
    return {
        "recent_turns": len(memory.turns),
        "compacted_turns": memory.compacted_turn_count,
        "facts": len(memory.facts),
        "open_items": len(memory.open_items),
    }


__all__ = [
    "SessionCommandError",
    "SessionCommandResult",
    "execute_session_command",
    "redacted_provider_snapshot",
]
