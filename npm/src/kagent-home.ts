import os from "node:os";
import path from "node:path";

function requiredHome(env: NodeJS.ProcessEnv): string {
  const home = env.HOME?.trim();
  return home || os.homedir();
}

export function resolveKagentHome(
  env: NodeJS.ProcessEnv = process.env,
): string {
  const configured = env.KAGENT_HOME;
  if (Object.prototype.hasOwnProperty.call(env, "KAGENT_HOME")) {
    if (!configured?.trim()) {
      throw new Error("KAGENT_HOME must not be empty");
    }
    if (configured === "~") {
      return path.resolve(requiredHome(env));
    }
    if (configured.startsWith("~/")) {
      return path.resolve(requiredHome(env), configured.slice(2));
    }
    if (!path.isAbsolute(configured)) {
      throw new Error("KAGENT_HOME must be an absolute or tilde-prefixed path");
    }
    return path.resolve(configured);
  }
  return path.resolve(requiredHome(env), ".kagent");
}

export function kagentStatePath(
  name: string,
  env: NodeJS.ProcessEnv = process.env,
): string {
  return path.join(resolveKagentHome(env), "state", name);
}

export function kagentCachePath(
  name: string,
  env: NodeJS.ProcessEnv = process.env,
): string {
  return path.join(resolveKagentHome(env), "cache", name);
}
