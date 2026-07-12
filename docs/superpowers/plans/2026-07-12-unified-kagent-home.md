# Unified Kagent Home Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate all user-level Kagent configuration, durable state, and cache defaults under `~/.kagent` with safe legacy migration and unchanged project-local `.kagent` behavior.

**Architecture:** Add one Python path/migration module and one TypeScript home-path module. Existing consumers delegate default-path construction to those modules while explicit environment overrides retain precedence. Durable XDG data is copied atomically once; disposable cache is rebuilt.

**Tech Stack:** Python 3.9+, TypeScript, Node.js 18+, pytest, Node test runner, GitHub Actions.

---

### Task 1: Repair clean-checkout CI dependency installation

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_ci.py`

- [ ] **Step 1: Add a failing workflow contract test**

```python
def test_github_actions_ci_installs_node_dependencies():
    workflow = Path(".github/workflows/ci.yml").read_text()

    assert "actions/setup-node@v4" in workflow
    assert "node-version: 22" in workflow
    assert "cache: npm" in workflow
    assert "npm ci" in workflow
```

- [ ] **Step 2: Verify the contract fails**

Run: `.venv/bin/python -m pytest tests/test_ci.py::test_github_actions_ci_installs_node_dependencies -q`

Expected: FAIL because the workflow does not contain `actions/setup-node@v4` or `npm ci`.

- [ ] **Step 3: Install Node dependencies in CI**

Insert after Python setup:

```yaml
      - name: Set up Node
        uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: npm

      - name: Install Node dependencies
        run: npm ci
```

- [ ] **Step 4: Verify the workflow contract and clean npm build**

Run: `.venv/bin/python -m pytest tests/test_ci.py -q`

Run in a temporary `git archive` checkout: `npm ci && npm run check`

Expected: all CI tests and all Node checks PASS.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml tests/test_ci.py
git commit -m "fix: install node dependencies in ci"
```

### Task 2: Add Python Kagent home and migration primitives

**Files:**
- Create: `src/kagent/utils/paths.py`
- Create: `tests/test_paths.py`

- [ ] **Step 1: Add failing path-resolution tests**

Cover these exact expectations:

```python
def test_default_kagent_home_uses_hidden_home_directory(tmp_path):
    env = {"HOME": str(tmp_path)}
    assert kagent_home(env) == tmp_path / ".kagent"
    assert kagent_config_dir(env) == tmp_path / ".kagent" / "config"
    assert kagent_state_dir(env) == tmp_path / ".kagent" / "state"
    assert kagent_cache_dir(env) == tmp_path / ".kagent" / "cache"


def test_explicit_kagent_home_wins(tmp_path):
    configured = tmp_path / "custom-home"
    env = {"HOME": str(tmp_path), "KAGENT_HOME": str(configured)}
    assert kagent_home(env) == configured
```

- [ ] **Step 2: Verify the new tests fail**

Run: `.venv/bin/python -m pytest tests/test_paths.py -q`

Expected: collection FAIL because `kagent.utils.paths` does not exist.

- [ ] **Step 3: Implement path resolution**

Create `paths.py` with public functions:

```python
KAGENT_HOME_ENV_VAR = "KAGENT_HOME"

def kagent_home(env: Mapping[str, str] | None = None) -> Path: ...
def kagent_config_dir(env: Mapping[str, str] | None = None) -> Path: ...
def kagent_state_dir(env: Mapping[str, str] | None = None) -> Path: ...
def kagent_cache_dir(env: Mapping[str, str] | None = None) -> Path: ...
def migrate_legacy_kagent_state(env: Mapping[str, str] | None = None) -> Path: ...
```

`kagent_home()` expands `~`, requires a usable `HOME` when no explicit home is
configured, and returns an absolute path.

- [ ] **Step 4: Add failing migration tests**

Test provider config, session memory, history, pending approvals, and patches;
also test destination-wins, repeated calls, marker creation, explicit
`KAGENT_HOME` migration skip, symlink rejection, and `0700`/`0600` modes.

- [ ] **Step 5: Verify migration tests fail for missing behavior**

Run: `.venv/bin/python -m pytest tests/test_paths.py -q`

Expected: path tests PASS and migration tests FAIL because no files are copied.

- [ ] **Step 6: Implement safe migration**

Use a fixed legacy mapping and atomic file copies. Reject symlink chains before
reading or writing. Never overwrite destinations. Recursively copy only regular
files from `pending-approvals` and `patches`. Write the owner-only completion
marker only after every eligible copy succeeds.

- [ ] **Step 7: Verify Python path and migration tests**

Run: `.venv/bin/python -m pytest tests/test_paths.py -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/kagent/utils/paths.py tests/test_paths.py
git commit -m "feat: add unified kagent home migration"
```

### Task 3: Route Python durable state through Kagent home

**Files:**
- Modify: `src/kagent/providers/llm.py`
- Modify: `src/kagent/cli/memory.py`
- Modify: `src/kagent/cli/pending_approval.py`
- Modify: `src/kagent/runtime/patch_checkpoints.py`
- Modify: `tests/test_llm_provider.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_pending_approval.py`
- Modify: `tests/test_runtime_tools.py`

- [ ] **Step 1: Change existing tests to expect `~/.kagent` defaults**

Expected paths:

```text
~/.kagent/config/provider.json
~/.kagent/state/session-memory.json
~/.kagent/state/history
~/.kagent/state/pending-approvals
~/.kagent/state/patches
```

