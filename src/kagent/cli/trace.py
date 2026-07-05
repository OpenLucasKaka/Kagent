from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from kagent.service.safety import safe_trace_file_stem
from kagent.utils.json_output import json_ready


def persist_runtime_cli_trace(
    result: dict,
    trace_dir: str,
    persist_trace: Any,
) -> None:
    result["trace_path"] = str(
        Path(trace_dir) / f"{safe_trace_file_stem(result.get('run_id'))}.json"
    )
    persist_trace(result, trace_dir)


def persist_runtime_cli_trace_or_raise(
    result: dict,
    trace_dir: str,
    persist_trace: Any,
) -> None:
    try:
        persist_runtime_cli_trace(result, trace_dir, persist_trace)
    except OSError as exc:
        raise ValueError(f"could not persist --trace-dir trace: {exc}") from exc


def save_runtime_trace_snapshot_or_raise(payload: Any, output_path: str) -> str:
    target = Path(output_path).expanduser()
    if not target.is_absolute():
        target = Path.cwd() / target
    if target.exists() and target.is_dir():
        raise ValueError("trace output path must be a file")
    if target.is_symlink():
        raise ValueError("trace output path must not be a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(json_ready(payload), ensure_ascii=False, indent=2, sort_keys=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(data)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.chmod(0o600)
        temporary_path.replace(target)
        target.chmod(0o600)
    except Exception:
        if fd != -1:
            os.close(fd)
        temporary_path.unlink(missing_ok=True)
        raise
    return str(target)
