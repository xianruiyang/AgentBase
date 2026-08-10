import assert from "node:assert/strict";
import test from "node:test";

import {
  extractConfiguredEffortFromSnapshotTail,
  parseArgs,
} from "../scripts/set-current-thread-reasoning-depth.mjs";

test("legacy task-table entry forwards the reasoning-governor contract", () => {
  assert.equal(parseArgs(["--effort", "max"]).action, "set");
  assert.equal(parseArgs(["--effort", "max"]).effort, "max");
  assert.deepEqual(
    extractConfiguredEffortFromSnapshotTail(
      '{"latestThreadSettings":{"model":"gpt-test","effort":"high"}}',
    ),
    { found: true, effort: "high" },
  );
});
