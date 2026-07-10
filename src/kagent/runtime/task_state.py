from __future__ import annotations

from typing import Dict

TASK_STATES = ("pending", "in_progress", "blocked", "done", "failed", "cancelled")
TASK_EVENTS = ("start", "block", "resume", "complete", "fail", "cancel", "reopen")


class TaskStateMachine:
    _TRANSITIONS = {
        ("pending", "start"): "in_progress",
        ("pending", "fail"): "failed",
        ("pending", "cancel"): "cancelled",
        ("in_progress", "block"): "blocked",
        ("in_progress", "complete"): "done",
        ("in_progress", "fail"): "failed",
        ("in_progress", "cancel"): "cancelled",
        ("blocked", "resume"): "in_progress",
        ("blocked", "fail"): "failed",
        ("blocked", "cancel"): "cancelled",
        ("done", "reopen"): "in_progress",
        ("failed", "reopen"): "pending",
        ("cancelled", "reopen"): "pending",
    }

    def transition(self, state: str, event: str) -> Dict[str, str]:
        normalized_state = str(state).strip()
        normalized_event = str(event).strip()
        if normalized_state not in TASK_STATES:
            raise ValueError("unknown task state")
        if normalized_event not in TASK_EVENTS:
            raise ValueError("unknown task event")
        next_state = self._TRANSITIONS.get((normalized_state, normalized_event))
        if next_state is None:
            raise ValueError("invalid task transition")
        return {
            "previous_state": normalized_state,
            "event": normalized_event,
            "state": next_state,
        }