Add one explicit-override test per public path function and at least one test
showing default resolution triggers legacy migration before returning.

- [ ] **Step 2: Verify focused tests fail**

Run: `.venv/bin/python -m pytest tests/test_llm_provider.py tests/test_cli.py tests/test_pending_approval.py tests/test_runtime_tools.py -q`

Expected: FAIL on old XDG path expectations.

- [ ] **Step 3: Delegate default paths to `kagent.utils.paths`**

Keep each existing explicit environment variable check first. For default paths,
call `migrate_legacy_kagent_state()` and derive the result from the config or
state directory helpers. Do not change project-local runtime workspace or skill
resolution.

- [ ] **Step 4: Verify focused Python tests**

Run: `.venv/bin/python -m pytest tests/test_paths.py tests/test_llm_provider.py tests/test_cli.py tests/test_pending_approval.py tests/test_runtime_tools.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/kagent/providers/llm.py src/kagent/cli/memory.py src/kagent/cli/pending_approval.py src/kagent/runtime/patch_checkpoints.py tests/test_llm_provider.py tests/test_cli.py tests/test_pending_approval.py tests/test_runtime_tools.py
git commit -m "feat: store durable state under kagent home"
```

### Task 4: Route npm cache and approval state through Kagent home

**Files:**
- Create: `npm/src/kagent-home.ts`
- Create: `npm/src/kagent-home.test.ts`
- Modify: `npm/src/runtime-client.ts`
- Modify: `npm/lib/python-runner.js`
- Modify: `tests/test_npm_package.py`

- [ ] **Step 1: Add failing TypeScript path tests**

Test these pure functions:

```typescript
resolveKagentHome({HOME: "/Users/kaka"})
// /Users/kaka/.kagent

resolveKagentHome({HOME: "/Users/kaka", KAGENT_HOME: "/tmp/kagent"})
// /tmp/kagent

kagentStatePath("pending-approvals", env)
// /Users/kaka/.kagent/state/pending-approvals

kagentCachePath("npm-python", env)
// /Users/kaka/.kagent/cache/npm-python
```

- [ ] **Step 2: Verify Node tests fail**

Run: `npm run build:cli && node --test npm/lib/kagent-home.test.js`

Expected: build FAIL because `npm/src/kagent-home.ts` does not exist.

- [ ] **Step 3: Implement `kagent-home.ts` and use it in runtime client**

Export `resolveKagentHome`, `kagentStatePath`, and `kagentCachePath`. Preserve
`KAGENT_PENDING_APPROVAL_PATH` precedence in `runtime-client.ts`.

- [ ] **Step 4: Route the CommonJS launcher cache through `KAGENT_HOME`**

Update `cacheRoot()` and `metadataCacheRoot()` in `npm/lib/python-runner.js` so
`KAGENT_NODE_VENV` remains highest precedence and default cache paths become
`~/.kagent/cache/npm-python` and `~/.kagent/cache`.

- [ ] **Step 5: Update package behavioral tests**

Replace XDG default assertions with `KAGENT_HOME`/`~/.kagent` expectations and
add a launcher test that inspects the private Python runtime path.

- [ ] **Step 6: Verify Node and packaging tests**

Run: `npm run check`

Run: `.venv/bin/python -m pytest tests/test_npm_package.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add npm/src/kagent-home.ts npm/src/kagent-home.test.ts npm/src/runtime-client.ts npm/lib/python-runner.js npm/lib tests/test_npm_package.py
git commit -m "feat: use unified kagent home in npm client"
```

### Task 5: Document the unified layout and verify the complete release gate

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/operations.md`
- Modify: `docs/iteration_log.md`
- Modify: `tests/test_docs.py`
- Modify: `tests/test_operations_docs.py`

- [ ] **Step 1: Add failing documentation assertions**

Require `KAGENT_HOME`, `~/.kagent/config/provider.json`,
`~/.kagent/state/session-memory.json`, legacy migration behavior, and the
project/global `.kagent` distinction.

- [ ] **Step 2: Verify documentation tests fail**

Run: `.venv/bin/python -m pytest tests/test_docs.py tests/test_operations_docs.py -q`

Expected: FAIL because the docs still describe XDG defaults.

- [ ] **Step 3: Update product and operator documentation**

Describe the new layout, explicit override precedence, safe first-run migration,
cache rebuild, and unchanged project-local `.kagent` directories. Remove claims
that XDG directories are current defaults.

- [ ] **Step 4: Verify documentation and focused suites**

Run: `.venv/bin/python -m pytest tests/test_docs.py tests/test_operations_docs.py tests/test_paths.py tests/test_npm_package.py -q`

Expected: PASS.

- [ ] **Step 5: Run full verification**

Run: `npm run check`

Run: `.venv/bin/python -m pytest -q`

Run: `.venv/bin/python -m ruff check src tests`

Run: `scripts/run_checks.sh`

Run: `git diff --check`

Expected: every command exits 0 with no test failures.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/architecture.md docs/operations.md docs/iteration_log.md tests/test_docs.py tests/test_operations_docs.py
git commit -m "docs: document unified kagent home"
```

- [ ] **Step 7: Push and monitor CI**

Push `main`, then verify the new GitHub Actions run completes successfully for
Python 3.9 and 3.12. If a check fails, inspect the exact job evidence before any
additional fix.
