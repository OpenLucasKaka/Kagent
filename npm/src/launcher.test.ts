import assert from "node:assert/strict";
import test from "node:test";

type LaunchOptions = {
  force?: boolean;
  currentVersion: string;
};

type UpgradeResult = {
  upgraded: boolean;
  installedVersion: string;
};

type TestDependencies = {
  env: NodeJS.ProcessEnv;
  stdin: { isTTY?: boolean };
  stdout: { write(value: string): boolean };
  stderr: { write(value: string): boolean };
  currentVersion(): string;
  checkForUpdate(options: LaunchOptions): Promise<Record<string, unknown>>;
  runUpgrade(options: LaunchOptions): Promise<UpgradeResult>;
  promptUpdate(info: Record<string, unknown>): Promise<boolean>;
  runInk(args: string[], options: { fallback: () => void }): void | Promise<void>;
  runPython(args: string[]): void;
  restart(args: string[]): void;
  exit(code: number): void;
};

const { launchKagent } = require("./launcher") as {
  launchKagent(args: string[], deps?: Partial<TestDependencies>): Promise<void>;
};

function updateInfo(overrides: Record<string, unknown> = {}) {
  return {
    current: "1.0.0",
    latest: "1.1.0",
    channel: "latest",
    updateAvailable: true,
    checkedAt: "2026-07-13T00:00:00.000Z",
    ...overrides,
  };
}

function harness(overrides: Partial<TestDependencies> = {}) {
  const events: string[] = [];
  const stdout: string[] = [];
  const stderr: string[] = [];
  const exits: number[] = [];
  const checks: LaunchOptions[] = [];
  const upgrades: LaunchOptions[] = [];
  const deps: TestDependencies = {
    env: {},
    stdin: { isTTY: true },
    stdout: { write(value) { stdout.push(value); return true; } },
    stderr: { write(value) { stderr.push(value); return true; } },
    currentVersion: () => "1.0.0",
    async checkForUpdate(options) {
      checks.push(options);
      events.push("check");
      return updateInfo({ updateAvailable: false, latest: "1.0.0" });
    },
    async runUpgrade(options) {
      upgrades.push(options);
      events.push("upgrade");
      return { upgraded: true, installedVersion: "1.1.0" };
    },
    async promptUpdate() {
      events.push("prompt");
      return false;
    },
    runInk() { events.push("ink"); },
    runPython() { events.push("python"); },
    restart() { events.push("restart"); },
    exit(code) { exits.push(code); },
    ...overrides,
  };
  return { deps, events, stdout, stderr, exits, checks, upgrades };
}

test("runs automatic preflight before the Ink UI", async () => {
  const context = harness();

  await launchKagent([], context.deps);

  assert.deepEqual(context.events, ["check", "ink"]);
  assert.equal(context.checks[0]?.force, false);
});

test("runs the same automatic preflight before classic Python", async () => {
  const pythonArgs: string[][] = [];
  const context = harness({
    runPython(args) {
      context.events.push("python");
      pythonArgs.push(args);
    },
  });

  await launchKagent(["--classic"], context.deps);

  assert.deepEqual(context.events, ["check", "python"]);
  assert.deepEqual(pythonArgs, [[]]);
});

test("skips automatic checks for version, one-shot, piped input, and opt-out", async () => {
  for (const scenario of [
    { args: ["--version"], overrides: {} },
    { args: ["run", "hello"], overrides: {} },
    { args: [], overrides: { stdin: { isTTY: false } } },
    { args: [], overrides: { env: { KAGENT_NO_SELF_UPDATE: "yes" } } },
  ]) {
    const context = harness(scenario.overrides as Partial<TestDependencies>);
    await launchKagent(scenario.args, context.deps);
    assert.equal(context.events.includes("check"), false, JSON.stringify(scenario));
  }
});

