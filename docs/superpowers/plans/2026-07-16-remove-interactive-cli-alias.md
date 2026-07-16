# Remove the `--interactive` CLI Alias Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove `--interactive` as a public Python CLI option while preserving `kagent --classic` as the single explicit classic-terminal entry point.

**Architecture:** The npm launcher remains unchanged: bare `kagent` opens Ink, while `--classic` is stripped before the launcher invokes Python with no goal. The Python CLI retains an internal `args.interactive` state derived from the absence of a goal, but argparse no longer exposes a second interactive selector.

**Tech Stack:** Python 3.9+, argparse, pytest, Node.js/TypeScript launcher tests, POSIX shell smoke checks.

---

## File Map

- `src/kagent/cli/main.py`: remove the public option, initialize internal interactive state, and update CLI diagnostics.
- `tests/test_cli.py`: prove the removed option is rejected and implicit interactive behavior remains available.
- `scripts/run_checks.sh`: exercise Python interactive mode through the supported no-goal path instead of the removed alias.
- `npm/src/launcher.test.ts`: unchanged reference test proving `--classic` invokes Python with an empty argument list.
- `README.md` and `docs/operations.md`: verify public classic-UI guidance names only `--classic`; no content change is required unless the final search finds stale explicit `--interactive` guidance.

### Task 1: Specify the Removed Alias and Internal Interactive State

**Files:**
- Modify: `tests/test_cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Make the default-mode unit test require internal state initialization**

In `test_cli_defaults_goal_runs_to_runtime_mode`, remove the pre-populated
`interactive=False` field from the `Namespace`. Keep the existing assertion:

```python
args = Namespace(
    deterministic=False,
    runtime=False,
    runtime_plan="",
    goal="write an internal rollout plan",
    list_tools=False,
    list_faults=False,
    graph=False,
    version=False,
    plan=False,
    summary=False,
    max_steps=None,
    max_retries=None,
    inject_wrong_answer=[],
    inject_fault=[],
)

_apply_default_cli_mode(args)

