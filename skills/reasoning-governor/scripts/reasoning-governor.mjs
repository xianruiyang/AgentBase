#!/usr/bin/env node

import crypto from "node:crypto";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const VALID_EFFORTS = new Set(["low", "medium", "high", "xhigh", "max", "ultra"]);
const DEFAULT_TIMEOUT_MS = 20000;
const NORMAL_FRAME_LIMIT_BYTES = 8 * 1024 * 1024;
const SNAPSHOT_PREFIX_BYTES = 4096;
const SNAPSHOT_TAIL_BYTES = 4 * 1024 * 1024;
const SETTINGS_SCAN_LIMIT_CHARS = 256 * 1024;

function usage() {
  return [
    "Usage:",
    "  node reasoning-governor.mjs status [--thread-id <id>]",
    "  node reasoning-governor.mjs set --effort high [--thread-id <id>]",
    "  node reasoning-governor.mjs --effort high [--thread-id <id>]  # legacy set form",
    "",
    "Defaults:",
    "  --thread-id defaults to CODEX_THREAD_ID, then stdin JSON when available.",
    "  --pipe defaults to the Codex desktop IPC pipe for this platform.",
    "  --host-id defaults to the current thread host reported by Codex, then local.",
    "",
    "Notes:",
    "  status reads the configured next-turn effort without changing it.",
    "  set changes and reads back the next-turn configuration. It cannot change or read the active turn effort.",
    "  It uses the running Codex desktop IPC router and does not send a message or start a turn.",
  ].join("\n");
}

function parseArgs(argv) {
  const out = {
    action: null,
    effort: null,
    threadId: null,
    hostId: null,
    pipePath: null,
    timeoutMs: DEFAULT_TIMEOUT_MS,
    debug: false,
    help: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "status" || arg === "set") {
      if (out.action) {
        throw new Error(`Multiple actions provided: ${out.action}, ${arg}`);
      }
      out.action = arg;
    } else if (arg === "--effort" || arg === "-e") {
      out.effort = argv[++i] ?? null;
    } else if (arg === "--thread-id" || arg === "-t") {
      out.threadId = argv[++i] ?? null;
    } else if (arg === "--host-id") {
      out.hostId = argv[++i] ?? null;
    } else if (arg === "--pipe") {
      out.pipePath = argv[++i] ?? null;
    } else if (arg === "--timeout-ms") {
      out.timeoutMs = Number(argv[++i] ?? DEFAULT_TIMEOUT_MS);
    } else if (arg === "--debug") {
      out.debug = true;
    } else if (arg === "--help" || arg === "-h") {
      out.help = true;
    } else if (!out.effort && !arg.startsWith("-")) {
      out.effort = arg;
      out.action ??= "set";
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }

  if (!Number.isFinite(out.timeoutMs) || out.timeoutMs <= 0) {
    throw new Error("--timeout-ms must be a positive number.");
  }

  out.action ??= out.effort ? "set" : null;
  if (out.action === "status" && out.effort) {
    throw new Error("status does not accept an effort value.");
  }

  return out;
}

async function readStdinBriefly() {
  if (process.stdin.isTTY) {
    return "";
  }

  return await new Promise((resolve) => {
    let data = "";
    let ended = false;
    const timer = setTimeout(() => {
      if (!ended) {
        resolve(data);
      }
    }, 250);

    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => {
      data += chunk;
    });
    process.stdin.on("end", () => {
      ended = true;
      clearTimeout(timer);
      resolve(data);
    });
    process.stdin.resume();
  });
}

function findThreadIdInObject(value) {
  if (!value || typeof value !== "object") {
    return null;
  }

  const directKeys = ["threadId", "thread_id", "threadID", "conversationId", "conversation_id"];
  for (const key of directKeys) {
    if (typeof value[key] === "string" && value[key].trim()) {
      return value[key].trim();
    }
  }

  for (const child of Object.values(value)) {
    const found = findThreadIdInObject(child);
    if (found) {
      return found;
    }
  }

  return null;
}

