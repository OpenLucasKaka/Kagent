from __future__ import annotations

import json
import sys
import warnings
from typing import Any, Dict, Iterable, TextIO

from kagent.cli.provider import RuntimeProviderConfigError, runtime_provider_config_message
from kagent.providers.llm import FakeLLMProvider, LLMProviderConfig, build_llm_provider
from kagent.runtime import run_runtime_agent
from kagent.utils.json_output import json_ready

Request = Dict[str, Any]
DEFAULT_RUNTIME_MAX_ITERATIONS = 3


def main() -> None:
    warnings.filterwarnings("ignore")
    run_stdio_runtime(sys.stdin, sys.stdout)


def run_stdio_runtime(stdin: TextIO, stdout: TextIO) -> None:
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = _parse_request(line)
        except ValueError as exc:
            _emit(
                stdout,
                {
                    "type": "run_failed",
                    "error_code": "invalid_json",
                    "message": str(exc),
                },
            )
            continue
        _handle_request(request, stdout)


def _parse_request(line: str) -> Request:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON request: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValueError("request must be a JSON object")
    return payload


def _handle_request(request: Request, stdout: TextIO) -> None:
    request_type = str(request.get("type", ""))
    if request_type != "run_request":
        _emit(
            stdout,
            {
                "type": "run_failed",
                "error_code": "invalid_request_type",
                "message": "request type must be run_request",
            },
        )
        return

    goal = str(request.get("goal", "")).strip()
    if not goal:
        _emit(
            stdout,
            {
                "type": "run_failed",
                "error_code": "missing_goal",
                "message": "goal is required",
            },
        )
        return

    try:
        max_iterations = _positive_int(
            request.get("max_iterations"),
            default=DEFAULT_RUNTIME_MAX_ITERATIONS,
        )
    except (TypeError, ValueError) as exc:
        _emit(
            stdout,
            {
                "type": "run_failed",
                "error_code": "invalid_request",
                "message": str(exc),
            },
        )
        return
    _emit(
        stdout,
        {
            "type": "run_started",
            "goal": goal,
            "max_iterations": str(max_iterations),
        },
    )

    try:
        provider = _provider_from_request(request)
        result = run_runtime_agent(
            goal,
            provider=provider,
            max_iterations=max_iterations,
            event_sink=lambda event: _emit(stdout, {"type": "run_progress", "event": event}),
        )
        _emit(
            stdout,
            {
                "type": "run_completed",
                "status": str(result.get("status", "done")),
                "answer": str(result.get("answer", "")),
                "payload": result,
            },
        )
    except RuntimeProviderConfigError as exc:
        _emit(
            stdout,
            {
                "type": "run_failed",
                "error_code": "provider_not_configured",
                "message": str(exc),
            },
        )
    except Exception as exc:  # pragma: no cover - defensive protocol boundary
        _emit(
            stdout,
            {
                "type": "run_failed",
                "error_code": "runtime_error",
                "message": str(exc),
            },
        )


def _provider_from_request(request: Request) -> Any:
    runtime_plan = str(request.get("runtime_plan", "")).strip()
    if runtime_plan:
        return FakeLLMProvider(runtime_plan)
    config = LLMProviderConfig.from_sources()
    missing = _missing_provider_fields(config)
    if missing:
        raise RuntimeProviderConfigError(runtime_provider_config_message(missing))
    return build_llm_provider(config)


def _missing_provider_fields(config: LLMProviderConfig) -> list[str]:
    missing = []
    if not config.base_url:
        missing.append("KAGENT_LLM_BASE_URL")
    if not config.model:
        missing.append("KAGENT_LLM_MODEL")
    return missing


def _positive_int(value: Any, *, default: int) -> int:
    if value in (None, ""):
        return default
    parsed = int(value)
    if parsed < 1:
        raise ValueError("max_iterations must be at least 1")
    return parsed


def _emit(stdout: TextIO, payload: Dict[str, Any]) -> None:
    stdout.write(json.dumps(json_ready(payload), ensure_ascii=False, sort_keys=True) + "\n")
    stdout.flush()


__all__: Iterable[str] = ["run_stdio_runtime", "main"]


if __name__ == "__main__":
    main()
