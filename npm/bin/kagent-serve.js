#!/usr/bin/env node
"use strict";

const { runPythonEntrypoint } = require("../lib/python-runner");

runPythonEntrypoint("kagent-serve", process.argv.slice(2));