async function resolveThreadId(explicitThreadId) {
  if (explicitThreadId) {
    return explicitThreadId;
  }

  if (process.env.CODEX_THREAD_ID) {
    return process.env.CODEX_THREAD_ID;
  }

  const stdin = await readStdinBriefly();
  if (!stdin.trim()) {
    return null;
  }

  try {
    return findThreadIdInObject(JSON.parse(stdin));
  } catch {
    return null;
  }
}

function defaultIpcPath() {
  if (process.platform === "win32") {
    return "\\\\.\\pipe\\codex-ipc";
  }

  const dir = path.join(os.tmpdir(), "codex-ipc");
  const uid = process.getuid?.();
  return path.join(dir, uid ? `ipc-${uid}.sock` : "ipc.sock");
}

function encodeFrame(message) {
  const json = JSON.stringify(message);
  const byteLength = Buffer.byteLength(json, "utf8");
  const frame = Buffer.allocUnsafe(4 + byteLength);
  frame.writeUInt32LE(byteLength, 0);
  frame.write(json, 4, "utf8");
  return frame;
}

function createTailBuffer(capacity) {
  const buffer = Buffer.allocUnsafe(capacity);
  let position = 0;
  let size = 0;

  return {
    reset() {
      position = 0;
      size = 0;
    },
    append(chunk) {
      if (chunk.length >= capacity) {
        chunk.copy(buffer, 0, chunk.length - capacity);
        position = 0;
        size = capacity;
        return;
      }

      const firstLength = Math.min(chunk.length, capacity - position);
      chunk.copy(buffer, position, 0, firstLength);
      if (firstLength < chunk.length) {
        chunk.copy(buffer, 0, firstLength);
      }
      position = (position + chunk.length) % capacity;
      size = Math.min(capacity, size + chunk.length);
    },
    toBuffer() {
      if (size < capacity) {
        return Buffer.from(buffer.subarray(0, size));
      }
      return Buffer.concat([buffer.subarray(position), buffer.subarray(0, position)]);
    },
  };
}

function isEscaped(text, index) {
  let backslashes = 0;
  for (let i = index - 1; i >= 0 && text[i] === "\\"; i -= 1) {
    backslashes += 1;
  }
  return backslashes % 2 === 1;
}

function findLastUnescaped(text, token) {
  let index = text.lastIndexOf(token);
  while (index >= 0) {
    if (!isEscaped(text, index)) {
      return index;
    }
    index = text.lastIndexOf(token, index - 1);
  }
  return -1;
}

function parseJsonStringAt(text, start) {
  if (text[start] !== '"') {
    return null;
  }

  let escaped = false;
  for (let i = start + 1; i < text.length; i += 1) {
    const char = text[i];
    if (escaped) {
      escaped = false;
      continue;
    }
    if (char === "\\") {
      escaped = true;
      continue;
    }
    if (char === '"') {
      try {
        return { value: JSON.parse(text.slice(start, i + 1)), end: i + 1 };
      } catch {
        return null;
      }
    }
  }
  return null;
}

function extractDirectObjectField(text, objectStart, fieldName) {
  const end = Math.min(text.length, objectStart + SETTINGS_SCAN_LIMIT_CHARS);
  let depth = 0;

  for (let i = objectStart; i < end; i += 1) {
    const char = text[i];
    if (char === "{") {
      depth += 1;
      continue;
    }
    if (char === "}") {
      depth -= 1;
      if (depth === 0) {
        return { found: false, value: null };
      }
      continue;
    }
    if (char !== '"') {
      continue;
    }

    const parsedKey = parseJsonStringAt(text, i);
    if (!parsedKey) {
      return { found: false, value: null };
    }
    i = parsedKey.end - 1;
    if (depth !== 1) {
      continue;
    }

    let cursor = parsedKey.end;
    while (cursor < end && /\s/.test(text[cursor])) {
      cursor += 1;
    }
    if (text[cursor] !== ":") {
      continue;
    }
    cursor += 1;
    while (cursor < end && /\s/.test(text[cursor])) {
      cursor += 1;
    }
    if (parsedKey.value !== fieldName) {
      continue;
    }
    if (text.startsWith("null", cursor)) {
      return { found: true, value: null };
    }

    const parsedValue = parseJsonStringAt(text, cursor);
    return parsedValue
      ? { found: true, value: parsedValue.value }
      : { found: false, value: null };
  }

  return { found: false, value: null };
}

