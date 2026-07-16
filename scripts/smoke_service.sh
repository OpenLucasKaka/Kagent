#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
SERVICE_BIN="${SERVICE_BIN:-.venv/bin/kagent-serve}"
PORT="$("$PYTHON_BIN" - <<'PY'
import socket

sock = socket.socket()
sock.bind(("127.0.0.1", 0))
print(sock.getsockname()[1])
sock.close()
PY
)"

SERVICE_LOG="${SERVICE_LOG:-/tmp/kagent-service-smoke.log}"
AUTH_TOKEN="${KAGENT_SMOKE_AUTH_TOKEN:-smoke-token}"
TRACE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/kagent-traces.XXXXXX")"
KAGENT_SERVICE_AUTH_TOKEN="$AUTH_TOKEN" \
    "$SERVICE_BIN" --host 127.0.0.1 --port "$PORT" --trace-dir "$TRACE_DIR" \
    --max-request-bytes 4096 --max-goal-chars 256 --idempotency-cache-size 8 \
    --protect-diagnostics --trust-forwarded-for \
    --request-timeout-seconds 1 \
    >"$SERVICE_LOG.stdout" 2>"$SERVICE_LOG.stderr" &
server_pid="$!"

dump_service_logs() {
    echo "service smoke failed for pid ${server_pid} on port ${PORT}" >&2
    if kill -0 "$server_pid" 2>/dev/null; then
        echo "service process is still running" >&2
    else
        echo "service process is not running" >&2
    fi
    echo "service stdout ($SERVICE_LOG.stdout):" >&2
    sed -n '1,160p' "$SERVICE_LOG.stdout" >&2 || true
    echo "service stderr ($SERVICE_LOG.stderr):" >&2
    sed -n '1,220p' "$SERVICE_LOG.stderr" >&2 || true
}

cleanup() {
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
    rm -rf "$TRACE_DIR"
}
trap cleanup EXIT INT TERM

if ! "$PYTHON_BIN" - "$PORT" "$SERVICE_LOG.stderr" "$AUTH_TOKEN" <<'PY'
import json
import sys
import time
import urllib.error
import urllib.request

port = sys.argv[1]
service_stderr_path = sys.argv[2]
auth_token = sys.argv[3]
base_url = f"http://127.0.0.1:{port}"
REQUEST_TIMEOUT_SECONDS = 15


def get_json(path, *, auth=False):
    headers = {"Authorization": f"Bearer {auth_token}"} if auth else {}
    request = urllib.request.Request(f"{base_url}{path}", headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8")), response.headers


def post_json(path, payload, *, extra_headers=None):
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
    }
    headers.update(extra_headers or {})
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8")), response.headers


def post_sse(path, payload):
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8"), response.headers


def parse_sse_events(body):
    events = []
    for raw_event in body.strip().split("\n\n"):
        event_name = ""
        data_lines = []
        for line in raw_event.splitlines():
            if line.startswith("event: "):
                event_name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data_lines.append(line.removeprefix("data: "))
        events.append({"event": event_name, "data": json.loads("\n".join(data_lines))})
    return events


deadline = time.time() + 10
while True:
    try:
        health, health_headers = get_json("/health")
        assert health == {"status": "ok"}
        assert health_headers["X-Content-Type-Options"] == "nosniff"
        assert health_headers["Cache-Control"] == "no-store"
        break
    except Exception:
        if time.time() >= deadline:
            raise
        time.sleep(0.2)

ready, _headers = get_json("/ready")
assert ready["status"] == "ready"
assert ready["checks"]["trace_persistence"] == "ok"
assert ready["checks"]["runtime_tools"] == "ok"
assert "agent_config" not in ready["checks"]

try:
    urllib.request.urlopen(f"{base_url}/metrics", timeout=REQUEST_TIMEOUT_SECONDS)
except urllib.error.HTTPError as exc:
    assert exc.code == 401
else:
    raise AssertionError("unauthorized diagnostic probe unexpectedly succeeded")

config, _headers = get_json("/config", auth=True)
assert config["auth_required"] == "true"
assert config["protect_diagnostics"] == "true"
assert config["trace_persistence"] == "enabled"
assert config["runtime_max_iterations"]

openapi_payload, _headers = get_json("/openapi.json", auth=True)
openapi_paths = openapi_payload["paths"]
assert "/run" not in openapi_paths
assert "/tools" not in openapi_paths
assert openapi_paths["/runtime/run"]["post"]["operationId"] == "postRuntimeRun"
assert openapi_paths["/runtime/run/stream"]["post"]["operationId"] == "postRuntimeRunStream"
assert openapi_paths["/runtime/tools"]["get"]["operationId"] == "getRuntimeTools"
assert "RunRequest" not in openapi_payload["components"]["schemas"]
assert "ToolsResponse" not in openapi_payload["components"]["schemas"]

runtime_tools, _headers = get_json("/runtime/tools", auth=True)
tool_names = {item["name"] for item in runtime_tools["tools"]}
assert {"note", "artifact", "apply_patch"}.issubset(tool_names)

head_request = urllib.request.Request(f"{base_url}/health", method="HEAD")
with urllib.request.urlopen(head_request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
    assert response.status == 200
    assert response.headers["Server"] == "kagentHTTP/0.1"
    assert response.read() == b""

runtime_payload, runtime_headers = post_json(
    "/runtime/run",
    {
        "goal": "capture hello",
        "plan": {
            "actions": [],
            "final_answer": "captured hello",
        },
        "metadata": {"suite": "service-smoke"},
        "tags": ["smoke"],
    },
    extra_headers={"Idempotency-Key": "runtime-smoke-1"},
)
assert runtime_payload["status"] == "done"
assert runtime_payload["answer"] == "captured hello"
assert runtime_payload["trace_path"]
assert runtime_payload["metadata"] == {"suite": "service-smoke"}
assert runtime_payload["tags"] == ["smoke"]

stream_body, stream_headers = post_sse(
    "/runtime/run/stream",
    {
        "goal": "stream hello",
        "plan": {
            "actions": [],
            "final_answer": "streamed hello",
        },
    },
)
assert stream_headers["Content-Type"] == "text/event-stream"
stream_events = parse_sse_events(stream_body)
assert any(event["event"] == "answer_delta" for event in stream_events)
assert stream_events[-1]["event"] == "final"
assert stream_events[-1]["data"]["answer"] == "streamed hello"

runtime_payload_again, _headers = post_json(
    "/runtime/run",
    {
        "goal": "capture hello",
        "plan": {
            "actions": [],
            "final_answer": "captured hello",
        },
        "metadata": {"suite": "service-smoke"},
        "tags": ["smoke"],
    },
    extra_headers={"Idempotency-Key": "runtime-smoke-1"},
)
assert runtime_payload_again == runtime_payload

metrics, _headers = get_json("/metrics", auth=True)
assert metrics["requests_by_path"]["/runtime/run"] == "2"
assert metrics["requests_by_path"]["/runtime/run/stream"] == "1"
assert metrics["idempotency_cache_hits"] == "1"

with open(service_stderr_path, encoding="utf-8") as handle:
    records = [json.loads(line) for line in handle if line.strip().startswith("{")]
runtime_records = [
    record
    for record in records
    if record["method"] == "POST" and record["path"] == "/runtime/run"
]
assert runtime_records
assert runtime_records[-1]["idempotency_key_present"] is True
assert "runtime-smoke-1" not in json.dumps(records)
PY
then
    dump_service_logs
    exit 1
fi
