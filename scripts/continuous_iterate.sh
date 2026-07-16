#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

DURATION_SECONDS="${1:-18000}"
INTERVAL_SECONDS="${2:-60}"
LOG_FILE="${3:-/tmp/kagent-continuous.log}"
METRICS_FILE="${4:-/tmp/kagent-continuous.jsonl}"
CHECK_COMMAND="${KAGENT_CHECK_COMMAND:-scripts/run_checks.sh}"
END_AT=$(( $(date +%s) + DURATION_SECONDS ))
ITERATION=1

while [ "$ITERATION" -eq 1 ] || [ "$(date +%s)" -lt "$END_AT" ]; do
  STARTED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  CHECK_RESULT="$(.venv/bin/python - "$LOG_FILE" "$CHECK_COMMAND" "$ITERATION" "$STARTED_AT" <<'PY'
import subprocess
import sys
import time

log_file, command, iteration, started_at = sys.argv[1:]
with open(log_file, "a", encoding="utf-8") as handle:
    handle.write(f"== iteration {iteration} {started_at} ==\n")
    handle.flush()
    started_nanos = time.monotonic_ns()
    completed = subprocess.run(command, shell=True, stdout=handle, stderr=subprocess.STDOUT)
    duration = max(0, (time.monotonic_ns() - started_nanos) // 1_000_000_000)
    handle.write("\n")
print(completed.returncode)
print(duration)
PY
)"
  CHECKS_EXIT_CODE="$(printf '%s\n' "$CHECK_RESULT" | sed -n '1p')"
  DURATION="$(printf '%s\n' "$CHECK_RESULT" | sed -n '2p')"
  STATUS="failed"
  if [ "$CHECKS_EXIT_CODE" -eq 0 ]; then
    STATUS="passed"
  fi

  .venv/bin/python - "$METRICS_FILE" "$ITERATION" "$STARTED_AT" "$DURATION" "$CHECKS_EXIT_CODE" "$STATUS" <<'PY'
import json
import sys

metrics_path, iteration, started_at, duration, exit_code, status = sys.argv[1:]
record = {
    "iteration": int(iteration),
    "started_at": started_at,
    "duration_seconds": duration,
    "checks_exit_code": int(exit_code),
    "status": status,
}

with open(metrics_path, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(record, sort_keys=True) + "\n")
PY

  ITERATION=$((ITERATION + 1))
  if [ "$(date +%s)" -lt "$END_AT" ]; then
    sleep "$INTERVAL_SECONDS"
  fi
done

echo "continuous iteration complete: ${LOG_FILE}"
echo "continuous metrics complete: ${METRICS_FILE}"
