import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  createSnapshotFieldScanner,
  parseArgs,
  readReasoningEffort,
  renderModelResult,
  updateReasoningEffort,
} from "../scripts/reasoning-governor.mjs";
import {
  UNKNOWN_CONTEXT,
  boundCache,
  decideSessionStartContext,
  runSessionStartHook,
} from "../scripts/reasoning-session-hook.mjs";

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

function scanSnapshotInChunks(message, chunkSize = 7) {
  const payload = Buffer.from(JSON.stringify(message), "utf8");
  const scanner = createSnapshotFieldScanner();
  for (let offset = 0; offset < payload.length; offset += chunkSize) {
    scanner.append(payload.subarray(offset, Math.min(payload.length, offset + chunkSize)));
  }
  return scanner.finish(payload.length);
}

test("parses status, explicit set, and the legacy set form", () => {
  assert.deepEqual(parseArgs(["status", "--thread-id", "thread-123"]), {
    action: "status",
    effort: null,
    threadId: "thread-123",
    hostId: null,
    pipePath: null,
    timeoutMs: 20_000,
    view: "model",
    debug: false,
    help: false,
  });
  assert.equal(parseArgs(["set", "--effort", "max"]).action, "set");
  assert.equal(parseArgs(["set", "--effort", "max"]).effort, "max");
  assert.equal(parseArgs(["high"]).action, "set");
  assert.equal(parseArgs(["high"]).effort, "high");
  assert.equal(parseArgs(["status", "--view", "machine"]).view, "machine");
  assert.equal(parseArgs(["status", "--machine"]).view, "machine");
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

test("stream scanner follows the structural settings path across chunk boundaries", () => {
  const result = scanSnapshotInChunks(
    {
      type: "broadcast",
      method: "thread-stream-state-changed",
      params: {
        conversationId: "thread-structural",
        hostId: "local",
        change: {
          type: "snapshot",
          conversationState: {
            turns: [
              {
                text: 'example: "latestThreadSettings":{"effort":"low"}',
              },
            ],
            latestThreadSettings: {
              model: "gpt-test",
              effort: "xhigh",
              collaborationMode: {
                settings: { reasoning_effort: "low" },
              },
            },
          },
        },
      },
    },
    1,
  );

  assert.equal(result.conversationId, "thread-structural");
  assert.equal(result.hostId, "local");
  assert.equal(result.found, true);
  assert.equal(result.effort, "xhigh");
  assert.ok(result.bodyLength > 0);
});

test("distinguishes a null setting from an unreadable snapshot", () => {
  const base = {
    type: "broadcast",
    method: "thread-stream-state-changed",
    params: {
      conversationId: "thread-null",
      hostId: "local",
      change: { type: "snapshot", conversationState: {} },
    },
  };
  base.params.change.conversationState.latestThreadSettings = null;
  const nullResult = scanSnapshotInChunks(base);
  assert.equal(nullResult.conversationId, "thread-null");
  assert.equal(nullResult.hostId, "local");
  assert.equal(nullResult.found, true);
  assert.equal(nullResult.effort, null);

  delete base.params.change.conversationState.latestThreadSettings;
  const missingResult = scanSnapshotInChunks(base);
  assert.equal(missingResult.conversationId, "thread-null");
  assert.equal(missingResult.hostId, "local");
  assert.equal(missingResult.found, false);
  assert.equal(missingResult.effort, null);
});

test("reads settings from the middle of a frame larger than the normal parse limit", async () => {
  const before = "a".repeat(5 * 1024 * 1024);
  const after = `${'example: "latestThreadSettings":{"effort":"low"}'}${"b".repeat(
    5 * 1024 * 1024,
  )}`;
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
        socket.write(
          encodeFrame({
            type: "broadcast",
            method: "thread-stream-state-changed",
            params: {
              conversationId: message.params.conversationId,
              hostId: "local",
              change: {
                type: "snapshot",
                conversationState: {
                  before,
                  latestThreadSettings: { model: "gpt-test", effort: "high" },
                  after,
                },
              },
            },
          }),
        );
      }
    },
    (pipePath) =>
      readReasoningEffort({
        pipePath,
        threadId: "thread-large-middle",
        hostId: "local",
        timeoutMs: 5_000,
        debug: false,
      }),
  );

  assert.equal(result.ok, true);
  assert.equal(result.currentConfiguredEffort, "high");
  assert.ok(result.readbackSnapshotBytes > 8 * 1024 * 1024);
});

test("renders only minimal model evidence while canonical receipts stay complete", () => {
  assert.equal(
    renderModelResult({
      ok: true,
      operation: "status",
      currentConfiguredEffort: "max",
      readbackVerified: true,
      pipePath: "ignored",
    }),
    "{ok:true op:status effort:max}",
  );
  assert.equal(
    renderModelResult({
      ok: false,
      operation: "set",
      updateAccepted: true,
      readbackVerified: true,
      matchesRequestedEffort: false,
      requestedEffort: "max",
      currentConfiguredEffort: "high",
    }),
    "{ok:false op:set reason:readback_mismatch requested:max effort:high}",
  );
  assert.equal(
    renderModelResult({
      ok: false,
      operation: "status",
      readbackVerified: false,
      readbackError: "timed out",
    }),
    '{ok:false op:status reason:readback_unavailable detail:"timed out"}',
  );
});

