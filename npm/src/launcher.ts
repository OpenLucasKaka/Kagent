import childProcess from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";

import {
  checkForUpdate,
  runUpgrade,
  type CheckForUpdateOptions,
  type RunUpgradeOptions,
  type UpdateCheckResult,
  type UpdateCheckState,
  type UpgradeResult,
} from "./update-manager";

type Writable = Pick<NodeJS.WritableStream, "write">;
type ReadableTTY = Pick<NodeJS.ReadStream, "isTTY">;

type InkOptions = { fallback: () => void };

interface PythonRunner {
  runPythonEntrypoint(commandName: string, args: string[]): void | Promise<void>;
  _internals: {
    readUpdateState(env?: NodeJS.ProcessEnv): unknown;
    writeUpdateState(state: UpdateCheckState, env?: NodeJS.ProcessEnv): void;
  };
}

interface InkRunner {
  runKagentInk(args: string[], options: InkOptions): void | Promise<void>;
}

export interface LauncherDependencies {
  env: NodeJS.ProcessEnv;
  stdin: ReadableTTY;
  stdout: Writable;
  stderr: Writable;
  currentVersion(): string;
  checkForUpdate(options: CheckForUpdateOptions): Promise<UpdateCheckResult>;
  runUpgrade(options: RunUpgradeOptions): Promise<UpgradeResult>;
  promptUpdate(info: UpdateCheckResult): Promise<boolean>;
  runInk(args: string[], options: InkOptions): void | Promise<void>;
  runPython(args: string[]): void | Promise<void>;
  restart(args: string[]): void;
  exit(code: number): void;
}

export async function launchKagent(
  args: string[],
  overrides: Partial<LauncherDependencies> = {},
): Promise<void> {
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

function createDefaultDependencies(): LauncherDependencies {
  const root = packageRoot();
  const runner = require("./python-runner") as PythonRunner;
  const ink = require("./ink-runner") as InkRunner;
  const env = process.env;
  const managerDeps = {
    readState: async () => runner._internals.readUpdateState(env) as UpdateCheckState,
    writeState: async (state: UpdateCheckState) => {
      runner._internals.writeUpdateState(state, env);
    },
    runInstall: async (argv: readonly string[]) => {
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
    checkForUpdate: (options) => checkForUpdate({
      ...options,
      env,
      deps: managerDeps,
    }),
    runUpgrade: (options) => runUpgrade({
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

async function runAutomaticPreflight(
  args: string[],
  currentVersion: string,
  deps: LauncherDependencies,
): Promise<boolean> {
  let info: UpdateCheckResult;
  try {
    info = await deps.checkForUpdate({ currentVersion, force: false, env: deps.env });
  } catch (error) {
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
  } catch (error) {
    deps.stderr.write(
      `kagent: update failed: ${errorMessage(error)}; continuing with ${currentVersion}\n`,
    );
    return false;
  }
  deps.restart(args);
  return true;
}

async function runExplicitCheck(
  currentVersion: string,
  deps: LauncherDependencies,
): Promise<void> {
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
  } catch (error) {
    deps.stderr.write(`kagent: update check failed: ${errorMessage(error)}\n`);
    deps.exit(1);
  }
}

async function runExplicitUpgrade(
  currentVersion: string,
  deps: LauncherDependencies,
): Promise<void> {
  try {
    const result = await deps.runUpgrade({ currentVersion, env: deps.env });
    deps.stdout.write(`${JSON.stringify({
      upgraded: result.upgraded,
      installedVersion: result.installedVersion,
    })}\n`);
  } catch (error) {
    deps.stderr.write(`kagent: upgrade failed: ${errorMessage(error)}\n`);
    deps.exit(1);
  }
}

function shouldRunAutomaticCheck(
  args: string[],
  env: NodeJS.ProcessEnv,
  stdin: ReadableTTY,
): boolean {
  return Boolean(stdin.isTTY) &&
    !envFlagEnabled(env.KAGENT_NO_SELF_UPDATE) &&
    (args.length === 0 || (args.length === 1 && args[0] === "--classic"));
}

function shouldRunInk(
  args: string[],
  env: NodeJS.ProcessEnv,
  stdin: ReadableTTY,
): boolean {
  return args.length === 0 && !env.KAGENT_CLASSIC_UI && Boolean(stdin.isTTY);
}

function envFlagEnabled(value: string | undefined): boolean {
  if (!value) {
    return false;
  }
  return !["0", "false", "no"].includes(value.toLowerCase());
}

function isUpdateCheckCommand(args: string[]): boolean {
  return args.length === 2 && args[0] === "update" && args[1] === "--check";
}

function isUpgradeCommand(args: string[]): boolean {
  return args.length === 1 && args[0] === "upgrade";
}

function classicArgs(args: string[]): string[] {
  return args.filter((arg) => arg !== "--classic");
}

function packageRoot(): string {
  return path.resolve(__dirname, "..", "..");
}

function readPackageVersion(root: string): string {
  const packageJson = JSON.parse(
    fs.readFileSync(path.join(root, "package.json"), "utf8"),
  ) as { version?: unknown };
  if (typeof packageJson.version !== "string" || !packageJson.version) {
    throw new Error("package.json does not declare a version");
  }
  return packageJson.version;
}

function runChecked(
  command: string,
  argv: readonly string[],
  cwd: string,
  env: NodeJS.ProcessEnv,
): void {
  const result = childProcess.spawnSync(command, [...argv], {
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

function promptUpdate(
  info: UpdateCheckResult,
  input: NodeJS.ReadStream,
  output: NodeJS.WriteStream,
): Promise<boolean> {
  return new Promise((resolve) => {
    const prompt =
      `kagent update available: current=${info.current} latest=${info.latest} channel=${info.channel}\n` +
      "Update now? [Y/n] ";
    const rl = readline.createInterface({ input, output });
    rl.question(prompt, (answer) => {
      rl.close();
      const normalized = answer.trim().toLowerCase();
      resolve(normalized === "" || normalized === "y" || normalized === "yes");
    });
  });
}

function restartEntrypoint(args: string[], env: NodeJS.ProcessEnv): void {
  const binPath = process.argv[1];
  if (!binPath) {
    throw new Error("unable to determine current kagent executable");
  }
  const result = childProcess.spawnSync(process.execPath, [binPath, ...args], {
    env,
    stdio: "inherit",
  });
  if (result.error) {
    throw result.error;
  }
  process.exit(result.status ?? 1);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

module.exports = { launchKagent };
