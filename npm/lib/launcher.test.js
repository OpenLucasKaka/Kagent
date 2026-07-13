"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const strict_1 = __importDefault(require("node:assert/strict"));
const node_test_1 = __importDefault(require("node:test"));
const { launchKagent } = require("./launcher");
function updateInfo(overrides = {}) {
    return {
        current: "1.0.0",
        latest: "1.1.0",
        channel: "latest",
        updateAvailable: true,
        checkedAt: "2026-07-13T00:00:00.000Z",
        ...overrides,
    };
}
function harness(overrides = {}) {
    const events = [];
    const stdout = [];
    const stderr = [];
    const exits = [];
    const checks = [];
    const upgrades = [];
    const deps = {
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
(0, node_test_1.default)("runs automatic preflight before the Ink UI", async () => {
    const context = harness();
    await launchKagent([], context.deps);
    strict_1.default.deepEqual(context.events, ["check", "ink"]);
    strict_1.default.equal(context.checks[0]?.force, false);
});
(0, node_test_1.default)("runs the same automatic preflight before classic Python", async () => {
    const pythonArgs = [];
    const context = harness({
        runPython(args) {
            context.events.push("python");
            pythonArgs.push(args);
        },
    });
    await launchKagent(["--classic"], context.deps);
    strict_1.default.deepEqual(context.events, ["check", "python"]);
    strict_1.default.deepEqual(pythonArgs, [[]]);
});
(0, node_test_1.default)("skips automatic checks for version, one-shot, piped input, and opt-out", async () => {
    for (const scenario of [
        { args: ["--version"], overrides: {} },
        { args: ["run", "hello"], overrides: {} },
        { args: [], overrides: { stdin: { isTTY: false } } },
        { args: [], overrides: { env: { KAGENT_NO_SELF_UPDATE: "yes" } } },
    ]) {
        const context = harness(scenario.overrides);
        await launchKagent(scenario.args, context.deps);
        strict_1.default.equal(context.events.includes("check"), false, JSON.stringify(scenario));
    }
});
(0, node_test_1.default)("prompts once for a newly discovered update and continues after decline", async () => {
    const prompts = [];
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
    strict_1.default.deepEqual(context.events, ["check", "prompt", "ink"]);
    strict_1.default.deepEqual(prompts, [updateInfo()]);
    strict_1.default.equal(context.upgrades.length, 0);
});
(0, node_test_1.default)("does not re-prompt for a cached update within the TTL", async () => {
    const context = harness({
        async checkForUpdate(options) {
            context.checks.push(options);
            context.events.push("check");
            return updateInfo({ skipped: true, reason: "ttl" });
        },
    });
    await launchKagent([], context.deps);
    strict_1.default.deepEqual(context.events, ["check", "ink"]);
});
(0, node_test_1.default)("accepting an automatic update upgrades then restarts without starting a UI", async () => {
    const restarted = [];
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
    strict_1.default.deepEqual(context.events, ["check", "prompt", "upgrade", "restart"]);
    strict_1.default.deepEqual(restarted, [["--classic"]]);
    strict_1.default.equal(context.upgrades[0]?.currentVersion, "1.0.0");
});
(0, node_test_1.default)("automatic check and install failures report briefly and continue", async () => {
    const checkFailure = harness({
        async checkForUpdate() { throw new Error("registry offline"); },
    });
    await launchKagent([], checkFailure.deps);
    strict_1.default.deepEqual(checkFailure.events, ["ink"]);
    strict_1.default.match(checkFailure.stderr.join(""), /^kagent: update check skipped: registry offline\n$/);
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
    strict_1.default.deepEqual(installFailure.events, ["check", "prompt", "upgrade", "ink"]);
    strict_1.default.match(installFailure.stderr.join(""), /^kagent: update failed: npm failed; continuing with 1\.0\.0\n$/);
});
(0, node_test_1.default)("update --check forces a check, emits stable JSON, and never starts Python", async () => {
    const context = harness({
        async checkForUpdate(options) {
            context.checks.push(options);
            context.events.push("check");
            return updateInfo({ cacheWarning: "cache unavailable", ignored: "value" });
        },
    });
    await launchKagent(["update", "--check"], context.deps);
    strict_1.default.deepEqual(context.events, ["check"]);
    strict_1.default.equal(context.checks[0]?.force, true);
    strict_1.default.deepEqual(JSON.parse(context.stdout.join("")), {
        current: "1.0.0",
        latest: "1.1.0",
        channel: "latest",
        updateAvailable: true,
        checkedAt: "2026-07-13T00:00:00.000Z",
        cacheWarning: "cache unavailable",
    });
});
(0, node_test_1.default)("upgrade forces install verification, emits stable JSON, and never starts Python", async () => {
    const context = harness();
    await launchKagent(["upgrade"], context.deps);
    strict_1.default.deepEqual(context.events, ["upgrade"]);
    strict_1.default.deepEqual(JSON.parse(context.stdout.join("")), {
        upgraded: true,
        installedVersion: "1.1.0",
    });
});
(0, node_test_1.default)("explicit update failures exit one without bootstrapping Python", async () => {
    for (const args of [["update", "--check"], ["upgrade"]]) {
        const context = harness({
            async checkForUpdate() { throw new Error("check failed"); },
            async runUpgrade() { throw new Error("install failed"); },
        });
        await launchKagent(args, context.deps);
        strict_1.default.deepEqual(context.exits, [1]);
        strict_1.default.equal(context.events.includes("python"), false);
        strict_1.default.match(context.stderr.join(""), /kagent: (update check|upgrade) failed:/);
    }
});