test("session-start context is sparse and does not treat none as unseen", () => {
  const decision = decideSessionStartContext({
    source: "startup",
    model: "gpt-test",
    effort: "none",
    previous: null,
  });
  assert.equal(decision.emit, true);
  assert.equal(decision.context, "reasoning_effort=none; observed, not target/user-lock.");
  assert.equal(decision.reason, "observed");
  assert.equal(decision.record.effort, "none");
  assert.equal(decision.record.model, "gpt-test");
  assert.equal(typeof decision.record.updatedAtMs, "number");
});

test("session-start cache keeps only the newest bounded observations", () => {
  const sessions = {};
  for (let index = 0; index < 300; index += 1) {
    sessions[`session-${index}`] = { updatedAtMs: index, effort: "low", model: "gpt-test" };
  }
  const bounded = boundCache({ version: 1, sessions });
  assert.equal(Object.keys(bounded.sessions).length, 256);
  assert.equal("session-299" in bounded.sessions, true);
  assert.equal("session-0" in bounded.sessions, false);
});

test("session-start context only suppresses an unchanged resume", () => {
  const previous = { effort: "medium", model: "gpt-test", updatedAtMs: 1 };
  assert.deepEqual(
    decideSessionStartContext({
      source: "resume",
      model: "gpt-test",
      effort: "medium",
      previous,
    }),
    { emit: false, context: null, record: null, reason: "unchanged_resume" },
  );
  assert.equal(
    decideSessionStartContext({
      source: "compact",
      model: "gpt-test",
      effort: "medium",
      previous,
    }).emit,
    true,
  );
  assert.equal(
    decideSessionStartContext({
      source: "resume",
      model: "gpt-new",
      effort: "medium",
      previous,
    }).emit,
    true,
  );
  assert.deepEqual(
    decideSessionStartContext({
      source: "resume",
      model: "gpt-test",
      effort: null,
      previous,
    }),
    { emit: true, context: UNKNOWN_CONTEXT, record: null, reason: "readback_unavailable" },
  );
});

test("session-start hook reads canonical effort and persists bounded resume dedup state", async () => {
  const cacheRoot = await fs.mkdtemp(path.join(os.tmpdir(), "reasoning-session-hook-"));
  const cachePath = path.join(cacheRoot, "cache.json");
  let currentEffort = "high";
  try {
    await withFakeIpc(
      (message, socket) => {
        if (respondToInitialize(message, socket)) {
          return;
        }
        if (
          message.type === "broadcast" &&
          message.method === "thread-stream-following-changed" &&
          message.params?.following === true
        ) {
          sendSnapshot(socket, message.params.conversationId, currentEffort);
        }
      },
      async (pipePath) => {
        const baseInput = {
          hook_event_name: "SessionStart",
          session_id: "thread-hook",
          model: "gpt-test",
        };
        const startup = await runSessionStartHook({
          input: { ...baseInput, source: "startup" },
          pipePath,
          timeoutMs: 2_000,
          cachePath,
        });
        assert.equal(startup.context, "reasoning_effort=high; observed, not target/user-lock.");

        const resume = await runSessionStartHook({
          input: { ...baseInput, source: "resume" },
          pipePath,
          timeoutMs: 2_000,
          cachePath,
        });
        assert.deepEqual(resume, {
          emit: false,
          context: null,
          record: null,
          reason: "unchanged_resume",
        });

        currentEffort = null;
        const unavailable = await runSessionStartHook({
          input: { ...baseInput, source: "resume" },
          pipePath,
          timeoutMs: 2_000,
          cachePath,
        });
        assert.equal(unavailable.context, UNKNOWN_CONTEXT);

        currentEffort = "high";
        const recoveredResume = await runSessionStartHook({
          input: { ...baseInput, source: "resume" },
          pipePath,
          timeoutMs: 2_000,
          cachePath,
        });
        assert.equal(recoveredResume.emit, false);

        const compact = await runSessionStartHook({
          input: { ...baseInput, source: "compact" },
          pipePath,
          timeoutMs: 2_000,
          cachePath,
        });
        assert.equal(compact.emit, true);
        assert.equal(compact.context, "reasoning_effort=high; observed, not target/user-lock.");
        assert.equal((await fs.readFile(cachePath, "utf8")).includes("thread-hook"), false);
      },
    );
  } finally {
    await fs.rm(cacheRoot, { recursive: true, force: true });
  }
});

test("PowerShell hook entry forwards stdin and stays silent for non-SessionStart events", () => {
  const testDir = path.dirname(fileURLToPath(import.meta.url));
  const wrapper = path.resolve(testDir, "..", "scripts", "reasoning-governor.ps1");
  const common = [
    "-NoLogo",
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    wrapper,
    "-Hook",
  ];
  const ignored = spawnSync("pwsh.exe", common, {
    input: JSON.stringify({ hook_event_name: "Stop", session_id: "thread-ignored" }),
    encoding: "utf8",
  });
  assert.equal(ignored.status, 0, ignored.stderr);
  assert.equal(ignored.stdout, "");

  const unknown = spawnSync("pwsh.exe", common, {
    input: JSON.stringify({ hook_event_name: "SessionStart", source: "startup" }),
    encoding: "utf8",
  });
  assert.equal(unknown.status, 0, unknown.stderr);
  assert.equal(unknown.stdout.trim(), UNKNOWN_CONTEXT);
});
