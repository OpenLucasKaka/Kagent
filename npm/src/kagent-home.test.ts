import assert from "node:assert/strict";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  kagentCachePath,
  kagentStatePath,
  resolveKagentHome,
} from "./kagent-home";

test("defaults to the .kagent directory beneath HOME", () => {
  assert.equal(
    resolveKagentHome({ HOME: path.join(path.sep, "Users", "kaka") }),
    path.join(path.sep, "Users", "kaka", ".kagent"),
  );
});

test("expands a tilde-prefixed KAGENT_HOME", () => {
  const home = path.join(path.sep, "Users", "kaka");
  assert.equal(
    resolveKagentHome({ HOME: home, KAGENT_HOME: "~/shared-kagent" }),
    path.join(home, "shared-kagent"),
  );
});

test("rejects a relative KAGENT_HOME override", () => {
  assert.throws(
    () => resolveKagentHome({ KAGENT_HOME: "relative-kagent" }),
    /KAGENT_HOME.*absolute/i,
  );
});

test("builds state and cache paths beneath the resolved kagent home", () => {
  const env = { KAGENT_HOME: path.join(path.sep, "srv", "kagent") };
  assert.equal(
    kagentStatePath("pending-approvals", env),
    path.join(path.sep, "srv", "kagent", "state", "pending-approvals"),
  );
  assert.equal(
    kagentCachePath("npm-python", env),
    path.join(path.sep, "srv", "kagent", "cache", "npm-python"),
  );
});

test("falls back to the system home when HOME is missing or blank", () => {
  assert.equal(resolveKagentHome({}), path.resolve(os.homedir(), ".kagent"));
  assert.equal(
    resolveKagentHome({ HOME: "   " }),
    path.resolve(os.homedir(), ".kagent"),
  );
});

test("uses the system home for tilde overrides when HOME is unavailable", () => {
  assert.equal(resolveKagentHome({ KAGENT_HOME: "~" }), path.resolve(os.homedir()));
  assert.equal(
    resolveKagentHome({ HOME: "   ", KAGENT_HOME: "~/shared-kagent" }),
    path.resolve(os.homedir(), "shared-kagent"),
  );
});

test("rejects an empty or blank KAGENT_HOME override", () => {
  const home = path.join(path.sep, "Users", "kaka");
  assert.throws(
    () => resolveKagentHome({ HOME: home, KAGENT_HOME: "" }),
    /KAGENT_HOME.*empty/i,
  );
  assert.throws(
    () => resolveKagentHome({ HOME: home, KAGENT_HOME: "   " }),
    /KAGENT_HOME.*empty/i,
  );
});