function extractConfiguredEffortFromSnapshotTail(snapshotTail) {
  const key = '"latestThreadSettings"';
  const keyIndex = findLastUnescaped(snapshotTail, key);
  if (keyIndex < 0) {
    return { found: false, effort: null };
  }

  let cursor = keyIndex + key.length;
  while (cursor < snapshotTail.length && /\s/.test(snapshotTail[cursor])) {
    cursor += 1;
  }
  if (snapshotTail[cursor] !== ":") {
    return { found: false, effort: null };
  }
  cursor += 1;
  while (cursor < snapshotTail.length && /\s/.test(snapshotTail[cursor])) {
    cursor += 1;
  }
  if (snapshotTail.startsWith("null", cursor)) {
    return { found: true, effort: null };
  }
  if (snapshotTail[cursor] !== "{") {
    return { found: false, effort: null };
  }

  const field = extractDirectObjectField(snapshotTail, cursor, "effort");
  return { found: field.found, effort: field.value };
}

function parseSnapshotEnvelope(prefix, tail, bodyLength) {
  if (
    !prefix.includes('"method":"thread-stream-state-changed"') ||
    !prefix.includes('"change":{"type":"snapshot"')
  ) {
    return null;
  }

  const conversationMatch = prefix.match(/"conversationId":"([^"\\]+)"/);
  const hostMatch = prefix.match(/"hostId":"([^"\\]+)"/);
  const effort = extractConfiguredEffortFromSnapshotTail(tail);
  return {
    conversationId: conversationMatch?.[1] ?? null,
    hostId: hostMatch?.[1] ?? null,
    bodyLength,
    ...effort,
  };
}

function attachFrameReader(socket, { onMessage, onSnapshot, onError }) {
  const header = Buffer.allocUnsafe(4);
  let headerBytes = 0;
  let bodyLength = 0;
  let bodyBytes = 0;
  let body = null;
  const prefix = Buffer.allocUnsafe(SNAPSHOT_PREFIX_BYTES);
  let prefixBytes = 0;
  const tail = createTailBuffer(SNAPSHOT_TAIL_BYTES);

  socket.on("data", (chunk) => {
    try {
      let offset = 0;
      while (offset < chunk.length) {
        if (bodyLength === 0) {
          const bytes = Math.min(4 - headerBytes, chunk.length - offset);
          chunk.copy(header, headerBytes, offset, offset + bytes);
          headerBytes += bytes;
          offset += bytes;

          if (headerBytes < 4) {
            continue;
          }

          bodyLength = header.readUInt32LE(0);
          headerBytes = 0;
          if (bodyLength <= 0 || bodyLength > 256 * 1024 * 1024) {
            throw new Error(`Invalid IPC frame length: ${bodyLength}`);
          }

          bodyBytes = 0;
          prefixBytes = 0;
          tail.reset();
          body = bodyLength <= NORMAL_FRAME_LIMIT_BYTES ? Buffer.allocUnsafe(bodyLength) : null;
        }

        const bytes = Math.min(bodyLength - bodyBytes, chunk.length - offset);
        const segment = chunk.subarray(offset, offset + bytes);
        if (body) {
          segment.copy(body, bodyBytes);
        }
        if (prefixBytes < prefix.length) {
          const prefixLength = Math.min(segment.length, prefix.length - prefixBytes);
          segment.copy(prefix, prefixBytes, 0, prefixLength);
          prefixBytes += prefixLength;
        }
        tail.append(segment);
        bodyBytes += bytes;
        offset += bytes;

        if (bodyBytes === bodyLength) {
          if (body) {
            onMessage(JSON.parse(body.toString("utf8")));
          } else {
            const snapshot = parseSnapshotEnvelope(
              prefix.subarray(0, prefixBytes).toString("utf8"),
              tail.toBuffer().toString("utf8"),
              bodyLength,
            );
            if (!snapshot) {
              throw new Error(`Unsupported large IPC frame: ${bodyLength} bytes`);
            }
            onSnapshot(snapshot);
          }
          bodyLength = 0;
          bodyBytes = 0;
          body = null;
        }
      }
    } catch (error) {
      onError(error);
    }
  });
}

