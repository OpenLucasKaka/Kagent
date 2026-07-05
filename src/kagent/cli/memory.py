from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

from kagent.utils.json_output import json_ready

SESSION_MEMORY_SCHEMA_VERSION = "1"
SESSION_MEMORY_ENV_VAR = "KAGENT_SESSION_MEMORY_PATH"
HISTORY_ENV_VAR = "KAGENT_HISTORY_PATH"
_API_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9:_-]{8,}\b")
_BEARER_TOKEN_PATTERN = re.compile(
    r"\b(Authorization:\s*Bearer\s+|Bearer\s+)([A-Za-z0-9._~+/:-]{8,})",
    re.IGNORECASE,
)
_URL_CREDENTIAL_PATTERN = re.compile(r"\b(https?://)([^/\s:@]+):([^/\s@]+)@")


def default_runtime_session_memory_path(
    env: Mapping[str, str] | None = None,
) -> str:
    source = os.environ if env is None else env
    if SESSION_MEMORY_ENV_VAR in source:
        return source[SESSION_MEMORY_ENV_VAR]
    state_home = source.get("XDG_STATE_HOME", "").strip()
    if state_home:
        return str(Path(state_home) / "kagent" / "session-memory.json")
    home = source.get("HOME", "").strip()
    if not home:
        return ""
    return str(Path(home) / ".local" / "state" / "kagent" / "session-memory.json")


def default_runtime_history_path(
    env: Mapping[str, str] | None = None,
) -> str:
    source = os.environ if env is None else env
    if HISTORY_ENV_VAR in source:
        return source[HISTORY_ENV_VAR]
    state_home = source.get("XDG_STATE_HOME", "").strip()
    if state_home:
        return str(Path(state_home) / "kagent" / "history")
    home = source.get("HOME", "").strip()
    if not home:
        return ""
    return str(Path(home) / ".local" / "state" / "kagent" / "history")


def runtime_prompt_history(path: str):
    if not path:
        return None
    try:
        from prompt_toolkit.history import FileHistory
    except ImportError:
        return None

    history_path = Path(path)
    _prepare_owner_only_history_file(history_path)

    class _RedactingFileHistory(FileHistory):
        def store_string(self, string: str) -> None:
            super().store_string(redact_runtime_session_memory_text(string))

        def load_history_strings(self):
            for item in super().load_history_strings():
                yield redact_runtime_session_memory_text(item)

    return _RedactingFileHistory(str(history_path))


def clear_runtime_history(path: str) -> None:
    if not path:
        return
    history_path = Path(path)
    _prepare_owner_only_history_file(history_path)
    with history_path.open("w", encoding="utf-8") as handle:
        handle.write("")
    history_path.chmod(0o600)


def _prepare_owner_only_history_file(path: Path) -> None:
    _reject_symlink_memory_file(path)
    _reject_symlink_memory_path_parts(path)
    _ensure_owner_only_memory_dir(path.parent)
    if path.exists():
        _require_owner_only_memory_file(path)
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    os.close(fd)
    path.chmod(0o600)


def load_runtime_session_memory(path: str, *, max_turns: int) -> list[dict[str, str]]:
    if not path:
        return []
    memory_path = Path(path)
    try:
        _reject_symlink_memory_file(memory_path)
        _reject_symlink_memory_path_parts(memory_path)
        _tighten_existing_owner_only_memory_dir(memory_path.parent)
        _require_owner_only_memory_file(memory_path)
        payload = json.loads(memory_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    if not isinstance(payload, dict):
        raise ValueError("session memory file must contain a JSON object")
    turns = payload.get("turns")
    if not isinstance(turns, list):
        raise ValueError("session memory file must contain a turns array")
    return _normalize_session_memory_turns(turns, max_turns=max_turns)


def save_runtime_session_memory(path: str, turns: list[dict[str, str]]) -> None:
    if not path:
        return
    memory_path = Path(path)
    _reject_symlink_memory_file(memory_path)
    _reject_symlink_memory_path_parts(memory_path)
    output_dir = memory_path.parent
    _ensure_owner_only_memory_dir(output_dir)
    payload = {
        "schema_version": SESSION_MEMORY_SCHEMA_VERSION,
        "turns": json_ready(_redact_session_memory_turns(turns)),
    }
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{memory_path.name}.",
        suffix=".tmp",
        dir=output_dir,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.chmod(0o600)
        temporary_path.replace(memory_path)
        memory_path.chmod(0o600)
    except Exception:
        if fd != -1:
            os.close(fd)
        temporary_path.unlink(missing_ok=True)
        raise


def _normalize_session_memory_turns(
    turns: list[Any],
    *,
    max_turns: int,
) -> list[dict[str, str]]:
    normalized = []
    for item in turns:
        if not isinstance(item, dict):
            continue
        user = _redact_session_memory_text(str(item.get("user", "")).strip())
        assistant = _redact_session_memory_text(str(item.get("assistant", "")).strip())
        if not user and not assistant:
            continue
        normalized.append({"user": user, "assistant": assistant})
    return normalized[-max_turns:]


def _redact_session_memory_turns(turns: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "user": _redact_session_memory_text(str(turn.get("user", ""))),
            "assistant": _redact_session_memory_text(str(turn.get("assistant", ""))),
        }
        for turn in turns
        if str(turn.get("user", "")).strip() or str(turn.get("assistant", "")).strip()
    ]


def _redact_session_memory_text(text: str) -> str:
    return redact_runtime_session_memory_text(text)


def redact_runtime_session_memory_text(text: str) -> str:
    redacted = _API_KEY_PATTERN.sub("[REDACTED_API_KEY]", text)
    redacted = _BEARER_TOKEN_PATTERN.sub(r"\1[REDACTED_TOKEN]", redacted)
    return _URL_CREDENTIAL_PATTERN.sub(r"\1[REDACTED_CREDENTIALS]@", redacted)


def _require_owner_only_memory_file(path: Path) -> None:
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise ValueError("session memory file must be owner-only (0600)")


def _reject_symlink_memory_file(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("session memory file must not be a symlink")


def _ensure_owner_only_memory_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)


def _tighten_existing_owner_only_memory_dir(path: Path) -> None:
    if path.exists():
        path.chmod(0o700)


def _reject_symlink_memory_path_parts(path: Path) -> None:
    current = Path(path.anchor) if path.is_absolute() else Path(".")
    parts = path.parent.parts[1:] if path.parent.is_absolute() else path.parent.parts
    for part in parts:
        current = current / part
        if current.exists() and current.is_symlink() and not _is_platform_path_alias(current):
            raise ValueError("session memory path must not contain symlinks")


def _is_platform_path_alias(path: Path) -> bool:
    return str(path) in {"/tmp", "/var"}
