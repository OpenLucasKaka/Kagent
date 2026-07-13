"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.launchKagent = launchKagent;
const node_child_process_1 = __importDefault(require("node:child_process"));
const node_fs_1 = __importDefault(require("node:fs"));
const node_path_1 = __importDefault(require("node:path"));
const node_readline_1 = __importDefault(require("node:readline"));
const update_manager_1 = require("./update-manager");
async function launchKagent(args, overrides = {}) {
    const deps = { ...createDefaultDependencies(), ...overrides };
    const currentVersion = deps.currentVersion();
    if (isUpdateCheckCommand(args)) {
        await runExplicitCheck(currentVersion, deps);
        return;
    }
    if (isUpgradeCommand(args)) {
        await runExplicitUpgrade(currentVersion, deps);
        return;
    }
    if (shouldRunAutomaticCheck(args, deps.env, deps.stdin)) {
        const restarted = await runAutomaticPreflight(args, currentVersion, deps);
        if (restarted) {
            return;
        }
    }
    const pythonArgs = classicArgs(args);
    if (shouldRunInk(args, deps.env, deps.stdin)) {
        await deps.runInk(args, {
            fallback: () => { void deps.runPython(pythonArgs); },
        });
        return;
    }
    await deps.runPython(pythonArgs);
}
function createDefaultDependencies() {
    const root = packageRoot();
    const runner = require("./python-runner");
    const ink = require("./ink-runner");
    const env = process.env;
    const managerDeps = {
        readState: async () => runner._internals.readUpdateState(env),
        writeState: async (state) => {
            runner._internals.writeUpdateState(state, env);
        },
        runInstall: async (argv) => {
            runChecked("npm", argv, root, env);
        },
        readInstalledVersion: async () => readPackageVersion(root),
    };
    return {
        env,
        stdin: process.stdin,
        stdout: process.stdout,
        stderr: process.stderr,
        currentVersion: () => readPackageVersion(root),
        checkForUpdate: (options) => (0, update_manager_1.checkForUpdate)({
            ...options,
            env,
            deps: managerDeps,
        }),
        runUpgrade: (options) => (0, update_manager_1.runUpgrade)({
            ...options,
            env,
            deps: managerDeps,
        }),
        promptUpdate: (info) => promptUpdate(info, process.stdin, process.stderr),
        runInk: (launchArgs, options) => ink.runKagentInk(launchArgs, options),
        runPython: (launchArgs) => runner.runPythonEntrypoint("kagent", launchArgs),
        restart: (launchArgs) => restartEntrypoint(launchArgs, env),
        exit: (code) => { process.exitCode = code; },
    };
}
async function runAutomaticPreflight(args, currentVersion, deps) {
    let info;
    try {
        info = await deps.checkForUpdate({ currentVersion, force: false, env: deps.env });
    }
    catch (error) {
        deps.stderr.write(`kagent: update check skipped: ${errorMessage(error)}\n`);
        return false;
    }
    if (info.latest === null) {
        deps.stderr.write(`kagent: update check skipped: ${info.error}\n`);
        return false;
    }
    if (!info.updateAvailable || (info.skipped && info.reason === "ttl")) {
        return false;
    }
    if (!(await deps.promptUpdate(info))) {
        return false;
    }
    try {
        const result = await deps.runUpgrade({ currentVersion, env: deps.env });
        if (!result.upgraded) {
            return false;
        }
    }
    catch (error) {
        deps.stderr.write(`kagent: update failed: ${errorMessage(error)}; continuing with ${currentVersion}\n`);
        return false;
    }
    deps.restart(args);
    return true;
}
async function runExplicitCheck(currentVersion, deps) {
    try {
        const info = await deps.checkForUpdate({
            currentVersion,
            force: true,
            env: deps.env,
        });
        if (info.latest === null) {
            throw new Error("forced update check was skipped");
        }
        deps.stdout.write(`${JSON.stringify({
            current: info.current,
            latest: info.latest,
            channel: info.channel,
            updateAvailable: info.updateAvailable,
            checkedAt: info.checkedAt,
            ...(info.cacheWarning ? { cacheWarning: info.cacheWarning } : {}),
        })}\n`);
    }
    catch (error) {
        deps.stderr.write(`kagent: update check failed: ${errorMessage(error)}\n`);
        deps.exit(1);
    }
}
async function runExplicitUpgrade(currentVersion, deps) {
    try {
        const result = await deps.runUpgrade({ currentVersion, env: deps.env });
        deps.stdout.write(`${JSON.stringify({
            upgraded: result.upgraded,
            installedVersion: result.installedVersion,
        })}\n`);
    }
    catch (error) {
        deps.stderr.write(`kagent: upgrade failed: ${errorMessage(error)}\n`);
        deps.exit(1);
    }
}
function shouldRunAutomaticCheck(args, env, stdin) {
    return Boolean(stdin.isTTY) &&
        !envFlagEnabled(env.KAGENT_NO_SELF_UPDATE) &&
        (args.length === 0 || (args.length === 1 && args[0] === "--classic"));
}
function shouldRunInk(args, env, stdin) {
    return args.length === 0 && !env.KAGENT_CLASSIC_UI && Boolean(stdin.isTTY);
}
function envFlagEnabled(value) {
    if (!value) {
        return false;
    }
    return !["0", "false", "no"].includes(value.toLowerCase());
}
function isUpdateCheckCommand(args) {
    return args.length === 2 && args[0] === "update" && args[1] === "--check";
}
function isUpgradeCommand(args) {
    return args.length === 1 && args[0] === "upgrade";
}
function classicArgs(args) {
    return args.filter((arg) => arg !== "--classic");
}
function packageRoot() {
    return node_path_1.default.resolve(__dirname, "..", "..");
}
function readPackageVersion(root) {
    const packageJson = JSON.parse(node_fs_1.default.readFileSync(node_path_1.default.join(root, "package.json"), "utf8"));
    if (typeof packageJson.version !== "string" || !packageJson.version) {
        throw new Error("package.json does not declare a version");
    }
    return packageJson.version;
}
function runChecked(command, argv, cwd, env) {
    const result = node_child_process_1.default.spawnSync(command, [...argv], {
        cwd,
        env,
        encoding: "utf8",
        stdio: "inherit",
    });
    if (result.error) {
        throw result.error;
    }
    if (result.status !== 0) {
        throw new Error(`${command} ${argv.join(" ")} exited with ${result.status ?? 1}`);
    }
}
function promptUpdate(info, input, output) {
    return new Promise((resolve) => {
        const prompt = `kagent update available: current=${info.current} latest=${info.latest} channel=${info.channel}\n` +
            "Update now? [Y/n] ";
        const rl = node_readline_1.default.createInterface({ input, output });
        rl.question(prompt, (answer) => {
            rl.close();
            const normalized = answer.trim().toLowerCase();
            resolve(normalized === "" || normalized === "y" || normalized === "yes");
        });
    });
}
function restartEntrypoint(args, env) {
    const binPath = process.argv[1];
    if (!binPath) {
        throw new Error("unable to determine current kagent executable");
    }
    const result = node_child_process_1.default.spawnSync(process.execPath, [binPath, ...args], {
        env,
        stdio: "inherit",
    });
    if (result.error) {
        throw result.error;
    }
    process.exit(result.status ?? 1);
}
function errorMessage(error) {
    return error instanceof Error ? error.message : String(error);
}
module.exports = { launchKagent };
