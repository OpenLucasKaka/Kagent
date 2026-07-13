#!/usr/bin/env node
"use strict";

const { launchKagent } = require("../lib/launcher");

void launchKagent(process.argv.slice(2));
