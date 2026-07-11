from __future__ import annotations

from threading import Lock
from typing import Callable


class RuntimeSteeringBuffer:
    """Thread-safe latest-wins instruction slot for an active runtime run."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._instruction = ""
        self._revision = 0
        self._closed = False

    def submit(
        self,
        instruction: str,
        *,
        accepted: Callable[[dict[str, str]], None] | None = None,
    ) -> dict[str, str]:
        normalized = instruction.strip()
        if not normalized:
            raise ValueError("steering instruction is required")
        with self._lock:
            if self._closed:
                raise RuntimeError("active run is no longer accepting steering")
            replaced = bool(self._instruction)
            self._instruction = normalized
            self._revision += 1
            snapshot = {
                "revision": str(self._revision),
                "replaced": str(replaced).lower(),
            }
            if accepted is not None:
                accepted(snapshot)
            return snapshot

    def consume(self) -> tuple[str, str]:
        with self._lock:
            instruction = self._instruction
            if not instruction:
                return "", str(self._revision)
            self._instruction = ""
            return instruction, str(self._revision)

    def pending(self) -> bool:
        with self._lock:
            return bool(self._instruction)

    def close(self) -> tuple[str, str]:
        with self._lock:
            self._closed = True
            instruction = self._instruction
            self._instruction = ""
            return instruction, str(self._revision)