test("prompts once for a newly discovered update and continues after decline", async () => {
  const prompts: Array<Record<string, unknown>> = [];
  const context = harness({
    async checkForUpdate(options) {
      context.checks.push(options);
      context.events.push("check");
      return updateInfo();
    },
    async promptUpdate(info) {
      context.events.push("prompt");
      prompts.push(info);
      return false;
    },
  });

  await launchKagent([], context.deps);

  assert.deepEqual(context.events, ["check", "prompt", "ink"]);
  assert.deepEqual(prompts, [updateInfo()]);
  assert.equal(context.upgrades.length, 0);
});

test("does not re-prompt for a cached update within the TTL", async () => {
  const context = harness({
    async checkForUpdate(options) {
      context.checks.push(options);
      context.events.push("check");
      return updateInfo({ skipped: true, reason: "ttl" });
    },
  });

  await launchKagent([], context.deps);

  assert.deepEqual(context.events, ["check", "ink"]);
});

test("accepting an automatic update upgrades then restarts without starting a UI", async () => {
  const restarted: string[][] = [];
  const context = harness({
    async checkForUpdate(options) {
      context.checks.push(options);
      context.events.push("check");
      return updateInfo();
    },
    async promptUpdate() {
      context.events.push("prompt");
      return true;
    },
    restart(args) {
      context.events.push("restart");
      restarted.push(args);
    },
  });

  await launchKagent(["--classic"], context.deps);

  assert.deepEqual(context.events, ["check", "prompt", "upgrade", "restart"]);
  assert.deepEqual(restarted, [["--classic"]]);
  assert.equal(context.upgrades[0]?.currentVersion, "1.0.0");
});

test("automatic check and install failures report briefly and continue", async () => {
  const checkFailure = harness({
    async checkForUpdate() { throw new Error("registry offline"); },
  });
  await launchKagent([], checkFailure.deps);
  assert.deepEqual(checkFailure.events, ["ink"]);
  assert.match(checkFailure.stderr.join(""), /^kagent: update check skipped: registry offline\n$/);

  const installFailure = harness({
    async checkForUpdate(options) {
      installFailure.checks.push(options);
      installFailure.events.push("check");
      return updateInfo();
    },
    async promptUpdate() { installFailure.events.push("prompt"); return true; },
    async runUpgrade() { installFailure.events.push("upgrade"); throw new Error("npm failed"); },
  });
  await launchKagent([], installFailure.deps);
  assert.deepEqual(installFailure.events, ["check", "prompt", "upgrade", "ink"]);
  assert.match(installFailure.stderr.join(""), /^kagent: update failed: npm failed; continuing with 1\.0\.0\n$/);
});

test("update --check forces a check, emits stable JSON, and never starts Python", async () => {
  const context = harness({
    async checkForUpdate(options) {
      context.checks.push(options);
      context.events.push("check");
      return updateInfo({ cacheWarning: "cache unavailable", ignored: "value" });
    },
  });

  await launchKagent(["update", "--check"], context.deps);

  assert.deepEqual(context.events, ["check"]);
  assert.equal(context.checks[0]?.force, true);
  assert.deepEqual(JSON.parse(context.stdout.join("")), {
    current: "1.0.0",
    latest: "1.1.0",
    channel: "latest",
    updateAvailable: true,
    checkedAt: "2026-07-13T00:00:00.000Z",
    cacheWarning: "cache unavailable",
  });
});

test("upgrade forces install verification, emits stable JSON, and never starts Python", async () => {
  const context = harness();

  await launchKagent(["upgrade"], context.deps);

  assert.deepEqual(context.events, ["upgrade"]);
  assert.deepEqual(JSON.parse(context.stdout.join("")), {
    upgraded: true,
    installedVersion: "1.1.0",
  });
});

test("explicit update failures exit one without bootstrapping Python", async () => {
  for (const args of [["update", "--check"], ["upgrade"]]) {
    const context = harness({
      async checkForUpdate() { throw new Error("check failed"); },
      async runUpgrade() { throw new Error("install failed"); },
    });

    await launchKagent(args, context.deps);

    assert.deepEqual(context.exits, [1]);
    assert.equal(context.events.includes("python"), false);
    assert.match(context.stderr.join(""), /kagent: (update check|upgrade) failed:/);
  }
});
