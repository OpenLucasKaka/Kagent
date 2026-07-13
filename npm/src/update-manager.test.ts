import assert from "node:assert/strict";
import test from "node:test";

import {
  NPM_REGISTRY_URL,
  UPDATE_CHECK_TIMEOUT_MS,
  UPDATE_CHECK_TTL_MS,
  checkForUpdate,
  compareSemVer,
  resolveUpdateChannel,
  runUpgrade,
  type UpdateCheckState,
  type UpdateManagerDeps,
} from "./update-manager";

function registryResponse(version: string, tag: "latest" | "next" = "latest") {
  return {
    ok: true,
    status: 200,
    async json() {
      return { "dist-tags": { [tag]: version } };
    },
  };
}

test("maps stable/latest and beta/next update channel configuration", () => {
  assert.equal(UPDATE_CHECK_TIMEOUT_MS, 3_000);
  assert.equal(UPDATE_CHECK_TTL_MS, 24 * 60 * 60 * 1_000);
  assert.equal(resolveUpdateChannel({}), "latest");
  assert.equal(resolveUpdateChannel({ KAGENT_UPDATE_CHANNEL: "stable" }), "latest");
  assert.equal(resolveUpdateChannel({ KAGENT_UPDATE_CHANNEL: "latest" }), "latest");
  assert.equal(resolveUpdateChannel({ KAGENT_UPDATE_CHANNEL: "beta" }), "next");
  assert.equal(resolveUpdateChannel({ KAGENT_UPDATE_CHANNEL: "next" }), "next");
  assert.throws(
    () => resolveUpdateChannel({ KAGENT_UPDATE_CHANNEL: "nightly" }),
    /KAGENT_UPDATE_CHANNEL.*nightly.*stable.*beta/i,
  );
});

test("compares valid SemVer including prerelease identifiers", () => {
  assert.equal(compareSemVer("1.10.0", "1.9.9"), 1);
  assert.equal(compareSemVer("2.0.0", "10.0.0"), -1);
  assert.equal(compareSemVer("1.0.0", "1.0.0-beta.99"), 1);
  assert.equal(compareSemVer("1.0.0-beta.11", "1.0.0-beta.2"), 1);
  assert.equal(compareSemVer("1.0.0-beta.2", "1.0.0-beta.alpha"), -1);
  assert.equal(compareSemVer("1.0.0+build.1", "1.0.0+build.2"), 0);
});

test("rejects invalid SemVer", () => {
  for (const version of ["1.2", "v1.2.3", "01.2.3", "1.2.3-01", "1.2.x", ""]) {
    assert.throws(() => compareSemVer(version, "1.0.0"), /invalid semver/i);
  }
});

test("fetches the fixed registry URL and selected dist-tag", async () => {
  const calls: Array<{ url: string; signal: AbortSignal | undefined }> = [];
  const result = await checkForUpdate({
    currentVersion: "1.2.3",
    channel: "next",
    force: true,
    deps: {
      now: () => new Date("2026-07-13T00:00:00.000Z"),
      fetch: async (url, init) => {
        calls.push({ url: String(url), signal: init?.signal ?? undefined });
        return registryResponse("1.3.0-beta.1", "next");
      },
    },
  });

  assert.deepEqual(calls.map((call) => call.url), [NPM_REGISTRY_URL]);
  assert.equal(calls[0]?.signal instanceof AbortSignal, true);
  assert.deepEqual(result, {
    current: "1.2.3",
    latest: "1.3.0-beta.1",
    channel: "next",
    updateAvailable: true,
    checkedAt: "2026-07-13T00:00:00.000Z",
  });
});

test("uses a fresh same-channel state without a network request", async () => {
  let fetchCalls = 0;
  const state: UpdateCheckState = {
    channel: "latest",
    latest: "1.4.0",
    checkedAt: "2026-07-12T12:00:01.000Z",
  };
  const result = await checkForUpdate({
    currentVersion: "1.3.0",
    deps: {
      now: () => new Date("2026-07-13T12:00:00.000Z"),
      readState: async () => state,
      fetch: async () => {
        fetchCalls += 1;
        return registryResponse("9.0.0");
      },
    },
  });

  assert.equal(fetchCalls, 0);
  assert.deepEqual(result, {
    current: "1.3.0",
    latest: "1.4.0",
    channel: "latest",
    updateAvailable: true,
    checkedAt: state.checkedAt,
    skipped: true,
    reason: "ttl",
  });
});

test("force ignores TTL and persists a successful check", async () => {
  const writes: UpdateCheckState[] = [];
  const result = await checkForUpdate({
    currentVersion: "1.3.0",
    force: true,
    deps: {
      now: () => new Date("2026-07-13T12:00:00.000Z"),
      readState: async () => ({
        channel: "latest",
        latest: "1.4.0",
        checkedAt: "2026-07-13T11:59:59.000Z",
      }),
      writeState: async (state) => {
        writes.push(state);
      },
      fetch: async () => registryResponse("1.5.0"),
    },
  });

  assert.equal(result.latest, "1.5.0");
  assert.deepEqual(writes, [{
    channel: "latest",
    latest: "1.5.0",
    checkedAt: "2026-07-13T12:00:00.000Z",
  }]);
});