class CodexIpcClient {
  constructor({ pipePath, timeoutMs, debug }) {
    this.pipePath = pipePath;
    this.timeoutMs = timeoutMs;
    this.debug = debug;
    this.clientId = "external-reasoning-depth-script";
    this.pending = new Map();
    this.snapshotWaiters = new Map();
    this.followingHosts = new Map();
    this.socket = null;
  }

  async connect() {
    this.socket = net.connect(this.pipePath);
    attachFrameReader(this.socket, {
      onMessage: (message) => this.handleMessage(message),
      onSnapshot: (snapshot) => this.handleSnapshot(snapshot),
      onError: (error) => this.socket?.destroy(error),
    });

    await new Promise((resolve, reject) => {
      this.socket.once("connect", resolve);
      this.socket.once("error", reject);
    });

    const response = await this.request({
      method: "initialize",
      params: { clientType: "external-reasoning-depth-script" },
      version: 0,
      timeoutMs: Math.min(this.timeoutMs, 5000),
    });

    if (response.resultType !== "success" || response.method !== "initialize") {
      throw new Error(`IPC initialize failed: ${JSON.stringify(response)}`);
    }

    this.clientId = response.result.clientId;
    return response;
  }

  handleMessage(message) {
    if (this.debug) {
      process.stderr.write(`[codex-ipc] ${JSON.stringify(message)}\n`);
    }

    if (message.type === "broadcast") {
      if (
        message.method === "thread-stream-following-changed" &&
        message.params?.following === true &&
        typeof message.params?.conversationId === "string" &&
        typeof message.params?.hostId === "string"
      ) {
        this.followingHosts.set(message.params.conversationId, message.params.hostId);
      }

      if (
        message.method === "thread-stream-state-changed" &&
        message.params?.change?.type === "snapshot"
      ) {
        const state = message.params.change.conversationState;
        this.handleSnapshot({
          conversationId: message.params.conversationId ?? null,
          hostId: message.params.hostId ?? null,
          bodyLength: Buffer.byteLength(JSON.stringify(message), "utf8"),
          found: state && Object.hasOwn(state, "latestThreadSettings"),
          effort: state?.latestThreadSettings?.effort ?? null,
        });
      }
      return;
    }

    if (message.type !== "response") {
      return;
    }

    const pending = this.pending.get(message.requestId);
    if (!pending) {
      return;
    }

    clearTimeout(pending.timer);
    this.pending.delete(message.requestId);
    pending.resolve(message);
  }

  handleSnapshot(snapshot) {
    if (this.debug) {
      process.stderr.write(
        `[codex-ipc] snapshot readback ${JSON.stringify({
          conversationId: snapshot.conversationId,
          hostId: snapshot.hostId,
          bodyLength: snapshot.bodyLength,
          found: snapshot.found,
          effort: snapshot.effort,
        })}\n`,
      );
    }

    const pending = this.snapshotWaiters.get(snapshot.conversationId);
    if (!pending) {
      return;
    }
    clearTimeout(pending.timer);
    this.snapshotWaiters.delete(snapshot.conversationId);
    pending.resolve(snapshot);
  }

