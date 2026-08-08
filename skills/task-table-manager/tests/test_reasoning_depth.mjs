import assert from "node:assert/strict";
import test from "node:test";

import {
  extractConfiguredEffortFromSnapshotTail,
  parseSnapshotEnvelope,
} from "../scripts/set-current-thread-reasoning-depth.mjs";

test("extracts the direct effort from latestThreadSettings", () => {
  const tail = JSON.stringify({
    turns: [
      {
        text: 'example: "latestThreadSettings":{"effort":"low"}',
      },
    ],
    latestThreadSettings: {
      model: "gpt-test",
      effort: "xhigh",
      collaborationMode: {
        settings: { reasoning_effort: "xhigh" },
      },
    },
  });

  assert.deepEqual(extractConfiguredEffortFromSnapshotTail(tail), {
    found: true,
    effort: "xhigh",
  });
});

test("distinguishes a null setting from an unreadable snapshot", () => {
  assert.deepEqual(
    extractConfiguredEffortFromSnapshotTail('{"latestThreadSettings":null}'),
    { found: true, effort: null },
  );
  assert.deepEqual(extractConfiguredEffortFromSnapshotTail('{"latestModel":"gpt-test"}'), {
    found: false,
    effort: null,
  });
});

test("parses snapshot envelope metadata without parsing conversation history", () => {
  const prefix =
    '{"type":"broadcast","method":"thread-stream-state-changed","params":' +
    '{"conversationId":"thread-123","hostId":"local","change":{"type":"snapshot"';
  const tail =
    '{"latestThreadSettings":{"model":"gpt-test","effort":"high"},"latestModel":"gpt-test"}}}';

  assert.deepEqual(parseSnapshotEnvelope(prefix, tail, 84_000_000), {
    conversationId: "thread-123",
    hostId: "local",
    bodyLength: 84_000_000,
    found: true,
    effort: "high",
  });
});