test("rejects malformed registry metadata", async () => {
  const malformed = [
    null,
    [],
    {},
    { "dist-tags": null },
    { "dist-tags": { latest: "" } },
    { "dist-tags": { latest: "not-a-version" } },
  ];

  for (const payload of malformed) {
    await assert.rejects(
      checkForUpdate({
        currentVersion: "1.0.0",
        force: true,
        deps: {
          fetch: async () => ({
            ok: true,
            status: 200,
            async json() { return payload; },
          }),
        },
      }),
      /registry metadata|dist-tags|semver/i,
    );
  }
});

test("returns a skipped result on automatic network errors and throws when forced", async () => {
  const deps: UpdateManagerDeps = {
    now: () => new Date("2026-07-13T00:00:00.000Z"),
    fetch: async () => { throw new Error("socket closed"); },
  };

  assert.deepEqual(
    await checkForUpdate({ currentVersion: "1.0.0", deps }),
    {
      current: "1.0.0",
      latest: null,
      channel: "latest",
      updateAvailable: false,
      checkedAt: "2026-07-13T00:00:00.000Z",
      skipped: true,
      reason: "network-error",
      error: "socket closed",
    },
  );
  await assert.rejects(
    checkForUpdate({ currentVersion: "1.0.0", force: true, deps }),
    /unable to check.*socket closed/i,
  );
});

test("treats metadata body network failures as skippable", async () => {
  const deps: UpdateManagerDeps = {
    now: () => new Date("2026-07-13T00:00:00.000Z"),
    fetch: async () => ({
      ok: true,
      status: 200,
      async json() { throw new TypeError("terminated"); },
    }),
  };

  assert.deepEqual(
    await checkForUpdate({ currentVersion: "1.0.0", deps }),
    {
      current: "1.0.0",
      latest: null,
      channel: "latest",
      updateAvailable: false,
      checkedAt: "2026-07-13T00:00:00.000Z",
      skipped: true,
      reason: "network-error",
      error: "terminated",
    },
  );
  await assert.rejects(
    checkForUpdate({ currentVersion: "1.0.0", force: true, deps }),
    /unable to check.*terminated/i,
  );
});

test("aborts registry requests after the configured timeout", async () => {
  await assert.rejects(
    checkForUpdate({
      currentVersion: "1.0.0",
      force: true,
      deps: {
        timeoutMs: 5,
        fetch: (_url, init) => new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new Error("aborted")));
        }),
      },
    }),
    /unable to check.*timed out.*5ms/i,
  );
});

test("keeps the registry timeout active while reading metadata", async () => {
  await assert.rejects(
    checkForUpdate({
      currentVersion: "1.0.0",
      force: true,
      deps: {
        timeoutMs: 5,
        fetch: async () => ({
          ok: true,
          status: 200,
          json: () => new Promise((_resolve, reject) => {
            setTimeout(() => reject(new Error("body stalled")), 20);
          }),
        }),
      },
    }),
    /unable to check.*timed out.*5ms/i,
  );
});

test("upgrades using fixed npm argv for each channel", async () => {
  for (const [channel, expectedSpec, latest] of [
    ["latest", "@openlucaskaka/kagent@latest", "2.0.0"],
    ["next", "@openlucaskaka/kagent@next", "2.1.0-beta.1"],
  ] as const) {
    const installs: ReadonlyArray<string>[] = [];
    const result = await runUpgrade({
      currentVersion: "1.0.0",
      channel,
      deps: {
        readState: async () => {
          throw new Error("runUpgrade must force the update check");
        },
        fetch: async () => registryResponse(latest, channel),
        runInstall: async (argv) => { installs.push(argv); },
        readInstalledVersion: async () => latest,
      },
    });

    assert.deepEqual(installs, [["install", "--global", expectedSpec]]);
    assert.equal(result.latest, latest);
  }
});

test("does not install when current is latest and validates the installed version", async () => {
  let installs = 0;
  const noUpdate = await runUpgrade({
    currentVersion: "2.0.0",
    deps: {
      fetch: async () => registryResponse("2.0.0"),
      runInstall: async () => { installs += 1; },
      readInstalledVersion: async () => "2.0.0",
    },
  });
  assert.equal(installs, 0);
  assert.equal(noUpdate.updateAvailable, false);

  await assert.rejects(
    runUpgrade({
      currentVersion: "1.0.0",
      deps: {
        fetch: async () => registryResponse("2.0.0"),
        runInstall: async () => undefined,
        readInstalledVersion: async () => "1.9.9",
      },
    }),
    /installed version 1\.9\.9.*expected.*2\.0\.0/i,
  );
});

test("reports the fixed target when installation fails", async () => {
  await assert.rejects(
    runUpgrade({
      currentVersion: "1.0.0",
      deps: {
        fetch: async () => registryResponse("2.0.0"),
        runInstall: async () => { throw new Error("permission denied"); },
        readInstalledVersion: async () => "1.0.0",
      },
    }),
    /failed to install @openlucaskaka\/kagent@latest: permission denied/i,
  );
});
