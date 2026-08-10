#!/usr/bin/env node

import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  extractConfiguredEffortFromSnapshotTail,
  parseArgs,
  parseSnapshotEnvelope,
  runCli,
} from "../../reasoning-governor/scripts/reasoning-governor.mjs";

const isMain =
  process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));

if (isMain) {
  runCli();
}

export {
  extractConfiguredEffortFromSnapshotTail,
  parseArgs,
  parseSnapshotEnvelope,
};
