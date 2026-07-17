import http.client
import json
import os
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import UUID

from kagent import __version__
from kagent.service import (
    ServiceConcurrencyLimiter,
    ServiceConfig,
    ServiceIdempotencyCache,
    ServiceMetrics,
    ServiceRateLimiter,
    access_log_record,
    create_server,
    handle_request,
    readiness_payload,
)
from kagent.service import cli as service_module
from kagent.service import router as service_router
from kagent.service import runtime_resume as service_runtime_resume
from kagent.service import runtime_run as service_runtime_run
from kagent.service.trace_store import persist_trace


def test_service_health_endpoint_reports_ok():
    status_code, payload = handle_request("GET", "/health", b"")

    assert status_code == 200
    assert payload == {"status": "ok"}


def test_service_readiness_payload_reports_dependency_checks():
    payload = readiness_payload()

    assert payload == {
        "status": "ready",
        "failed_checks": [],
        "checks": {
            "runtime_config": "ok",
            "openapi": "ok",
            "runtime_tools": "ok",
        },
    }


def test_service_readiness_payload_checks_configured_trace_dir(tmp_path):
    trace_dir = tmp_path / "traces"

    payload = readiness_payload(ServiceConfig(trace_dir=str(trace_dir)))

    assert payload["status"] == "ready"
    assert payload["checks"]["trace_persistence"] == "ok"
    assert trace_dir.exists()
    assert list(trace_dir.iterdir()) == []


def test_service_ready_endpoint_rejects_unusable_trace_dir(tmp_path):
    blocking_file = tmp_path / "not-a-directory"
    blocking_file.write_text("blocks trace directory creation")
    trace_dir = blocking_file / "traces"

    status_code, payload = handle_request(
        "GET",
        "/ready",
        b"",
        config=ServiceConfig(trace_dir=str(trace_dir)),
    )

    assert status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["error_code"] == "readiness_failed"
    assert payload["failed_checks"] == ["trace_persistence"]
    assert payload["checks"]["trace_persistence"] == "failed: trace_persistence_unavailable"
    assert str(blocking_file) not in json.dumps(payload)


def test_service_readiness_payload_is_fast_for_http_probes():
    started_at = time.perf_counter()

    payload = readiness_payload()

    assert payload["status"] == "ready"
    assert time.perf_counter() - started_at < 1.0


def test_service_ready_endpoint_reports_ready():
    status_code, payload = handle_request("GET", "/ready", b"")

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["checks"]["runtime_tools"] == "ok"


def test_service_config_endpoint_reports_redacted_runtime_config(monkeypatch, tmp_path):
    for key in list(os.environ):
        if key.startswith("KAGENT_LLM_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(
        "KAGENT_LLM_CONFIG_PATH",
        str(tmp_path / "missing-provider.json"),
    )

    status_code, payload = handle_request(
        "GET",
        "/config",
        b"",
        headers={"Authorization": "Bearer secret"},
        config=ServiceConfig(
            host="0.0.0.0",
            port=9000,
            max_request_bytes=2048,
            max_goal_chars=1234,
            auth_token="secret",
            rate_limit_per_minute=12,
            max_concurrent_runs=3,
            idempotency_cache_size=5,
            runtime_allowed_tools_by_subject={"team-a": ("note",)},
            runtime_pending_approval_stale_seconds=1800,
            runtime_instance_heartbeat_seconds=5.0,
            runtime_orphaned_run_stale_seconds=45.0,
            allow_full_trace_response=True,
            protect_diagnostics=True,
            trace_dir="/tmp/traces",
            run_timeout_seconds=7.5,
            request_timeout_seconds=4.5,
        ),
    )

    assert status_code == 200
    assert payload == {
        "host": "0.0.0.0",
        "port": "9000",
        "max_request_bytes": "2048",
        "max_goal_chars": "1234",
        "auth_required": "true",
        "auth_subject_count": "1",
        "rate_limit_per_minute": "12",
        "max_concurrent_runs": "3",
        "idempotency_cache_size": "5",
        "idempotency_cache_backend": "memory",
        "idempotency_cache_path_configured": "false",
        "runtime_allowed_tools": "default",
        "runtime_allowed_tools_by_subject_count": "1",
        "runtime_max_iterations": "10",
        "runtime_pending_approval_stale_seconds": "1800",
        "runtime_instance_heartbeat_seconds": "5.0",
        "runtime_orphaned_run_stale_seconds": "45.0",
        "allow_full_trace_response": "true",
        "protect_diagnostics": "true",
        "trust_forwarded_for": "false",
        "run_timeout_seconds": "7.5",
        "request_timeout_seconds": "4.5",
        "trace_persistence": "enabled",
        "runtime_workspace": "disabled",
        "runtime_workspace_kinds": "workspace,reports,logs,policies,memories",
        "redis_short_term_memory": "disabled",
        "milvus_long_term_memory": "disabled",
        "kafka_audit_sink": "disabled",
        "kafka_audit_topic_configured": "false",
        "external_backend_timeout_seconds": "2.0",
        "embedding_provider": "unconfigured",
        "embedding_base_url": "",
        "embedding_base_url_configured": "false",
        "embedding_model": "",
        "embedding_api_key_configured": "false",
        "embedding_timeout_seconds": "30.0",
        "embedding_max_retries": "2",
        "embedding_retry_backoff_seconds": "0.25",
        "trace_directory_permissions": "0700",
        "trace_file_permissions": "0600",
        "trace_probe_file_permissions": "0600",
        "llm_provider": "unconfigured",
        "llm_provider_display_name": "Unconfigured",
        "llm_base_url": "",
        "llm_base_url_configured": "false",
        "llm_model": "",
        "llm_api_key_configured": "false",
        "llm_timeout_seconds": "30.0",
        "llm_max_retries": "2",
        "llm_retry_backoff_seconds": "0.25",
        "security_response_headers": "enabled",
        "cache_control_header": "no-store",
        "content_security_policy_header": (
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        ),
        "referrer_policy_header": "no-referrer",
        "x_frame_options_header": "DENY",
        "x_content_type_options_header": "nosniff",
    }
    assert "secret" not in json.dumps(payload)


def test_service_version_endpoint_reports_package_version():
    status_code, payload = handle_request("GET", "/version", b"")

    assert status_code == 200
    assert payload == {"version": __version__}


def test_service_runtime_tools_endpoint_reports_tool_schemas():
    status_code, payload = handle_request("GET", "/runtime/tools", b"")
    by_name = {item["name"]: item for item in payload["tools"]}

    assert status_code == 200
    assert by_name["apply_patch"]["approval_required_by_default"] == "false"
    assert by_name["apply_patch"]["input_schema"]["required"] == ["patch"]
    assert by_name["apply_patch"]["output_schema"]["required"] == [
        "changed_files",
        "file_count",
    ]
    assert by_name["artifact"]["approval_required_by_default"] == "false"
    assert by_name["artifact"]["input_schema"]["required"] == [
        "title",
        "kind",
        "content",
    ]
    assert by_name["artifact"]["output_schema"]["required"] == [
        "artifact_id",
        "title",
        "kind",
        "format",
        "content",
        "tags",
        "bytes",
    ]
    assert by_name["decision_matrix"]["input_schema"]["required"] == [
        "question",
        "criteria",
        "options",
    ]
    assert by_name["decision_matrix"]["output_schema"]["required"] == [
        "question",
        "criteria",
        "rankings",
        "winner",
    ]
    assert by_name["http_request"]["approval_required_by_default"] == "true"
    assert by_name["http_request"]["input_schema"]["required"] == ["url"]
    assert by_name["http_request"]["output_schema"]["required"] == [
        "url",
        "status_code",
        "content_type",
        "body_text",
        "bytes",
        "truncated",
    ]
    assert by_name["list_files"]["approval_required_by_default"] == "false"
    assert by_name["list_files"]["output_schema"]["required"] == [
        "root",
        "entries",
        "file_count",
        "truncated",
    ]
    assert by_name["note"]["input_schema"]["required"] == ["text"]
    assert by_name["note"]["output_schema"]["required"] == ["text"]
    assert by_name["open_app"]["approval_required_by_default"] == "true"
    assert by_name["open_app"]["input_schema"]["required"] == ["application"]
    assert by_name["open_app"]["output_schema"]["required"] == [
        "application",
        "opened",
        "command",
    ]
    assert by_name["open_url"]["approval_required_by_default"] == "true"
    assert by_name["open_url"]["input_schema"]["required"] == ["url"]
    assert by_name["open_url"]["output_schema"]["required"] == [
        "url",
        "opened",
        "application",
        "command",
    ]
    assert by_name["read_file"]["approval_required_by_default"] == "false"
    assert by_name["read_file"]["input_schema"]["required"] == ["path"]
    assert by_name["read_file"]["output_schema"]["required"] == [
        "path",
        "content",
        "bytes",
        "truncated",
        "sha256",
    ]
    assert by_name["rubric_score"]["input_schema"]["required"] == ["criteria"]
    assert by_name["rubric_score"]["output_schema"]["required"] == [
        "criteria",
        "passed",
        "failed",
        "total",
        "score_percent",
        "blocking_failures",
        "failed_criteria",
    ]
    assert by_name["task_list"]["input_schema"]["required"] == ["items"]
    assert by_name["task_list"]["output_schema"]["required"] == [
        "items",
        "counts",
        "total",
    ]
    assert by_name["transform_text"]["output_schema"]["required"] == ["text"]