  sendBroadcast({ method, params, version, targetClientIds = null }) {
    if (!this.socket || !this.socket.writable) {
      throw new Error("IPC socket is not connected.");
    }
    const message = {
      type: "broadcast",
      method,
      sourceClientId: this.clientId,
      version,
      params,
      ...(targetClientIds ? { targetClientIds } : {}),
    };
    this.socket.write(encodeFrame(message));
  }

  getFollowingHost(threadId) {
    return this.followingHosts.get(threadId) ?? null;
  }

  async readConfiguredEffort({ threadId, hostId, timeoutMs = this.timeoutMs }) {
    if (this.snapshotWaiters.has(threadId)) {
      throw new Error(`Snapshot readback already pending for thread: ${threadId}`);
    }

    const promise = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.snapshotWaiters.delete(threadId);
        reject(new Error(`Timed out reading back thread settings for host: ${hostId}`));
      }, timeoutMs);
      this.snapshotWaiters.set(threadId, { resolve, reject, timer });
    });

    this.sendBroadcast({
      method: "thread-stream-following-changed",
      version: 1,
      params: { conversationId: threadId, hostId, following: true },
    });

    return await promise;
  }

  stopFollowing({ threadId, hostId }) {
    if (!this.socket?.writable) {
      return;
    }
    this.sendBroadcast({
      method: "thread-stream-following-changed",
      version: 1,
      params: { conversationId: threadId, hostId, following: false },
    });
  }

  async request({ method, params, version, timeoutMs = this.timeoutMs }) {
    if (!this.socket || !this.socket.writable) {
      throw new Error("IPC socket is not connected.");
    }

    const requestId = crypto.randomUUID();
    const message = {
      type: "request",
      requestId,
      sourceClientId: this.clientId,
      version,
      method,
      params,
      timeoutMs,
    };

    const promise = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(requestId);
        reject(new Error(`Timed out waiting for IPC method: ${method}`));
      }, timeoutMs + 1000);
      this.pending.set(requestId, { resolve, reject, timer });
    });

    this.socket.write(encodeFrame(message));
    return await promise;
  }

  close() {
    for (const [requestId, pending] of this.pending.entries()) {
      clearTimeout(pending.timer);
      pending.reject(new Error("IPC client closed."));
      this.pending.delete(requestId);
    }
    for (const [threadId, pending] of this.snapshotWaiters.entries()) {
      clearTimeout(pending.timer);
      pending.reject(new Error("IPC client closed."));
      this.snapshotWaiters.delete(threadId);
    }

    this.socket?.end();
    this.socket?.destroy();
    this.socket = null;
  }
}

async function readReasoningEffort({ pipePath, threadId, hostId, timeoutMs, debug }) {
  const client = new CodexIpcClient({ pipePath, timeoutMs, debug });
  let initResponse = null;
  let readbackHostId = hostId;

  try {
    initResponse = await client.connect();
    readbackHostId = readbackHostId ?? client.getFollowingHost(threadId) ?? "local";
    let readback = null;
    let readbackError = null;
    try {
      readback = await client.readConfiguredEffort({
        threadId,
        hostId: readbackHostId,
        timeoutMs,
      });
    } catch (error) {
      readbackError = error.message;
    }

    const readbackVerified = readback?.found === true;
    return {
      ok: readbackVerified,
      operation: "status",
      method: "thread-stream-following-changed",
      transport: "codex-ipc",
      sentTurn: false,
      threadId,
      currentConfiguredEffort: readbackVerified ? readback.effort : null,
      readbackVerified,
      verification: readbackVerified ? "conversation_state_snapshot" : "unavailable",
      configuredFor: "next_turn",
      activeTurnEffort: null,
      activeTurnEffortReadable: false,
      readbackHostId,
      readbackSnapshotBytes: readback?.bodyLength ?? null,
      readbackError,
      pipePath,
      initHandledByClientId: initResponse.handledByClientId ?? null,
    };
  } finally {
    if (readbackHostId) {
      client.stopFollowing({ threadId, hostId: readbackHostId });
    }
    client.close();
  }
}

