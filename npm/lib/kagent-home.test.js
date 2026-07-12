"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const strict_1 = __importDefault(require("node:assert/strict"));
const node_os_1 = __importDefault(require("node:os"));
const node_path_1 = __importDefault(require("node:path"));
const node_test_1 = __importDefault(require("node:test"));
const kagent_home_1 = require("./kagent-home");
(0, node_test_1.default)("defaults to the .kagent directory beneath HOME", () => {
    strict_1.default.equal((0, kagent_home_1.resolveKagentHome)({ HOME: node_path_1.default.join(node_path_1.default.sep, "Users", "kaka") }), node_path_1.default.join(node_path_1.default.sep, "Users", "kaka", ".kagent"));
});
(0, node_test_1.default)("expands a tilde-prefixed KAGENT_HOME", () => {
    const home = node_path_1.default.join(node_path_1.default.sep, "Users", "kaka");
    strict_1.default.equal((0, kagent_home_1.resolveKagentHome)({ HOME: home, KAGENT_HOME: "~/shared-kagent" }), node_path_1.default.join(home, "shared-kagent"));
});
(0, node_test_1.default)("rejects a relative KAGENT_HOME override", () => {
    strict_1.default.throws(() => (0, kagent_home_1.resolveKagentHome)({ KAGENT_HOME: "relative-kagent" }), /KAGENT_HOME.*absolute/i);
});
(0, node_test_1.default)("builds state and cache paths beneath the resolved kagent home", () => {
    const env = { KAGENT_HOME: node_path_1.default.join(node_path_1.default.sep, "srv", "kagent") };
    strict_1.default.equal((0, kagent_home_1.kagentStatePath)("pending-approvals", env), node_path_1.default.join(node_path_1.default.sep, "srv", "kagent", "state", "pending-approvals"));
    strict_1.default.equal((0, kagent_home_1.kagentCachePath)("npm-python", env), node_path_1.default.join(node_path_1.default.sep, "srv", "kagent", "cache", "npm-python"));
});
(0, node_test_1.default)("falls back to the system home when HOME is missing or blank", () => {
    strict_1.default.equal((0, kagent_home_1.resolveKagentHome)({}), node_path_1.default.resolve(node_os_1.default.homedir(), ".kagent"));
    strict_1.default.equal((0, kagent_home_1.resolveKagentHome)({ HOME: "   " }), node_path_1.default.resolve(node_os_1.default.homedir(), ".kagent"));
});
(0, node_test_1.default)("uses the system home for tilde overrides when HOME is unavailable", () => {
    strict_1.default.equal((0, kagent_home_1.resolveKagentHome)({ KAGENT_HOME: "~" }), node_path_1.default.resolve(node_os_1.default.homedir()));
    strict_1.default.equal((0, kagent_home_1.resolveKagentHome)({ HOME: "   ", KAGENT_HOME: "~/shared-kagent" }), node_path_1.default.resolve(node_os_1.default.homedir(), "shared-kagent"));
});
(0, node_test_1.default)("rejects an empty or blank KAGENT_HOME override", () => {
    const home = node_path_1.default.join(node_path_1.default.sep, "Users", "kaka");
    strict_1.default.throws(() => (0, kagent_home_1.resolveKagentHome)({ HOME: home, KAGENT_HOME: "" }), /KAGENT_HOME.*empty/i);
    strict_1.default.throws(() => (0, kagent_home_1.resolveKagentHome)({ HOME: home, KAGENT_HOME: "   " }), /KAGENT_HOME.*empty/i);
});