def test_service_runtime_graph_endpoint_reports_topology():
    status_code, payload = handle_request("GET", "/runtime/graph", b"")

    assert status_code == 200
    assert payload["runtime_engine"] == "langgraph"
    assert payload["entry_point"] == "prepare"
    assert payload["nodes"] == [
        "prepare",
        "planner",
        "prepare_action",
        "mark_action_executing",
        "execute_action",
        "runtime_loop",
        "finalize",
    ]
    assert payload["edges"] == [
        "prepare -> planner",
        "planner -> prepare_action | runtime_loop",
        "prepare_action -> mark_action_executing | runtime_loop",
        "mark_action_executing -> execute_action | runtime_loop",
        "execute_action -> runtime_loop",
        "runtime_loop -> finalize",
        "finalize -> END",
    ]


def test_service_metrics_normalizes_runtime_run_status_paths_over_http(tmp_path):
    server = create_server(
        "127.0.0.1",
        0,
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        run = _open_json(
            f"http://{host}:{port}/runtime/run",
            data=json.dumps(
                {
                    "goal": "write launch plan",
                    "plan": {
                        "actions": [
                            {
                                "id": "step-1",
                                "tool": "artifact",
                                "input": {
                                    "title": "Launch plan",
                                    "kind": "plan",
                                    "content": "# Ship\nDo the rollout.",
                                },
                            }
                        ]
                    },
                }
            ).encode("utf-8"),
        )
        artifact_id = run["observations"][0]["output"]["artifact_id"]
        _open_json(f"http://{host}:{port}/runtime/runs/{run['run_id']}")
        _open_json(f"http://{host}:{port}/runtime/runs/{run['run_id']}/timeline")
        _open_json(f"http://{host}:{port}/runtime/runs/{run['run_id']}/artifacts")
        _open_json(
            f"http://{host}:{port}/runtime/runs/{run['run_id']}/artifacts/{artifact_id}"
        )
        _open_json(
            f"http://{host}:{port}/runtime/runs/{run['run_id']}/cancel",
            data=b"{}",
        )
        _open_json(f"http://{host}:{port}/runtime/approvals")
        _open_json(f"http://{host}:{port}/runtime/approvals/summary")
        _open_json(f"http://{host}:{port}/runtime/policy")
        _open_json(f"http://{host}:{port}/runtime/runs")
        _open_json(f"http://{host}:{port}/runtime/runs/summary")
        metrics = _open_json(f"http://{host}:{port}/metrics")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert metrics["requests_by_path"]["/runtime/run"] == "1"
    assert metrics["requests_by_path"]["/runtime/approvals"] == "1"
    assert metrics["requests_by_path"]["/runtime/approvals/summary"] == "1"
    assert metrics["requests_by_path"]["/runtime/policy"] == "1"
    assert metrics["requests_by_path"]["/runtime/runs"] == "1"
    assert metrics["requests_by_path"]["/runtime/runs/summary"] == "1"
    assert metrics["requests_by_path"]["/runtime/runs/{run_id}"] == "1"
    assert metrics["requests_by_path"]["/runtime/runs/{run_id}/timeline"] == "1"
    assert metrics["requests_by_path"]["/runtime/runs/{run_id}/artifacts"] == "1"
    assert (
        metrics["requests_by_path"]["/runtime/runs/{run_id}/artifacts/{artifact_id}"]
        == "1"
    )
    assert metrics["requests_by_path"]["/runtime/runs/{run_id}/cancel"] == "1"


def test_service_streams_runtime_run_answer_deltas_over_http():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        request = urllib.request.Request(
            f"http://{host}:{port}/runtime/run/stream",
            data=json.dumps(
                {
                    "goal": "打个招呼",
                    "plan": {
                        "actions": [],
                        "final_answer": "你好卡卡",
                    },
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            content_type = response.headers["Content-Type"]
            body = response.read().decode("utf-8")
        metrics = _open_json(f"http://{host}:{port}/metrics")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert content_type == "text/event-stream"
    events = _parse_sse_events(body)
    assert [event["event"] for event in events] == [
        "run_started",
        "progress",
        "progress",
        "answer_delta",
        "progress",
        "progress",
        "progress",
        "final",
    ]
    assert [event["data"].get("delta") for event in events] == [
        None,
        None,
        None,
        "你好卡卡",
        None,
        None,
        None,
        None,
    ]
    final_payload = events[-1]["data"]
    assert final_payload["status"] == "done"
    assert final_payload["answer"] == "你好卡卡"
    assert final_payload["answer_streamed"] == "true"
    assert metrics["requests_by_path"]["/runtime/run/stream"] == "1"


def test_service_flushes_runtime_stream_answer_delta_before_final(monkeypatch):
    class SlowStreamingProvider:
        def stream_complete(self, _system, _user):
            yield '{"actions":[],"final_answer":"hel'
            time.sleep(1.0)
            yield 'lo"}'

    monkeypatch.setattr(
        service_runtime_run.LLMProviderConfig,
        "from_sources",
        staticmethod(lambda: object()),
    )
    monkeypatch.setattr(
        service_runtime_run,
        "OpenAICompatibleProvider",
        lambda _config: SlowStreamingProvider(),
    )
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    body = json.dumps({"goal": "stream slowly"}).encode("utf-8")
    connection = http.client.HTTPConnection(host, port, timeout=5)

    try:
        started_at = time.perf_counter()
        connection.request(
            "POST",
            "/runtime/run/stream",
            body=body,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            },
        )
        response = connection.getresponse()
        first_answer_delta = None
        final_event = None
        while final_event is None:
            event = _read_sse_event(response)
            if event["event"] == "answer_delta" and first_answer_delta is None:
                first_answer_delta = event
                first_delta_elapsed = time.perf_counter() - started_at
            if event["event"] == "final":
                final_event = event
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert response.status == 200
    assert response.getheader("Content-Type") == "text/event-stream"
    assert first_answer_delta["data"]["delta"] == "hel"
    assert first_delta_elapsed < 0.8
    assert final_event["data"]["answer"] == "hello"


def test_service_metrics_tracks_agent_run_duration_histogram_buckets():
    metrics = ServiceMetrics(started_at=10.0)
    metrics.record_agent_run(status="done", duration_seconds=0.2)
    metrics.record_agent_run(status="timeout", duration_seconds=3.0)

    snapshot = metrics.snapshot(now=12.0)

    assert snapshot["agent_run_duration_seconds_bucket"] == {
        "0.05": "0",
        "0.1": "0",
        "0.25": "1",
        "0.5": "1",
        "1": "1",
        "2.5": "1",
        "5": "2",
        "10": "2",
        "+Inf": "2",
    }
    assert snapshot["agent_run_duration_seconds_count"] == "2"
    assert snapshot["agent_run_duration_seconds_sum"] == "3.2000"


def test_service_metrics_tracks_runtime_operational_counters():
    metrics = ServiceMetrics(started_at=10.0)

    metrics.record_runtime_run(
        status="requires_approval",
        failed_observation_count=0,
        approval_required_count=1,
        budget_exhausted=False,
        duration_seconds=0.2,
        auth_subject="team-a",
        progress_event_sink_failure_count=1,
        hook_failure_count=1,
        llm_provider_request={
            "attempt_count": "1",
            "retry_count": "0",
            "status": "ok",
            "stream": "false",
            "duration_seconds": "0.2000",
        },
    )
    metrics.record_runtime_run(
        status="failed",
        failed_observation_count=2,
        approval_required_count=0,
        budget_exhausted=True,
        duration_seconds=3.0,
        auth_subject="team-a",
        resumed_by_auth_subject="default",
        approved_by_auth_subject="default",
        progress_event_sink_failure_count=2,
        hook_failure_count=2,
        error_code_counts={
            "invalid_tool_input": 1,
            "tool_execution_timeout": 1,
        },
        llm_provider_request={
            "attempt_count": "3",
            "retry_count": "2",
            "status": "failed",
            "stream": "false",
            "duration_seconds": "1.2000",
            "error_type": "http_error",
            "http_status": "429",
            "retryable_reason": "model_unloaded",
        },
    )
    metrics.record_runtime_run(
        status="done",
        failed_observation_count=0,
        approval_required_count=0,
        budget_exhausted=False,
        duration_seconds=0.4,
        auth_subject="ops",
    )

    snapshot = metrics.snapshot(now=12.0)

    assert snapshot["runtime_runs_total"] == "3"
    assert snapshot["runtime_runs_by_status"] == {
        "done": "1",
        "failed": "1",
        "requires_approval": "1",
    }
    assert snapshot["runtime_runs_by_lifecycle_state"] == {
        "failed": "1",
        "succeeded": "1",
        "waiting_approval": "1",
    }
    assert snapshot["runtime_runs_by_auth_subject"] == {
        "ops": "1",
        "team-a": "2",
    }
    assert snapshot["runtime_runs_by_auth_subject_status"] == {
        "ops:done": "1",
        "team-a:failed": "1",
        "team-a:requires_approval": "1",
    }
    assert snapshot["runtime_runs_by_auth_subject_lifecycle_state"] == {
        "ops:succeeded": "1",
        "team-a:failed": "1",
        "team-a:waiting_approval": "1",
    }
    assert snapshot["runtime_resumes_by_auth_subject"] == {"default": "1"}
    assert snapshot["runtime_approvals_by_auth_subject"] == {"default": "1"}
    assert snapshot["runtime_failed_observations_total"] == "2"
    assert snapshot["runtime_progress_event_sink_failures_total"] == "3"
    assert snapshot["runtime_hook_failures_total"] == "3"
    assert snapshot["runtime_observation_errors_by_code"] == {
        "invalid_tool_input": "1",
        "tool_execution_timeout": "1",
    }
    assert snapshot["runtime_llm_provider_requests_total"] == "2"
    assert snapshot["runtime_llm_provider_request_attempts_total"] == "4"
    assert snapshot["runtime_llm_provider_request_retries_total"] == "2"
    assert snapshot["runtime_llm_provider_requests_by_status"] == {
        "failed": "1",
        "ok": "1",
    }
    assert snapshot["runtime_llm_provider_request_errors_by_type"] == {
        "http_error": "1"
    }
    assert snapshot["runtime_llm_provider_request_http_status"] == {"429": "1"}
    assert snapshot["runtime_llm_provider_request_retryable_reason"] == {
        "model_unloaded": "1"
    }
    assert snapshot["runtime_llm_provider_request_duration_seconds_bucket"] == {
        "0.05": "0",
        "0.1": "0",
        "0.25": "1",
        "0.5": "1",
        "1": "1",
        "2.5": "2",
        "5": "2",
        "10": "2",
        "+Inf": "2",
    }
    assert snapshot["runtime_llm_provider_request_duration_seconds_count"] == "2"
    assert snapshot["runtime_llm_provider_request_duration_seconds_sum"] == "1.4000"
    assert snapshot["average_runtime_llm_provider_request_duration_seconds"] == "0.7000"
    assert snapshot["max_runtime_llm_provider_request_duration_seconds"] == "1.2000"
    assert snapshot["runtime_approval_required_total"] == "1"
    assert snapshot["runtime_failed_budget_exhaustions_total"] == "1"
    assert snapshot["runtime_run_duration_seconds_bucket"] == {
        "0.05": "0",
        "0.1": "0",
        "0.25": "1",
        "0.5": "2",
        "1": "2",
        "2.5": "2",
        "5": "3",
        "10": "3",
        "+Inf": "3",
    }
    assert snapshot["runtime_run_duration_seconds_count"] == "3"
    assert snapshot["runtime_run_duration_seconds_sum"] == "3.6000"
    assert snapshot["average_runtime_run_duration_seconds"] == "1.2000"
    assert snapshot["max_runtime_run_duration_seconds"] == "3.0000"


def test_service_metrics_tracks_runtime_reconciliation_outcomes():
    metrics = ServiceMetrics()
    metrics.record_runtime_reconciliation(
        {
            "scanned": 4,
            "recovered_running": 2,
            "completed_resumes": 1,
            "reopened_approvals": 1,
            "protected_live": 3,
            "skipped_unowned": 1,
            "skipped_locked": 2,
            "errors": ["invalid trace", "unreadable trace"],
        }
    )
    metrics.record_runtime_reconciliation(
        {"scanned": "2", "recovered_running": "1", "errors": 1},
        status="unavailable",
    )

    snapshot = metrics.snapshot()

    assert snapshot["runtime_reconciliation_runs_total"] == "2"
    assert snapshot["runtime_reconciliation_runs_by_status"] == {
        "ok": "1",
        "unavailable": "1",
    }
    assert snapshot["runtime_reconciliation_traces_scanned_total"] == "6"
    assert snapshot["runtime_reconciliation_outcomes"] == {
        "completed_resumes": "1",
        "protected_live": "3",
        "recovered_running": "3",
        "reopened_approvals": "1",
        "skipped_locked": "2",
        "skipped_unowned": "1",
    }
    assert snapshot["runtime_reconciliation_errors_total"] == "3"


def test_service_metrics_endpoint_reports_runtime_snapshot():
    metrics = ServiceMetrics()
    metrics.record(path="/health", status_code=200)

    status_code, payload = handle_request("GET", "/metrics", b"", metrics=metrics)

    assert status_code == 200
    assert payload["requests_total"] == "1"
    assert payload["responses_by_status"] == {"200": "1"}


def test_service_metrics_endpoint_reports_runtime_operational_outcomes():
    metrics = ServiceMetrics()

    approval_status, approval_payload = handle_request(
        "POST",
        "/runtime/run",
        (
            b'{"goal":"fetch safely","plan":{"actions":[{"id":"step-1",'
            b'"tool":"http_request","input":{"url":"https://example.com"},'
            b'"reason":"fetch"}]}}'
        ),
        metrics=metrics,
    )
    failed_status, failed_payload = handle_request(
        "POST",
        "/runtime/run",
        (
            b'{"goal":"normalize","max_iterations":1,'
            b'"plan":{"actions":[{"id":"step-1","tool":"transform_text",'
            b'"input":{"text":" hello ","mode":"squash"},"reason":"normalize"}]}}'
        ),
        metrics=metrics,
    )
    planner_failed_status, planner_failed_payload = handle_request(
        "POST",
        "/runtime/run",
        (
            b'{"goal":"bad plan","max_iterations":1,'
            b'"plan":{"actions":[{"id":"step-1","tool":"note",'
            b'"input":{"text":"hello"},"unexpected":"field"}]}}'
        ),
        metrics=metrics,
    )
    metrics_status, metrics_payload = handle_request("GET", "/metrics", b"", metrics=metrics)

    assert approval_status == 200
    assert approval_payload["status"] == "requires_approval"
    assert failed_status == 200
    assert failed_payload["status"] == "failed"
    assert failed_payload["iteration_budget_remaining"] == "0"
    assert planner_failed_status == 200
    assert planner_failed_payload["status"] == "failed"
    assert planner_failed_payload["error_code"] == "invalid_plan"
    assert metrics_status == 200
    assert metrics_payload["runtime_runs_total"] == "3"
    assert metrics_payload["runtime_runs_by_status"] == {
        "failed": "2",
        "requires_approval": "1",
    }
    assert metrics_payload["runtime_runs_by_lifecycle_state"] == {
        "failed": "2",
        "waiting_approval": "1",
    }
    assert metrics_payload["runtime_failed_observations_total"] == "2"
    assert metrics_payload["runtime_progress_event_sink_failures_total"] == "0"
    assert metrics_payload["runtime_observation_errors_by_code"] == {
        "invalid_plan": "1",
        "invalid_tool_input": "1",
        "tool_not_allowed": "1",
    }
    assert metrics_payload["runtime_tool_executions_by_tool_status"] == {
        "http_request:requires_approval": "1",
        "transform_text:failed": "1",
    }
    assert metrics_payload["runtime_planner_attempts_by_status"] == {
        "failed": "1",
        "ok": "2",
    }
    assert metrics_payload["runtime_planner_failures_total"] == "1"
    assert metrics_payload["runtime_planner_failures_by_error_code"] == {
        "invalid_plan": "1"
    }
    assert metrics_payload["runtime_approval_required_total"] == "1"
    assert metrics_payload["runtime_failed_budget_exhaustions_total"] == "2"
    assert metrics_payload["runtime_run_duration_seconds_count"] == "3"
    assert float(metrics_payload["runtime_run_duration_seconds_sum"]) > 0
    assert float(metrics_payload["max_runtime_run_duration_seconds"]) > 0


def test_service_metrics_endpoint_records_runtime_progress_sink_failures(monkeypatch):
    metrics = ServiceMetrics()

    def runtime_response(_body, _config, _auth_subject, **_kwargs):
        return 200, {
            "trace_type": "codex_runtime",
            "status": "done",
            "duration_seconds": "0.25",
            "observations": [],
            "progress_event_sink_failure_count": "4",
            "hook_failure_count": "5",
        }

    monkeypatch.setattr(
        service_router.service_runtime_run,
        "execute_runtime_run_request",
        runtime_response,
    )

    run_status, run_payload = handle_request(
        "POST",
        "/runtime/run",
        b'{"goal":"emit progress"}',
        metrics=metrics,
    )
    metrics_status, metrics_payload = handle_request("GET", "/metrics", b"", metrics=metrics)

    assert run_status == 200
    assert run_payload["progress_event_sink_failure_count"] == "4"
    assert run_payload["hook_failure_count"] == "5"
    assert metrics_status == 200
    assert metrics_payload["runtime_runs_total"] == "1"
    assert metrics_payload["runtime_progress_event_sink_failures_total"] == "4"
    assert metrics_payload["runtime_hook_failures_total"] == "5"


def test_service_metrics_endpoint_records_runtime_llm_provider_request(monkeypatch):
    metrics = ServiceMetrics()

    def runtime_response(_body, _config, _auth_subject, **_kwargs):
        return 200, {
            "trace_type": "codex_runtime",
            "status": "failed",
            "duration_seconds": "0.50",
            "iteration_budget_remaining": "0",
            "observations": [
                {
                    "tool": "planner",
                    "status": "failed",
                    "error_code": "llm_provider_error",
                    "output": {},
                }
            ],
            "events": [{"node": "planner", "status": "failed"}],
            "llm_provider_request": {
                "attempt_count": "3",
                "retry_count": "2",
                "status": "failed",
                "stream": "false",
                "duration_seconds": "1.2500",
                "error_type": "http_error",
                "http_status": "429",
                "retryable_reason": "model_unloaded",
                "api_key": "must-not-leak",
            },
        }

    monkeypatch.setattr(
        service_router.service_runtime_run,
        "execute_runtime_run_request",
        runtime_response,
    )

    run_status, run_payload = handle_request(
        "POST",
        "/runtime/run",
        b'{"goal":"provider fails"}',
        metrics=metrics,
    )
    metrics_status, metrics_payload = handle_request("GET", "/metrics", b"", metrics=metrics)

    assert run_status == 200
    assert run_payload["llm_provider_request"]["attempt_count"] == "3"
    assert metrics_status == 200
    assert metrics_payload["runtime_llm_provider_requests_total"] == "1"
    assert metrics_payload["runtime_llm_provider_request_attempts_total"] == "3"
    assert metrics_payload["runtime_llm_provider_request_retries_total"] == "2"
    assert metrics_payload["runtime_llm_provider_requests_by_status"] == {
        "failed": "1"
    }
    assert metrics_payload["runtime_llm_provider_request_errors_by_type"] == {
        "http_error": "1"
    }
    assert metrics_payload["runtime_llm_provider_request_http_status"] == {"429": "1"}
    assert metrics_payload["runtime_llm_provider_request_retryable_reason"] == {
        "model_unloaded": "1"
    }
    assert "must-not-leak" not in json.dumps(metrics_payload)


def test_service_metrics_endpoint_reports_current_runtime_approval_queue(tmp_path):
    old_trace_path = persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "old-pending",
            "status": "requires_approval",
            "goal": "old approval",
            "auth_subject": "team-a",
            "pending_approval": {"id": "old-step", "tool": "http_request"},
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "fresh-pending",
            "status": "requires_approval",
            "goal": "fresh approval",
            "auth_subject": "team-a",
            "pending_approval": {"id": "fresh-step", "tool": "note"},
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "done-run",
            "status": "done",
            "goal": "done",
        },
        str(tmp_path),
    )
    old_timestamp = time.time() - 7200
    os.utime(old_trace_path, (old_timestamp, old_timestamp))

    status_code, metrics_payload = handle_request(
        "GET",
        "/metrics",
        b"",
        config=ServiceConfig(
            trace_dir=str(tmp_path),
            runtime_pending_approval_stale_seconds=3600,
        ),
    )

    assert status_code == 200
    assert metrics_payload["runtime_pending_approvals_current"] == "2"
    assert metrics_payload["runtime_stale_pending_approvals_current"] == "1"
    assert int(metrics_payload["runtime_max_pending_approval_age_seconds"]) >= 3600
    assert metrics_payload["runtime_pending_approval_stale_seconds"] == "3600"


def test_service_metrics_endpoint_reports_concurrency_snapshot():
    limiter = ServiceConcurrencyLimiter(max_concurrent_runs=2)
    release = limiter.try_acquire()

    try:
        status_code, payload = handle_request(
            "GET",
            "/metrics",
            b"",
            concurrency_limiter=limiter,
        )
    finally:
        assert release is not None
        release()

    assert status_code == 200
    assert payload["active_concurrent_runs"] == "1"
    assert payload["max_concurrent_runs"] == "2"


def test_service_metrics_endpoint_reports_rate_limiter_snapshot():
    limiter = ServiceRateLimiter(limit_per_minute=2)
    limiter.allow("client-a")

    status_code, payload = handle_request("GET", "/metrics", b"", rate_limiter=limiter)

    assert status_code == 200
    assert payload["active_rate_limit_windows"] == "1"
    assert payload["rate_limit_per_minute"] == "2"


def test_service_prometheus_metrics_endpoint_reports_text_exposition(monkeypatch):
    monkeypatch.setenv("KAGENT_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("KAGENT_LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("KAGENT_LLM_MODEL", "agent-runtime-model")
    monkeypatch.setenv("KAGENT_LLM_API_KEY", "redactme")
    monkeypatch.setenv("KAGENT_LLM_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("KAGENT_LLM_MAX_RETRIES", "2")
    monkeypatch.setenv("KAGENT_LLM_RETRY_BACKOFF_SECONDS", "0.25")
    metrics = ServiceMetrics()
    metrics.record(
        method="GET",
        path="/health",
        status_code=200,
        duration_seconds=0.125,
        auth_subject="team-a",
    )
    metrics.record(
        method="POST",
        path='/quoted"path\\segment',
        status_code=404,
        duration_seconds=0.0,
        error_code="not_found",
    )
    metrics.record_agent_run(status="done", duration_seconds=0.25)
    metrics.record_runtime_run(
        status="requires_approval",
        failed_observation_count=0,
        approval_required_count=1,
        budget_exhausted=False,
        duration_seconds=0.4,
        auth_subject="team-a",
        resumed_by_auth_subject="default",
        approved_by_auth_subject="default",
        progress_event_sink_failure_count=1,
        hook_failure_count=1,
        tool_status_counts={"http_request:requires_approval": 1},
        planner_attempt_status_counts={"ok": 1},
        llm_provider_request={
            "attempt_count": "1",
            "retry_count": "0",
            "status": "ok",
            "stream": "false",
            "duration_seconds": "0.2000",
        },
    )
    metrics.record_runtime_run(
        status="failed",
        failed_observation_count=2,
        approval_required_count=0,
        budget_exhausted=True,
        duration_seconds=3.5,
        auth_subject="team-a",
        resumed_by_auth_subject="team-a",
        progress_event_sink_failure_count=2,
        hook_failure_count=2,
        error_code_counts={
            "invalid_tool_input": 1,
            "tool_execution_timeout": 1,
        },
        tool_status_counts={"transform_text:failed": 1},
        planner_attempt_status_counts={"failed": 1},
        planner_failure_count=1,
        planner_error_code_counts={"invalid_plan": 1},
        llm_provider_request={
            "attempt_count": "3",
            "retry_count": "2",
            "status": "failed",
            "stream": "false",
            "duration_seconds": "1.2000",
            "error_type": "http_error",
            "http_status": "429",
            "retryable_reason": "model_unloaded",
        },
    )
    metrics.record_runtime_reconciliation(
        {
            "scanned": 3,
            "recovered_running": 1,
            "reopened_approvals": 1,
            "protected_live": 1,
            "errors": ["invalid trace"],
        }
    )
    limiter = ServiceConcurrencyLimiter(max_concurrent_runs=2)
    idempotency_cache = ServiceIdempotencyCache(max_entries=5)
    release = limiter.try_acquire()

    try:
        status_code, payload = handle_request(
            "GET",
            "/metrics.prom",
            b"",
            config=ServiceConfig(
                host="0.0.0.0",
                port=9001,
                auth_token="secret",
                max_request_bytes=8192,
                rate_limit_per_minute=11,
                max_concurrent_runs=2,
                idempotency_cache_size=5,
                max_goal_chars=1234,
                allow_full_trace_response=True,
                protect_diagnostics=True,
                trust_forwarded_for=True,
                trace_dir="/var/lib/kagent/traces",
                run_timeout_seconds=6.5,
                request_timeout_seconds=4.5,
            ),
            headers={"Authorization": "Bearer secret"},
            metrics=metrics,
            concurrency_limiter=limiter,
            idempotency_cache=idempotency_cache,
        )
    finally:
        assert release is not None
        release()

    assert status_code == 200
    assert isinstance(payload, str)
    assert "# HELP kagent_responses_total" in payload
    assert "# TYPE kagent_responses_total counter" in payload
    assert "# HELP kagent_requests_by_method_total" in payload
    assert "# TYPE kagent_requests_by_method_total counter" in payload
    assert "# HELP kagent_requests_by_path_total" in payload
    assert "# TYPE kagent_requests_by_path_total counter" in payload
    assert "# HELP kagent_requests_by_auth_subject_total" in payload
    assert "# TYPE kagent_requests_by_auth_subject_total counter" in payload
    assert "# HELP kagent_error_responses_total" in payload
    assert "# TYPE kagent_error_responses_total counter" in payload
    assert "# HELP kagent_request_duration_seconds" in payload
    assert "# TYPE kagent_request_duration_seconds histogram" in payload
    assert "# HELP kagent_agent_run_duration_seconds" in payload
    assert "# TYPE kagent_agent_run_duration_seconds histogram" in payload
    assert "# HELP kagent_run_status_total" in payload
    assert "# TYPE kagent_run_status_total counter" in payload
    assert "# HELP kagent_runtime_runs_total" in payload
    assert "# TYPE kagent_runtime_runs_total counter" in payload
    assert "# HELP kagent_runtime_run_status_total" in payload
    assert "# TYPE kagent_runtime_run_status_total counter" in payload
    assert "# HELP kagent_runtime_runs_by_auth_subject_total" in payload
    assert "# TYPE kagent_runtime_runs_by_auth_subject_total counter" in payload
    assert "# HELP kagent_runtime_run_status_by_auth_subject_total" in payload
    assert (
        "# TYPE kagent_runtime_run_status_by_auth_subject_total counter"
        in payload
    )
    assert "# HELP kagent_runtime_resumes_by_auth_subject_total" in payload
    assert (
        "# TYPE kagent_runtime_resumes_by_auth_subject_total counter"
        in payload
    )
    assert "# HELP kagent_runtime_approvals_by_auth_subject_total" in payload
    assert (
        "# TYPE kagent_runtime_approvals_by_auth_subject_total counter"
        in payload
    )
    assert "# HELP kagent_runtime_observation_errors_total" in payload
    assert "# TYPE kagent_runtime_observation_errors_total counter" in payload
    assert "# HELP kagent_runtime_progress_event_sink_failures_total" in payload
    assert (
        "# TYPE kagent_runtime_progress_event_sink_failures_total counter"
        in payload
    )
    assert "# HELP kagent_runtime_hook_failures_total" in payload
    assert "# TYPE kagent_runtime_hook_failures_total counter" in payload
    assert "# HELP kagent_runtime_final_answer_guardrails_total" in payload
    assert "# TYPE kagent_runtime_final_answer_guardrails_total counter" in payload
    assert (
        "# HELP kagent_runtime_final_answer_guardrails_by_reason_total"
        in payload
    )
    assert (
        "# TYPE kagent_runtime_final_answer_guardrails_by_reason_total "
        "counter"
        in payload
    )
    assert "# HELP kagent_runtime_run_duration_seconds" in payload
    assert "# TYPE kagent_runtime_run_duration_seconds histogram" in payload
    assert "# HELP kagent_active_concurrent_runs" in payload
    assert "# TYPE kagent_active_concurrent_runs gauge" in payload
    assert "# HELP kagent_idempotency_cache_hits" in payload
    assert "# TYPE kagent_idempotency_cache_hits counter" in payload
    assert "# HELP kagent_idempotency_cache_claims" in payload
    assert "# TYPE kagent_idempotency_cache_claims counter" in payload
    assert "# HELP kagent_idempotency_cache_waits" in payload
    assert "# TYPE kagent_idempotency_cache_waits counter" in payload
    assert "# HELP kagent_idempotency_cache_wait_timeouts" in payload
    assert "# TYPE kagent_idempotency_cache_wait_timeouts counter" in payload
    assert "# HELP kagent_idempotency_cache_takeovers" in payload
    assert "# TYPE kagent_idempotency_cache_takeovers counter" in payload
    assert "kagent_requests_total 2" in payload
    assert 'kagent_responses_total{status="200"} 1' in payload
    assert 'kagent_error_responses_total{error_code="not_found"} 1' in payload
    assert 'kagent_requests_by_method_total{method="GET"} 1' in payload
    assert 'kagent_requests_by_method_total{method="POST"} 1' in payload
    assert 'kagent_requests_by_path_total{path="/health"} 1' in payload
    assert (
        'kagent_requests_by_auth_subject_total{auth_subject="team-a"} 1'
        in payload
    )
    assert (
        'kagent_requests_by_path_total{path="/quoted\\"path\\\\segment"} 1'
        in payload
    )
    assert 'kagent_request_duration_seconds_bucket{le="0.05"} 1' in payload
    assert 'kagent_request_duration_seconds_bucket{le="0.1"} 1' in payload
    assert 'kagent_request_duration_seconds_bucket{le="0.25"} 2' in payload
    assert 'kagent_request_duration_seconds_bucket{le="+Inf"} 2' in payload
    assert "kagent_request_duration_seconds_count 2" in payload
    assert "kagent_request_duration_seconds_sum 0.1250" in payload
    assert 'kagent_agent_run_duration_seconds_bucket{le="0.25"} 1' in payload
    assert 'kagent_agent_run_duration_seconds_bucket{le="+Inf"} 1' in payload
    assert "kagent_agent_run_duration_seconds_count 1" in payload
    assert "kagent_agent_run_duration_seconds_sum 0.2500" in payload
    assert "kagent_active_concurrent_runs 1" in payload
    assert "kagent_max_concurrent_runs 2" in payload
    assert "kagent_max_request_bytes 8192" in payload
    assert "kagent_average_duration_seconds 0.0625" in payload
    assert "kagent_max_duration_seconds 0.1250" in payload
    assert "kagent_runs_total 1" in payload
    assert 'kagent_run_status_total{status="done"} 1' in payload
    assert "kagent_runtime_runs_total 2" in payload
    assert (
        'kagent_runtime_run_status_total{status="requires_approval"} 1'
        in payload
    )
    assert 'kagent_runtime_run_status_total{status="failed"} 1' in payload
    assert (
        'kagent_runtime_run_lifecycle_state_total'
        '{lifecycle_state="waiting_approval"} 1'
        in payload
    )
    assert (
        'kagent_runtime_run_lifecycle_state_total{lifecycle_state="failed"} 1'
        in payload
    )
    assert (
        'kagent_runtime_runs_by_auth_subject_total'
        '{auth_subject="team-a"} 2'
        in payload
    )
    assert (
        'kagent_runtime_run_status_by_auth_subject_total'
        '{auth_subject="team-a",status="requires_approval"} 1'
        in payload
    )
    assert (
        'kagent_runtime_run_status_by_auth_subject_total'
        '{auth_subject="team-a",status="failed"} 1'
        in payload
    )
    assert (
        'kagent_runtime_run_lifecycle_state_by_auth_subject_total'
        '{auth_subject="team-a",lifecycle_state="waiting_approval"} 1'
        in payload
    )
    assert (
        'kagent_runtime_run_lifecycle_state_by_auth_subject_total'
        '{auth_subject="team-a",lifecycle_state="failed"} 1'
        in payload
    )
    assert (
        'kagent_runtime_resumes_by_auth_subject_total'
        '{auth_subject="default"} 1'
        in payload
    )
    assert (
        'kagent_runtime_resumes_by_auth_subject_total'
        '{auth_subject="team-a"} 1'
        in payload
    )
    assert (
        'kagent_runtime_approvals_by_auth_subject_total'
        '{auth_subject="default"} 1'
        in payload
    )
    assert "kagent_runtime_failed_observations_total 2" in payload
    assert (
        'kagent_runtime_observation_errors_total'
        '{error_code="invalid_tool_input"} 1'
        in payload
    )
    assert (
        'kagent_runtime_observation_errors_total'
        '{error_code="tool_execution_timeout"} 1'
        in payload
    )
    assert "# HELP kagent_runtime_tool_executions_total" in payload
    assert "# TYPE kagent_runtime_tool_executions_total counter" in payload
    assert (
        'kagent_runtime_tool_executions_total'
        '{tool="http_request",status="requires_approval"} 1'
        in payload
    )
    assert (
        'kagent_runtime_tool_executions_total'
        '{tool="transform_text",status="failed"} 1'
        in payload
    )
    assert "# HELP kagent_runtime_planner_attempts_total" in payload
    assert "# TYPE kagent_runtime_planner_attempts_total counter" in payload
    assert 'kagent_runtime_planner_attempts_total{status="ok"} 1' in payload
    assert 'kagent_runtime_planner_attempts_total{status="failed"} 1' in payload
    assert "# HELP kagent_runtime_planner_failures_total" in payload
    assert "# TYPE kagent_runtime_planner_failures_total counter" in payload
    assert "kagent_runtime_planner_failures_total 1" in payload
    assert "# HELP kagent_runtime_planner_failures_by_error_code_total" in payload
    assert "# TYPE kagent_runtime_planner_failures_by_error_code_total counter" in payload
    assert (
        'kagent_runtime_planner_failures_by_error_code_total'
        '{error_code="invalid_plan"} 1'
        in payload
    )
    assert "# HELP kagent_runtime_llm_provider_requests_total" in payload
    assert "# TYPE kagent_runtime_llm_provider_requests_total counter" in payload
    assert "kagent_runtime_llm_provider_requests_total 2" in payload
    assert "kagent_runtime_llm_provider_request_attempts_total 4" in payload
    assert "kagent_runtime_llm_provider_request_retries_total 2" in payload
    assert (
        'kagent_runtime_llm_provider_requests_by_status_total{status="ok"} 1'
        in payload
    )
    assert (
        'kagent_runtime_llm_provider_requests_by_status_total{status="failed"} 1'
        in payload
    )
    assert (
        'kagent_runtime_llm_provider_request_errors_by_type_total'
        '{error_type="http_error"} 1'
        in payload
    )
    assert (
        'kagent_runtime_llm_provider_request_http_status_total'
        '{http_status="429"} 1'
        in payload
    )
    assert (
        'kagent_runtime_llm_provider_request_retryable_reason_total'
        '{retryable_reason="model_unloaded"} 1'
        in payload
    )
    assert (
        'kagent_runtime_llm_provider_request_duration_seconds_bucket{le="0.25"} 1'
        in payload
    )
    assert (
        'kagent_runtime_llm_provider_request_duration_seconds_bucket{le="2.5"} 2'
        in payload
    )
    assert (
        "kagent_runtime_llm_provider_request_duration_seconds_count 2"
        in payload
    )
    assert (
        "kagent_runtime_llm_provider_request_duration_seconds_sum 1.4000"
        in payload
    )
    assert "kagent_runtime_approval_required_total 1" in payload
    assert "kagent_runtime_progress_event_sink_failures_total 3" in payload
    assert "kagent_runtime_hook_failures_total 3" in payload
    assert "# HELP kagent_runtime_reconciliation_runs_total" in payload
    assert "# TYPE kagent_runtime_reconciliation_runs_total counter" in payload
    assert 'kagent_runtime_reconciliation_runs_total{status="ok"} 1' in payload
    assert "kagent_runtime_reconciliation_traces_scanned_total 3" in payload
    assert (
        'kagent_runtime_reconciliation_outcomes_total'
        '{outcome="recovered_running"} 1'
        in payload
    )
    assert (
        'kagent_runtime_reconciliation_outcomes_total'
        '{outcome="reopened_approvals"} 1'
        in payload
    )
    assert "kagent_runtime_reconciliation_errors_total 1" in payload
    assert "kagent_runtime_final_answer_guardrails_total 0" in payload
    assert "kagent_runtime_pending_approvals_current 0" in payload
    assert "kagent_runtime_stale_pending_approvals_current 0" in payload
    assert "kagent_runtime_max_pending_approval_age_seconds 0" in payload
    assert "kagent_runtime_pending_approval_stale_seconds 3600" in payload
    assert "kagent_runtime_failed_budget_exhaustions_total 1" in payload
    assert 'kagent_runtime_run_duration_seconds_bucket{le="0.5"} 1' in payload
    assert 'kagent_runtime_run_duration_seconds_bucket{le="5"} 2' in payload
    assert 'kagent_runtime_run_duration_seconds_bucket{le="+Inf"} 2' in payload
    assert "kagent_runtime_run_duration_seconds_count 2" in payload
    assert "kagent_runtime_run_duration_seconds_sum 3.9000" in payload
    assert "kagent_average_agent_run_duration_seconds 0.2500" in payload
    assert "kagent_max_agent_run_duration_seconds 0.2500" in payload
    assert "kagent_uptime_seconds" in payload
    assert (
        'kagent_build_info{auth_required="true",'
        'auth_subject_count="1",allow_full_trace_response="true",'
        'bind_host="0.0.0.0",bind_port="9001",'
        'idempotency_cache_backend="memory",'
        'idempotency_cache_path_configured="false",'
        'idempotency_cache_size="5",runtime_allowed_tools="default",'
        'runtime_allowed_tools_by_subject_count="0",'
        'runtime_max_iterations="10",'
        'max_concurrent_runs="2",'
        'max_goal_chars="1234",max_request_bytes="8192",'
        'protect_diagnostics="true",'
        'rate_limit_per_minute="11",'
        'request_timeout_seconds="4.5",run_timeout_seconds="6.5",'
        'trace_persistence="enabled",trust_forwarded_for="true",version="'
        in payload
    )
    assert 'security_response_headers="enabled"' in payload
    assert 'embedding_provider="unconfigured"' in payload
    assert 'embedding_base_url=""' in payload
    assert 'embedding_base_url_configured="false"' in payload
    assert 'embedding_model=""' in payload
    assert 'embedding_api_key_configured="false"' in payload
    assert 'llm_provider="openai_compatible"' in payload
    assert 'llm_provider_display_name="OpenAI-compatible"' in payload
    assert 'llm_base_url="configured"' in payload
    assert 'llm_base_url_configured="true"' in payload
    assert "https://llm.example.test/v1" not in payload
    assert 'llm_model="agent-runtime-model"' in payload
    assert 'llm_api_key_configured="true"' in payload
    assert 'llm_timeout_seconds="12.5"' in payload
    assert 'llm_max_retries="2"' in payload
    assert 'llm_retry_backoff_seconds="0.25"' in payload
    assert "redactme" not in payload
    assert 'cache_control_header="no-store"' in payload
    assert (
        'content_security_policy_header="default-src \'none\'; '
        "frame-ancestors 'none'; base-uri 'none'\""
    ) in payload
    assert 'referrer_policy_header="no-referrer"' in payload
    assert 'trace_directory_permissions="0700"' in payload
    assert 'trace_file_permissions="0600"' in payload
    assert 'trace_probe_file_permissions="0600"' in payload
    assert 'x_frame_options_header="DENY"' in payload
    assert 'x_content_type_options_header="nosniff"' in payload
    assert "secret" not in payload
    assert payload.endswith("\n")


def test_service_config_loads_named_internal_bearer_tokens_from_env():
    config = ServiceConfig.from_env(
        {
            "KAGENT_SERVICE_AUTH_TOKENS": (
                '{"team-a":"team-a-token","ops":"ops-token"}'
            )
        }
    )

    assert config.auth_required is True
    assert config.auth_tokens == {
        "ops": "ops-token",
        "team-a": "team-a-token",
    }


def test_service_config_reads_environment_defaults():
    config = ServiceConfig.from_env(
        {
            "KAGENT_SERVICE_HOST": "0.0.0.0",
            "KAGENT_SERVICE_PORT": "9000",
            "KAGENT_SERVICE_AUTH_TOKEN": "secret",
            "KAGENT_SERVICE_MAX_REQUEST_BYTES": "2048",
            "KAGENT_SERVICE_MAX_GOAL_CHARS": "1234",
            "KAGENT_SERVICE_RATE_LIMIT_PER_MINUTE": "12",
            "KAGENT_SERVICE_MAX_CONCURRENT_RUNS": "3",
            "KAGENT_SERVICE_IDEMPOTENCY_CACHE_SIZE": "5",
            "KAGENT_SERVICE_IDEMPOTENCY_CACHE_PATH": "/tmp/agent-idempotency.sqlite3",
            "KAGENT_SERVICE_RUNTIME_ALLOWED_TOOLS": "note,artifact",
            "KAGENT_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT": (
                '{"team-a":"note,transform_text","ops":["artifact","note"]}'
            ),
            "KAGENT_SERVICE_RUNTIME_MAX_ITERATIONS": "17",
            "KAGENT_SERVICE_RUNTIME_PENDING_APPROVAL_STALE_SECONDS": "1800",
            "KAGENT_SERVICE_RUNTIME_INSTANCE_HEARTBEAT_SECONDS": "7.5",
            "KAGENT_SERVICE_RUNTIME_ORPHANED_RUN_STALE_SECONDS": "45",
            "KAGENT_SERVICE_ALLOW_FULL_TRACE_RESPONSE": "true",
            "KAGENT_SERVICE_PROTECT_DIAGNOSTICS": "true",
            "KAGENT_SERVICE_TRUST_FORWARDED_FOR": "true",
            "KAGENT_SERVICE_TRACE_DIR": "/tmp/agent-traces",
            "KAGENT_SERVICE_RUNTIME_WORKSPACE_DIR": "/tmp/agent-runtime-workspace",
            "KAGENT_REDIS_URL": "redis://localhost:6379/0",
            "KAGENT_MILVUS_URL": "http://milvus.internal/healthz",
            "KAGENT_EMBEDDING_BASE_URL": "https://embedding.example/v1",
            "KAGENT_EMBEDDING_API_KEY": "embedding-key",
            "KAGENT_EMBEDDING_MODEL": "text-embedding-model",
            "KAGENT_EMBEDDING_TIMEOUT_SECONDS": "6.5",
            "KAGENT_EMBEDDING_MAX_RETRIES": "4",
            "KAGENT_EMBEDDING_RETRY_BACKOFF_SECONDS": "0.75",
            "KAGENT_KAFKA_AUDIT_URL": "http://kafka-rest.internal/topics/audit",
            "KAGENT_KAFKA_AUDIT_TOPIC": "kagent-audit",
            "KAGENT_EXTERNAL_BACKEND_TIMEOUT_SECONDS": "1.5",
            "KAGENT_SERVICE_RUN_TIMEOUT_SECONDS": "9.5",
            "KAGENT_SERVICE_REQUEST_TIMEOUT_SECONDS": "4.5",
        }
    )

    assert config.host == "0.0.0.0"
    assert config.port == 9000
    assert config.auth_token == "secret"
    assert config.max_request_bytes == 2048
    assert config.max_goal_chars == 1234
    assert config.rate_limit_per_minute == 12
    assert config.max_concurrent_runs == 3
    assert config.idempotency_cache_size == 5
    assert config.idempotency_cache_path == "/tmp/agent-idempotency.sqlite3"
    assert config.runtime_allowed_tools == ("artifact", "note")
    assert config.runtime_allowed_tools_by_subject == {
        "ops": ("artifact", "note"),
        "team-a": ("note", "transform_text"),
    }
    assert config.runtime_max_iterations == 17
    assert config.runtime_pending_approval_stale_seconds == 1800
    assert config.runtime_instance_heartbeat_seconds == 7.5
    assert config.runtime_orphaned_run_stale_seconds == 45
    assert config.allow_full_trace_response is True
    assert config.protect_diagnostics is True
    assert config.trust_forwarded_for is True
    assert config.trace_dir == "/tmp/agent-traces"
    assert config.runtime_workspace_dir == "/tmp/agent-runtime-workspace"
    assert config.redis_url == "redis://localhost:6379/0"
    assert config.milvus_url == "http://milvus.internal/healthz"
    assert config.embedding_base_url == "https://embedding.example/v1"
    assert config.embedding_api_key == "embedding-key"
    assert config.embedding_model == "text-embedding-model"
    assert config.embedding_timeout_seconds == 6.5
    assert config.embedding_max_retries == 4
    assert config.embedding_retry_backoff_seconds == 0.75
    assert config.kafka_audit_url == "http://kafka-rest.internal/topics/audit"
    assert config.kafka_audit_topic == "kagent-audit"
    assert config.external_backend_timeout_seconds == 1.5
    assert config.run_timeout_seconds == 9.5
    assert config.request_timeout_seconds == 4.5


def test_runtime_run_passes_embedding_retry_config(monkeypatch):
    calls = []

    def fake_run_runtime_agent(goal, **kwargs):
        calls.append({"goal": goal, **kwargs})
        return {"status": "done", "run_id": "run-123"}

    monkeypatch.setattr(service_runtime_run, "run_runtime_agent", fake_run_runtime_agent)

    status_code, payload = service_runtime_run.execute_runtime_run_request(
        json.dumps(
            {
                "goal": "remember this",
                "plan": {"actions": [], "final_answer": "done"},
            }
        ).encode("utf-8"),
        ServiceConfig(
            embedding_base_url="https://embedding.example/v1",
            embedding_api_key="embedding-key",
            embedding_model="text-embedding-model",
            embedding_timeout_seconds=6.5,
            embedding_max_retries=4,
            embedding_retry_backoff_seconds=0.75,
        ),
    )

    assert status_code == 200
    assert payload["status"] == "done"
    assert calls[0]["embedding_base_url"] == "https://embedding.example/v1"
    assert calls[0]["embedding_api_key"] == "embedding-key"
    assert calls[0]["embedding_model"] == "text-embedding-model"
    assert calls[0]["embedding_timeout_seconds"] == 6.5
    assert calls[0]["embedding_max_retries"] == 4
    assert calls[0]["embedding_retry_backoff_seconds"] == 0.75


def test_runtime_resume_passes_embedding_retry_config(tmp_path, monkeypatch):
    calls = []
    pending_action = {
        "id": "step-1",
        "tool": "note",
        "input": {"text": "approved"},
        "reason": "record approval",
    }

    def fake_run_runtime_agent(goal, **kwargs):
        calls.append({"goal": goal, **kwargs})
        return {"status": "done", "run_id": "resumed-123"}

    service_module._persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "pending-123",
            "status": "requires_approval",
            "goal": "record approved note",
            "plan": {"actions": [pending_action], "final_answer": "done"},
            "pending_approval": pending_action,
        },
        str(tmp_path),
    )
    monkeypatch.setattr(
        service_runtime_resume,
        "run_runtime_agent",
        fake_run_runtime_agent,
    )

    status_code, payload = service_runtime_resume.execute_runtime_resume_request(
        json.dumps(
            {
                "run_id": "pending-123",
                "approved_action_ids": ["step-1"],
            }
        ).encode("utf-8"),
        ServiceConfig(
            trace_dir=str(tmp_path),
            embedding_base_url="https://embedding.example/v1",
            embedding_api_key="embedding-key",
            embedding_model="text-embedding-model",
            embedding_timeout_seconds=6.5,
            embedding_max_retries=4,
            embedding_retry_backoff_seconds=0.75,
        ),
    )

    assert status_code == 200
    assert payload["status"] == "done"
    assert calls[0]["embedding_base_url"] == "https://embedding.example/v1"
    assert calls[0]["embedding_api_key"] == "embedding-key"
    assert calls[0]["embedding_model"] == "text-embedding-model"
    assert calls[0]["embedding_timeout_seconds"] == 6.5
    assert calls[0]["embedding_max_retries"] == 4
    assert calls[0]["embedding_retry_backoff_seconds"] == 0.75


def test_service_config_rejects_protected_diagnostics_without_auth_token():
    try:
        ServiceConfig(protect_diagnostics=True)
    except ValueError as exc:
        assert str(exc) == "protect_diagnostics requires auth_token"
    else:
        raise AssertionError("protected diagnostics without auth token was accepted")


def test_service_config_rejects_unknown_runtime_allowed_tools():
    try:
        ServiceConfig(runtime_allowed_tools=("note", "missing_tool"))
    except ValueError as exc:
        assert str(exc) == "runtime_allowed_tools contains unknown tools: missing_tool"
    else:
        raise AssertionError("unknown runtime allowed tool was accepted")


def test_service_config_rejects_unknown_subject_runtime_allowed_tools():
    try:
        ServiceConfig(
            runtime_allowed_tools_by_subject={"team-a": ("note", "missing_tool")}
        )
    except ValueError as exc:
        assert (
            str(exc)
            == "runtime_allowed_tools_by_subject contains unknown tools for team-a: missing_tool"
        )
    else:
        raise AssertionError("unknown subject runtime allowed tool was accepted")


def test_service_config_rejects_non_positive_runtime_iteration_cap():
    try:
        ServiceConfig(runtime_max_iterations=0)
    except ValueError as exc:
        assert str(exc) == "runtime_max_iterations must be at least 1"
    else:
        raise AssertionError("non-positive runtime iteration cap was accepted")


def test_service_config_rejects_invalid_pending_approval_stale_threshold():
    try:
        ServiceConfig(runtime_pending_approval_stale_seconds=-1)
    except ValueError as exc:
        assert str(exc) == (
            "runtime_pending_approval_stale_seconds must be non-negative"
        )
    else:
        raise AssertionError("negative pending approval stale threshold was accepted")


def test_service_config_rejects_non_positive_runtime_instance_heartbeat():
    try:
        ServiceConfig(runtime_instance_heartbeat_seconds=0)
    except ValueError as exc:
        assert str(exc) == "runtime_instance_heartbeat_seconds must be positive"
    else:
        raise AssertionError("non-positive runtime instance heartbeat was accepted")


def test_service_config_rejects_orphan_threshold_not_above_heartbeat():
    try:
        ServiceConfig(
            runtime_instance_heartbeat_seconds=10,
            runtime_orphaned_run_stale_seconds=10,
        )
    except ValueError as exc:
        assert str(exc) == (
            "runtime_orphaned_run_stale_seconds must be greater than "
            "runtime_instance_heartbeat_seconds"
        )
    else:
        raise AssertionError("unsafe orphaned runtime threshold was accepted")


def test_service_module_reports_invalid_environment_config_without_traceback():
    env = os.environ.copy()
    env["KAGENT_SERVICE_PORT"] = "not-a-port"

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "kagent.service",
            "--help",
        ],
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )

    assert completed.returncode == 2
    assert "KAGENT_SERVICE_PORT must be an integer" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_service_cli_help_exposes_runtime_workspace_dir():
    completed = subprocess.run(
        [
            ".venv/bin/kagent-serve",
            "--help",
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0
    assert "--runtime-workspace-dir" in completed.stdout


def test_service_cli_handles_sigterm_with_graceful_exit():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = str(probe.getsockname()[1])

    process = subprocess.Popen(
        [
            ".venv/bin/kagent-serve",
            "--host",
            "127.0.0.1",
            "--port",
            port,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        serving_line = process.stdout.readline()
        assert json.loads(serving_line)["status"] == "serving"

        process.send_signal(signal.SIGTERM)

        stdout, stderr = process.communicate(timeout=5)
        assert stdout == ""
        assert stderr == ""
        assert process.returncode == 143
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)


def test_service_rate_limiter_enforces_fixed_window_limit():
    limiter = ServiceRateLimiter(limit_per_minute=2)

    assert limiter.allow("client-a", now=10.0) is True
    assert limiter.allow("client-a", now=11.0) is True
    assert limiter.allow("client-a", now=12.0) is False
    assert limiter.allow("client-a", now=71.0) is True


def test_service_rate_limiter_can_be_disabled():
    limiter = ServiceRateLimiter(limit_per_minute=0)

    assert limiter.allow("client-a", now=10.0) is True
    assert limiter.allow("client-a", now=10.0) is True


def test_service_rate_limiter_prunes_expired_windows():
    limiter = ServiceRateLimiter(limit_per_minute=1)
    limiter.allow("client-a", now=10.0)
    limiter.allow("client-b", now=20.0)

    limiter.allow("client-c", now=81.0)

    assert limiter.snapshot(now=81.0) == {
        "active_rate_limit_windows": "1",
        "rate_limit_per_minute": "1",
    }


def test_service_rate_limiter_snapshot_prunes_expired_windows_without_new_requests():
    limiter = ServiceRateLimiter(limit_per_minute=1)
    limiter.allow("client-a", now=10.0)
    limiter.allow("client-b", now=20.0)

    assert limiter.snapshot(now=81.0) == {
        "active_rate_limit_windows": "0",
        "rate_limit_per_minute": "1",
    }


def test_service_access_log_schema_documents_required_and_optional_fields():
    schema = service_module.access_log_schema()

    assert schema["type"] == "object"
    assert schema["required"] == [
        "event",
        "method",
        "path",
        "status_code",
        "duration_seconds",
        "request_id",
        "remote_addr",
    ]
    assert schema["properties"]["event"] == {"type": "string", "const": "http_request"}
    assert schema["properties"]["status_code"] == {"type": "integer"}
    assert schema["properties"]["duration_seconds"] == {
        "type": "string",
        "pattern": r"^\d+\.\d{4}$",
    }
    assert schema["properties"]["error_code"]["type"] == "string"
    assert schema["properties"]["run_id"]["type"] == "string"
    assert schema["properties"]["trace_path"]["type"] == "string"
    assert schema["properties"]["idempotency_key_present"]["type"] == "boolean"
    assert schema["properties"]["request_body_bytes"]["type"] == "integer"
    assert schema["properties"]["auth_subject"]["type"] == "string"
    assert schema["properties"]["runtime_owner_auth_subject"]["type"] == "string"
    assert schema["properties"]["resumed_by_auth_subject"]["type"] == "string"
    assert schema["properties"]["approved_by_auth_subject"]["type"] == "string"


def test_service_access_log_record_includes_error_code_when_present():
    record = access_log_record(
        method="GET",
        path="/missing",
        status_code=404,
        duration_seconds=0.125,
        request_id="req-123",
        remote_addr="127.0.0.1",
        error_code="not_found",
    )

    assert record["error_code"] == "not_found"


def test_service_access_log_record_includes_resume_actor_when_present():
    record = access_log_record(
        method="POST",
        path="/runtime/resume",
        status_code=200,
        duration_seconds=0.125,
        request_id="req-123",
        remote_addr="127.0.0.1",
        resumed_by_auth_subject="default",
    )

    assert record["resumed_by_auth_subject"] == "default"


def test_service_access_log_record_includes_approval_actor_when_present():
    record = access_log_record(
        method="POST",
        path="/runtime/resume",
        status_code=200,
        duration_seconds=0.125,
        request_id="req-123",
        remote_addr="127.0.0.1",
        approved_by_auth_subject="default",
    )

    assert record["approved_by_auth_subject"] == "default"


def test_service_access_log_record_includes_runtime_owner_when_present():
    record = access_log_record(
        method="POST",
        path="/runtime/resume",
        status_code=200,
        duration_seconds=0.125,
        request_id="req-123",
        remote_addr="127.0.0.1",
        runtime_owner_auth_subject="team-a",
    )

    assert record["runtime_owner_auth_subject"] == "team-a"


def test_service_access_log_write_flushes_stderr(monkeypatch):
    class FakeStderr:
        def __init__(self):
            self.lines = []
            self.flushes = 0

        def write(self, value):
            self.lines.append(value)

        def flush(self):
            self.flushes += 1

    class FakeHandler:
        command = "GET"
        path = "/health"

        def _request_id(self):
            return "req-123"

        def _remote_addr(self):
            return "127.0.0.1"

        def _metrics(self):
            return ServiceMetrics()

    fake_stderr = FakeStderr()
    monkeypatch.setattr(service_module.sys, "stderr", fake_stderr)

    service_module._AgentRequestHandler._write_access_log(
        FakeHandler(),
        200,
        {"status": "ok"},
    )

    assert fake_stderr.lines
    assert fake_stderr.flushes == 1


def test_service_trace_persistence_keeps_run_id_inside_trace_dir(tmp_path):
    trace_dir = tmp_path / "traces"
    outside_path = tmp_path / "outside.json"

    trace_path = Path(
        service_module._persist_trace(
            {"run_id": "../outside", "status": "done"},
            str(trace_dir),
        )
    )

    assert trace_path.parent == trace_dir
    assert trace_path.name != "../outside.json"
    assert json.loads(trace_path.read_text())["run_id"] == "../outside"
    assert not outside_path.exists()


def test_service_rejects_unknown_route():
    status_code, payload = handle_request("GET", "/missing", b"")

    assert status_code == 404
    assert payload == {
        "status": "failed",
        "error_code": "not_found",
        "error": "not found",
    }


def test_service_head_health_returns_headers_without_body_over_http():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request("HEAD", "/health", headers={"X-Request-ID": "head-req"})
        response = connection.getresponse()
        body = response.read()
        status_code = response.status
        content_type = response.getheader("Content-Type")
        request_id = response.getheader("X-Request-ID")
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status_code == 200
    assert content_type == "application/json"
    assert request_id == "head-req"
    assert body == b""


def test_service_access_log_includes_runtime_resume_actor_and_owner_over_http(
    tmp_path,
    capsys,
):
    pending_action = {
        "id": "step-1",
        "tool": "note",
        "input": {"text": "approved note"},
        "reason": "record approved note",
    }
    service_module._persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "pending-team-a",
            "status": "requires_approval",
            "goal": "record approved note",
            "auth_subject": "team-a",
            "plan": {"actions": [pending_action], "final_answer": "recorded"},
            "pending_approval": pending_action,
        },
        str(tmp_path),
    )
    server = create_server(
        "127.0.0.1",
        0,
        config=ServiceConfig(
            trace_dir=str(tmp_path),
            auth_token="admin-token",
            auth_tokens={"team-a": "team-a-token"},
        ),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    body = json.dumps(
        {
            "run_id": "pending-team-a",
            "approved_action_ids": ["step-1"],
        }
    ).encode("utf-8")

    try:
        request = urllib.request.Request(
            f"http://{host}:{port}/runtime/resume",
            data=body,
            headers={
                "Authorization": "Bearer admin-token",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            run = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    stderr = capsys.readouterr().err
    records = [json.loads(line) for line in stderr.splitlines() if line.strip()]
    resume_records = [
        record
        for record in records
        if record["method"] == "POST" and record["path"] == "/runtime/resume"
    ]

    assert run["status"] == "done"
    assert run["auth_subject"] == "team-a"
    assert run["resumed_by_auth_subject"] == "default"
    assert run["approved_by_auth_subject"] == "default"
    assert resume_records[-1]["auth_subject"] == "default"
    assert resume_records[-1]["resumed_by_auth_subject"] == "default"
    assert resume_records[-1]["approved_by_auth_subject"] == "default"
    assert resume_records[-1]["runtime_owner_auth_subject"] == "team-a"
    assert "admin-token" not in stderr
    assert "team-a-token" not in stderr


def test_service_can_serve_prometheus_metrics_over_http():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        _open_json(f"http://{host}:{port}/health")
        text, content_type = _open_text(f"http://{host}:{port}/metrics.prom")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert content_type.startswith("text/plain")
    assert "kagent_requests_total" in text
    assert "kagent_active_concurrent_runs" in text


def test_service_echoes_request_id_header_over_http():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        request = urllib.request.Request(
            f"http://{host}:{port}/health",
            headers={"X-Request-ID": "req-123"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            request_id = response.headers["X-Request-ID"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert request_id == "req-123"


def test_service_runtime_run_response_includes_trace_path_header_over_http(tmp_path):
    server = create_server(
        "127.0.0.1",
        0,
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        request = urllib.request.Request(
            f"http://{host}:{port}/runtime/run",
            data=json.dumps(
                {
                    "goal": "capture hello",
                    "plan": {
                        "actions": [
                            {
                                "id": "step-1",
                                "tool": "note",
                                "input": {"text": "hello"},
                            }
                        ]
                    },
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            trace_path_header = response.headers["X-Trace-Path"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert trace_path_header == payload["trace_path"]
    assert Path(trace_path_header).exists()


def test_service_accepts_safe_request_id_header_value():
    assert service_module._request_id_from_headers({"X-Request-ID": "req-123_A"}) == "req-123_A"


def test_service_replaces_unsafe_request_id_header_value():
    request_id = service_module._request_id_from_headers({"X-Request-ID": "bad\nid"})

    assert UUID(request_id)
    assert request_id != "bad\nid"


def test_service_replaces_oversized_request_id_header_value():
    request_id = service_module._request_id_from_headers({"X-Request-ID": "x" * 129})

    assert UUID(request_id)
    assert request_id != "x" * 129


def test_service_sets_content_type_options_header_over_http():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        request = urllib.request.Request(f"http://{host}:{port}/health", method="GET")
        with urllib.request.urlopen(request, timeout=5) as response:
            content_type_options = response.headers["X-Content-Type-Options"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert content_type_options == "nosniff"


def test_service_server_header_does_not_expose_python_runtime_over_http():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        request = urllib.request.Request(f"http://{host}:{port}/health", method="GET")
        with urllib.request.urlopen(request, timeout=5) as response:
            server_header = response.headers["Server"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert server_header == "kagentHTTP/0.1"
    assert "Python" not in server_header


def test_service_metrics_endpoint_counts_prior_http_requests():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        _open_json(f"http://{host}:{port}/health")
        _open_json(f"http://{host}:{port}/version")
        metrics = _open_json(f"http://{host}:{port}/metrics")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert metrics["requests_total"] == "2"
    assert metrics["requests_by_method"] == {"GET": "2"}
    assert metrics["requests_by_path"] == {"/health": "1", "/version": "1"}
    assert float(metrics["average_duration_seconds"]) > 0
    assert float(metrics["max_duration_seconds"]) > 0
    assert float(metrics["uptime_seconds"]) >= 0


def test_service_metrics_endpoint_counts_error_responses_by_code_over_http():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        try:
            _open_json(f"http://{host}:{port}/missing-random-123")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        metrics = _open_json(f"http://{host}:{port}/metrics")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert metrics["error_responses_by_code"] == {"not_found": "1"}
    assert metrics["requests_by_path"] == {"__unknown__": "1"}


def test_service_metrics_counts_readiness_failures_by_error_code_over_http(tmp_path):
    blocking_file = tmp_path / "not-a-directory"
    blocking_file.write_text("blocks trace directory creation")
    server = create_server(
        "127.0.0.1",
        0,
        config=ServiceConfig(trace_dir=str(blocking_file / "traces")),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        try:
            _open_json(f"http://{host}:{port}/ready")
        except urllib.error.HTTPError as exc:
            assert exc.code == 503
        metrics = _open_json(f"http://{host}:{port}/metrics")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert metrics["error_responses_by_code"] == {"readiness_failed": "1"}
    assert metrics["requests_by_path"] == {"/ready": "1"}


def _open_json(url: str, data=None, headers=None):
    request_headers = {"Content-Type": "application/json"}
    request_headers.update(headers or {})
    request = urllib.request.Request(
        url,
        data=data,
        headers=request_headers,
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read().decode("utf-8"))


def _open_text(url: str):
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.read().decode("utf-8"), response.headers["Content-Type"]


def _parse_sse_events(body: str):
    events = []
    for raw_event in body.strip().split("\n\n"):
        event_name = ""
        data_lines = []
        for line in raw_event.splitlines():
            if line.startswith("event: "):
                event_name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data_lines.append(line.removeprefix("data: "))
        events.append(
            {
                "event": event_name,
                "data": json.loads("\n".join(data_lines)),
            }
        )
    return events


def _read_sse_event(response):
    event_name = ""
    data_lines = []
    while True:
        line = response.readline().decode("utf-8")
        if line == "":
            raise AssertionError("stream ended before SSE event completed")
        line = line.rstrip("\r\n")
        if line == "":
            return {
                "event": event_name,
                "data": json.loads("\n".join(data_lines)),
            }
        if line.startswith("event: "):
            event_name = line.removeprefix("event: ")
        elif line.startswith("data: "):
            data_lines.append(line.removeprefix("data: "))