assert args.runtime is True
assert args.interactive is False
```

- [ ] **Step 2: Add subprocess tests for help and rejection behavior**

Add these tests near the other CLI entrypoint tests:

```python
def test_cli_help_does_not_advertise_removed_interactive_alias():
    completed = subprocess.run(
        [".venv/bin/python", "-m", "kagent.cli", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "\n  --interactive " not in completed.stdout
    assert "--classic" not in completed.stdout


def test_cli_rejects_removed_interactive_alias():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "kagent.cli",
            "--interactive",
            "--runtime-plan",
            '{"actions":[],"final_answer":"ready"}',
        ],
        input="exit\n",
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "unrecognized arguments: --interactive" in completed.stderr
    assert "Traceback" not in completed.stderr
```

The `--classic` assertion documents that this option belongs to the npm
launcher rather than the Python parser.

- [ ] **Step 3: Run the tests and verify RED**

Run:

```bash
.venv/bin/pytest \
  tests/test_cli.py::test_cli_defaults_goal_runs_to_runtime_mode \
  tests/test_cli.py::test_cli_help_does_not_advertise_removed_interactive_alias \
  tests/test_cli.py::test_cli_rejects_removed_interactive_alias -q
```

Expected: the unit test fails because `interactive` was not initialized, help
still contains the option, and `--interactive` is accepted instead of rejected.

### Task 2: Remove the Public Option with the Minimum Python Change

**Files:**
- Modify: `src/kagent/cli/main.py:48-52`
- Modify: `src/kagent/cli/main.py:58-65`
- Modify: `src/kagent/cli/main.py:138-151`
- Modify: `src/kagent/cli/main.py:238-242`
- Modify: `src/kagent/cli/main.py:464-470`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Remove the argparse declaration**

Delete only this block:

```python
parser.add_argument(
    "--interactive",
    action="store_true",
    help="Start the kagent terminal agent that reads goals from stdin.",
)
```

Keep `--interactive-json`, `--session-memory`, and the internal interactive
runner.

- [ ] **Step 2: Initialize internal mode before every branch**

Replace `_apply_default_cli_mode` with:

```python
def _apply_default_cli_mode(args: argparse.Namespace) -> None:
    args.interactive = False
    if getattr(args, "configure", False):
        return
    args.runtime = True
    if args.goal is None and not _is_introspection_command(args):
        args.interactive = True
```

This keeps `--classic` working because the npm launcher passes an empty Python
argument list, while one-shot goals retain `interactive=False`.

- [ ] **Step 3: Update help and diagnostics without changing validation**

Use these user-facing strings:

```python
help=(
    "Persist interactive runtime session memory to PATH. "
    "Only valid in interactive mode."
)
```

```python
parser.error("--interactive-json requires interactive mode")
parser.error("--session-memory requires interactive mode")
parser.error("--output is not supported in interactive mode")
```

Update the missing-goal diagnostic to:

```python
parser.error(
    "goal is required unless --list-tools, --graph, --version, "
    "or --configure is used"
)
```

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run the same command from Task 1.

Expected: `3 passed`.

- [ ] **Step 5: Commit the parser behavior change**

```bash
git add src/kagent/cli/main.py tests/test_cli.py
git commit -m "refactor: remove interactive CLI alias"
```

### Task 3: Migrate Tests and Smoke Checks to Implicit Interactive Mode

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `scripts/run_checks.sh`

- [ ] **Step 1: Remove explicit alias arguments from interactive tests**

For every subprocess argument list in `tests/test_cli.py`, delete the standalone
item:

```python
"--interactive",
```

Do not remove `--interactive-json`. Each affected command has no positional
goal, so `_apply_default_cli_mode` selects interactive mode automatically.

Change the session-memory diagnostic assertion to:

```python
assert "--session-memory requires interactive mode" in completed.stderr
```

- [ ] **Step 2: Run the CLI test module**

Run:

```bash
.venv/bin/pytest tests/test_cli.py -q
```

Expected: all CLI tests pass with no traceback or unexpected warning output.

- [ ] **Step 3: Remove the alias from shell smoke commands**

Delete each standalone shell continuation from `scripts/run_checks.sh`:

```bash
    --interactive \
```

Retain `--runtime`, `--runtime-plan`, `--session-memory`, and stdin piping. With
no positional goal, these commands still enter internal interactive mode.

- [ ] **Step 4: Verify no stale explicit alias remains outside historical design records**

Run:

```bash
rg -n --pcre2 -- '--interactive(?!-json)' \
  src tests scripts README.md docs/operations.md npm/src
```

Expected: the only matches are the regression test argument and assertion that
prove `--interactive` is rejected. References in the approved design and
implementation plan are intentionally excluded from this command.

- [ ] **Step 5: Commit migrated callers**

```bash
git add tests/test_cli.py scripts/run_checks.sh README.md docs/operations.md
git commit -m "test: use implicit Python interactive mode"
```

Only stage README or operations documentation if the search required an actual
edit.

### Task 4: Confirm `--classic` Remains the Single Explicit Entry

**Files:**
- Test: `npm/src/launcher.test.ts`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Run the npm launcher regression test**

Run:

```bash
npm run build:cli
node --test npm/lib/launcher.test.js
```

Expected: the existing `runs the same automatic preflight before classic
Python` test passes and confirms `launchKagent(["--classic"])` calls Python with
`[]`.

- [ ] **Step 2: Verify public command behavior manually**

Run:

```bash
printf 'exit\n' | .venv/bin/python -m kagent.cli \
  --runtime-plan '{"actions":[],"final_answer":"ready"}'
```

Expected: exit code `0`; implicit interactive mode accepts stdin without
requiring `--interactive`.

Run:

```bash
.venv/bin/python -m kagent.cli --interactive
```

Expected: exit code `2` and `unrecognized arguments: --interactive`.

- [ ] **Step 3: Run repository verification**

Run:

```bash
.venv/bin/ruff check src tests
.venv/bin/pytest -q
npm run check
bash scripts/run_checks.sh
```

Expected: every command exits `0` with no test failures. If the full smoke script
depends on unavailable external services, report the exact failing command and
retain the successful focused Python and npm evidence.

- [ ] **Step 4: Inspect the final diff**

Run:

```bash
git diff --check HEAD~2..HEAD
git status --short
```

Expected: no whitespace errors; only the known unrelated untracked
`docs/superpowers/plans/2026-07-13-npm-update-channels.md` remains outside this
work.
