"use strict";

const childProcess = require("child_process");
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..", "..");
const outputPath = path.join(root, "npm", "build-info.json");

function gitOutput(args) {
  const result = childProcess.spawnSync("git", args, {
    cwd: root,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"]
  });
  if (result.status !== 0) {
    return "";
  }
  return String(result.stdout || "").trim();
}

const info = {
  headSha: gitOutput(["rev-parse", "HEAD"]),
  remoteUrl: gitOutput(["config", "--get", "remote.origin.url"]),
  generatedAt: new Date().toISOString()
};

fs.writeFileSync(outputPath, `${JSON.stringify(info, null, 2)}\n`, {
  encoding: "utf8",
  mode: 0o644
});