async function updateReasoningEffort({ pipePath, threadId, hostId, effort, timeoutMs, debug }) {
  const client = new CodexIpcClient({ pipePath, timeoutMs, debug });
  let initResponse = null;
  let readbackHostId = hostId;

  try {
    initResponse = await client.connect();
    const updateResponse = await client.request({
      method: "thread-follower-update-thread-settings",
      version: 1,
      timeoutMs,
      params: {
        conversationId: threadId,
        threadSettings: { effort },
      },
    });

    if (updateResponse.resultType !== "success") {
      throw new Error(updateResponse.error || `IPC update failed: ${JSON.stringify(updateResponse)}`);
    }

    const updateAccepted = updateResponse.result?.ok === true;
    readbackHostId = readbackHostId ?? client.getFollowingHost(threadId) ?? "local";
    let readback = null;
    let readbackError = null;
    if (updateAccepted) {
      try {
        readback = await client.readConfiguredEffort({
          threadId,
          hostId: readbackHostId,
          timeoutMs,
        });
      } catch (error) {
        readbackError = error.message;
      }
    }

    const readbackVerified = readback?.found === true;
    const configuredEffort = readbackVerified ? readback.effort : null;
    const matchesRequestedEffort = readbackVerified ? configuredEffort === effort : null;

    return {
      ok: updateAccepted && matchesRequestedEffort === true,
      operation: "set",
      updateAccepted,
      method: "thread-follower-update-thread-settings",
      transport: "codex-ipc",
      sentTurn: false,
      threadId,
      requestedEffort: effort,
      currentConfiguredEffort: configuredEffort,
      matchesRequestedEffort,
      readbackVerified,
      verification: readbackVerified ? "conversation_state_snapshot" : "unavailable",
      configuredFor: "next_turn",
      activeTurnEffort: null,
      activeTurnEffortReadable: false,
      readbackHostId,
      readbackSnapshotBytes: readback?.bodyLength ?? null,
      readbackError,
      handledByClientId: updateResponse.handledByClientId ?? null,
      pipePath,
      initHandledByClientId: initResponse.handledByClientId ?? null,
    };
  } finally {
    if (readbackHostId) {
      client.stopFollowing({ threadId, hostId: readbackHostId });
    }
    client.close();
  }
}

async function main(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);

  if (args.help) {
    console.log(usage());
    return 0;
  }
  if (!args.action) {
    throw new Error("Missing action. Expected status or set.");
  }
  if (args.action === "set" && (!args.effort || !VALID_EFFORTS.has(args.effort))) {
    throw new Error(`Invalid or missing effort. Expected one of: ${[...VALID_EFFORTS].join(", ")}`);
  }

  const threadId = await resolveThreadId(args.threadId);
  if (!threadId) {
    throw new Error("Missing thread id. Pass --thread-id or run inside Codex with CODEX_THREAD_ID.");
  }

  const common = {
    pipePath: args.pipePath ?? defaultIpcPath(),
    threadId,
    hostId: args.hostId,
    timeoutMs: args.timeoutMs,
    debug: args.debug,
  };
  const result =
    args.action === "status"
      ? await readReasoningEffort(common)
      : await updateReasoningEffort({ ...common, effort: args.effort });

  console.log(JSON.stringify(result, null, 2));
  return result.ok ? 0 : 3;
}

async function runCli(argv = process.argv.slice(2)) {
  try {
    process.exitCode = await main(argv);
  } catch (error) {
    console.error(
      JSON.stringify(
        {
          ok: false,
          error: error.message,
        },
        null,
        2,
      ),
    );
    process.exitCode = 1;
  }
}

const isMain =
  process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));

if (isMain) {
  runCli();
}

export {
  extractConfiguredEffortFromSnapshotTail,
  parseArgs,
  parseSnapshotEnvelope,
  readReasoningEffort,
  runCli,
  updateReasoningEffort,
};
