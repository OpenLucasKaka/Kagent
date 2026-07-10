from __future__ import annotations

from datetime import datetime, timezone
from threading import Event, Lock
from typing import Dict


class RuntimeCancellationToken:
    """Thread-safe cooperative cancellation shared across runtime boundaries."""

    def __init__(self) -> None:
        self._event = Event()
        self._lock = Lock()
        self._reason = ""
        self._cancelled_at = ""

    def cancel(self, reason: str = "") -> bool:
        normalized_reason = reason.strip()
        with self._lock:
            if self._event.is_set():
                return False
            self._reason = normalized_reason
            self._cancelled_at = datetime.now(timezone.utc).isoformat()
            self._event.set()
            return True

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def snapshot(self) -> Dict[str, str]:
        with self._lock:
            return {
                "cancelled": str(self._event.is_set()).lower(),
                "reason": self._reason,
                "cancelled_at": self._cancelled_at,
            }

