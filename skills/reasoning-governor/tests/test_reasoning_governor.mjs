import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  extractConfiguredEffortFromSnapshotTail,
  parseArgs,
  parseSnapshotEnvelope,
  readReasoningEffort,
  updateReasoningEffort,
} from "../scripts/reasoning-governor.mjs";

function encodeFrame(message) {
  const json = JSON.stringify(message);
  const payload = Buffer.from(json, "utf8");
  const frame = Buffer.allocUnsafe(4 + payload.length);
  frame.writeUInt32LE(payload.length, 0);
  payload.copy(frame, 4);
  return frame;
}

function attachMessageReader(socket, onMessage) {
  let pending = Buffer.alloc(0);
  socket.on("data", (chunk) => {
    pending = Buffer.concat([pending, chunk]);
    while (pending.length >= 4) {
      const bodyLength = pending.readUInt32LE(0);
      if (pending.length < 4 + bodyLength) {
        return;
      }
      const body = pending.subarray(4, 4 + bodyLength).toString("utf8");
      pending = pending.subarray(4 + bodyLength);
      onMessage(JSON.parse(body), socket);
    }
  });
}

async function withFakeIpc(onMessage, run) {
  const id = `reasoning-governor-${process.pid}-${crypto.randomUUID()}`;
  const pipePath =
    process.platform === "win32"
      ? `\\\\.\\pipe\\${id}`
      : path.join(os.tmpdir(), `${id}.sock`);
  const server = net.createServer((socket) => attachMessageReader(socket, onMessage));

  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(pipePath, resolve);
  });
  try {
    return await run(pipePath);
  } finally {
    await new Promise((resolve, reject) => {
      server.close((error) => (error ? reject(error) : resolve()));
    });
    if (process.platform !== "win32") {
      await fs.rm(pipePath, { force: true });
    }
  }
}

function respondToInitialize(message, socket) {
  if (message.type !== "request" || message.method !== "initialize") {
    return false;
  }
  socket.write(
    encodeFrame({
      type: "response",
      requestId: message.requestId,
      method: "initialize",
      resultType: "success",
      result: { clientId: "fake-reasoning-governor" },
      handledByClientId: "fake-router",
    }),
  );
  return true;
}

function sendSnapshot(socket, conversationId, effort) {
  socket.write(
    encodeFrame({
      type: "broadcast",
      method: "thread-stream-state-changed",
      params: {
        conversationId,
        hostId: "local",
        change: {
          type: "snapshot",
          conversationState: {
            latestThreadSettings: { model: "gpt-test", effort },
          },
        },
      },
    }),
  );
}

test("parses status, explicit set, and the legacy set form", () => {
  assert.deepEqual(parseArgs(["status", "--thread-id", "thread-123"]), {
    action: "status",
    effort: null,
    threadId: "thread-123",
    hostId: null,
    pipePath: null,
    timeoutMs: 20_000,
    debug: false,
    help: false,
  });
  assert.equal(parseArgs(["set", "--effort", "max"]).action, "set");
  assert.equal(parseArgs(["set", "--effort", "max"]).effort, "max");
  assert.equal(parseArgs(["high"]).action, "set");
  assert.equal(parseArgs(["high"]).effort, "high");
});

test("rejects an effort value for status", () => {
  assert.throws(() => parseArgs(["status", "high"]), /status does not accept/);
});

test("reads configured effort without sending a turn", async () => {
  const result = await withFakeIpc(
    (message, socket) => {
      if (respondToInitialize(message, socket)) {
        return;
      }
      if (
        message.type === "broadcast" &&
        message.method === "thread-stream-following-changed" &&
        message.params?.following === true
      ) {
        sendSnapshot(socket, message.params.conversationId, "high");
      }
    },
    (pipePath) =>
      readReasoningEffort({
        pipePath,
        threadId: "thread-status",
        hostId: "local",
        timeoutMs: 2_000,
        debug: false,
      }),
  );

  assert.equal(result.ok, true);
  assert.equal(result.operation, "status");
  assert.equal(result.currentConfiguredEffort, "high");
  assert.equal(result.sentTurn, false);
  assert.equal(result.activeTurnEffortReadable, false);
});

test("sets and reads back next-turn effort without sending a turn", async () => {
  let requestedEffort = null;
  const result = await withFakeIpc(
    (message, socket) => {
      if (respondToInitialize(message, socket)) {
        return;
      }
      if (message.type === "request" && message.method === "thread-follower-update-thread-settings") {
        requestedEffort = message.params?.threadSettings?.effort ?? null;
        socket.write(
          encodeFrame({
            type: "response",
            requestId: message.requestId,
            method: message.method,
            resultType: "success",
            result: { ok: true },
            handledByClientId: "fake-router",
          }),
        );
        return;
      }
      if (
        message.type === "broadcast" &&
        message.method === "thread-stream-following-changed" &&
        message.params?.following === true
      ) {
        sendSnapshot(socket, message.params.conversationId, requestedEffort);
      }
    },
    (pipePath) =>
      updateReasoningEffort({
        pipePath,
        threadId: "thread-set",
        hostId: "local",
        effort: "max",
        timeoutMs: 2_000,
        debug: false,
      }),
  );

  assert.equal(requestedEffort, "max");
  assert.equal(result.ok, true);
  assert.equal(result.operation, "set");
  assert.equal(result.currentConfiguredEffort, "max");
  assert.equal(result.matchesRequestedEffort, true);
  assert.equal(result.sentTurn, false);
});

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
