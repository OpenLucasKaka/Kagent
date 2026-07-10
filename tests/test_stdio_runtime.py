import json
import subprocess


def _jsonl(stdout: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


def test_stdio_runtime_accepts_run_request_and_streams_jsonl_events():
    request = {
        "type": "run_request",
        "goal": "capture hello",
        "max_iterations": 2,
        "runtime_plan": json.dumps(
            {
                "actions": [
                    {
                        "id": "step-1",
                        "tool": "note",
                        "input": {"text": "hello from stdio"},
                        "reason": "exercise the stdio protocol",
                    }
                ],
                "final_answer": "stdio done",
            }
        ),
    }

    completed = subprocess.run(
        [".venv/bin/python", "-m", "kagent.cli.stdio_runtime"],
        input=f"{json.dumps(request)}\n",
        capture_output=True,
        text=True,
        check=True,
    )

    events = _jsonl(completed.stdout)
    assert completed.stderr == ""
    assert [event["type"] for event in events][:2] == [
        "run_started",
        "run_progress",
    ]
    assert events[-1]["type"] == "run_completed"
    assert events[-1]["status"] == "done"
    assert events[-1]["answer"] == "stdio done"
    assert events[-1]["payload"]["goal"] == "capture hello"


def test_stdio_runtime_reports_malformed_json_as_structured_error():
    completed = subprocess.run(
        [".venv/bin/python", "-m", "kagent.cli.stdio_runtime"],
        input="{not json}\n",
        capture_output=True,
        text=True,
        check=False,
    )

    events = _jsonl(completed.stdout)
    assert completed.returncode == 0
    assert completed.stderr == ""
    assert events[-1]["type"] == "run_failed"
    assert events[-1]["error_code"] == "invalid_json"


def test_stdio_runtime_reports_invalid_iteration_budget_without_crashing():
    request = {
        "type": "run_request",
        "goal": "invalid budget",
        "max_iterations": 0,
    }

    completed = subprocess.run(
        [".venv/bin/python", "-m", "kagent.cli.stdio_runtime"],
        input=f"{json.dumps(request)}\n",
        capture_output=True,
        text=True,
        check=True,
    )

    events = _jsonl(completed.stdout)
    assert events == [
        {
            "type": "run_failed",
            "error_code": "invalid_request",
            "message": "max_iterations must be at least 1",
        }
    ]
    assert "Traceback" not in completed.stdout
    assert completed.stderr == ""


def test_stdio_runtime_reports_missing_provider_as_structured_error(tmp_path):
    env = {
        "KAGENT_LLM_CONFIG_PATH": str(tmp_path / "missing-provider.json"),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "PYTHONPATH": "src",
    }
    request = {"type": "run_request", "goal": "needs provider"}

    completed = subprocess.run(
        [".venv/bin/python", "-m", "kagent.cli.stdio_runtime"],
        input=f"{json.dumps(request)}\n",
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    events = _jsonl(completed.stdout)
    assert events[0]["type"] == "run_started"
    assert events[-1]["type"] == "run_failed"
    assert events[-1]["error_code"] == "provider_not_configured"
    assert "KAGENT_LLM_BASE_URL" in events[-1]["message"]
