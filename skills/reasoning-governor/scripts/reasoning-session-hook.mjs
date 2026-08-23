#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { defaultIpcPath, readReasoningEffort } from "./reasoning-governor.mjs";

const SESSION_START_SOURCES = new Set(["startup", "resume", "clear", "compact"]);
const CACHE_VERSION = 1;
const CACHE_ENTRY_LIMIT = 256;
const READBACK_TIMEOUT_MS = 5_000;
const UNKNOWN_CONTEXT = "reasoning_effort=?; do not infer.";

function defaultCachePath() {
  return path.join(os.tmpdir(), "agentbase-reasoning-governor", "session-start-cache.json");
}

function sessionKey(sessionId) {
  return crypto.createHash("sha256").update(sessionId, "utf8").digest("hex");
}

function emptyCache() {
  return { version: CACHE_VERSION, sessions: {} };
}

async function readCache(cachePath) {
  try {
    const parsed = JSON.parse(await fs.readFile(cachePath, "utf8"));
    if (
      parsed?.version !== CACHE_VERSION ||
      !parsed.sessions ||
      typeof parsed.sessions !== "object" ||
      Array.isArray(parsed.sessions)
    ) {
      return emptyCache();
    }
    return parsed;
  } catch {
    return emptyCache();
  }
}

function boundCache(cache) {
  const entries = Object.entries(cache.sessions)
    .filter(([, value]) => value && typeof value === "object")
    .sort(
      (left, right) => Number(right[1].updatedAtMs ?? 0) - Number(left[1].updatedAtMs ?? 0),
    )
    .slice(0, CACHE_ENTRY_LIMIT);
  return { version: CACHE_VERSION, sessions: Object.fromEntries(entries) };
}

async function writeCache(cachePath, cache) {
  await fs.mkdir(path.dirname(cachePath), { recursive: true });
  await fs.writeFile(cachePath, `${JSON.stringify(boundCache(cache))}\n`, "utf8");
}

function observedContext(effort) {
  return `reasoning_effort=${effort}; observed, not target/user-lock.`;
}

function decideSessionStartContext({ source, model, effort, previous }) {
  if (!SESSION_START_SOURCES.has(source)) {
    return { emit: false, context: null, record: null, reason: "unsupported_source" };
  }

  if (typeof effort !== "string" || !effort.trim()) {
    return { emit: true, context: UNKNOWN_CONTEXT, record: null, reason: "readback_unavailable" };
  }

  const normalizedEffort = effort.trim();
  const normalizedModel = typeof model === "string" && model.trim() ? model.trim() : null;
  const unchangedResume =
    source === "resume" &&
    previous?.effort === normalizedEffort &&
    previous?.model === normalizedModel;

  return {
    emit: !unchangedResume,
    context: unchangedResume ? null : observedContext(normalizedEffort),
    record: unchangedResume
      ? null
      : {
          effort: normalizedEffort,
          model: normalizedModel,
          updatedAtMs: Date.now(),
        },
    reason: unchangedResume ? "unchanged_resume" : "observed",
  };
}

async function runSessionStartHook({
  input,
  pipePath = defaultIpcPath(),
  timeoutMs = READBACK_TIMEOUT_MS,
  cachePath = defaultCachePath(),
  debug = false,
}) {
  if (input?.hook_event_name !== "SessionStart") {
    return { emit: false, context: null, reason: "unsupported_event" };
  }

  const source = typeof input.source === "string" ? input.source : "";
  if (!SESSION_START_SOURCES.has(source)) {
    return { emit: false, context: null, reason: "unsupported_source" };
  }

  const sessionId = typeof input.session_id === "string" ? input.session_id.trim() : "";
  if (!sessionId) {
    return { emit: true, context: UNKNOWN_CONTEXT, reason: "missing_session_id" };
  }

  let status = null;
  try {
    status = await readReasoningEffort({
      pipePath,
      threadId: sessionId,
      hostId: null,
      timeoutMs,
      debug,
    });
  } catch {
    status = null;
  }

  const effort =
    status?.ok === true &&
    status.readbackVerified === true &&
    typeof status.currentConfiguredEffort === "string"
      ? status.currentConfiguredEffort
      : null;
  const cache = await readCache(cachePath);
  const key = sessionKey(sessionId);
  const decision = decideSessionStartContext({
    source,
    model: input.model,
    effort,
    previous: cache.sessions[key] ?? null,
  });

  if (decision.record) {
    cache.sessions[key] = decision.record;
    try {
      await writeCache(cachePath, cache);
    } catch {
      // This cache only suppresses duplicate resume context. Losing it is safe.
    }
  }

  return decision;
}

async function readHookInput() {
  let text = "";
  process.stdin.setEncoding("utf8");
  for await (const chunk of process.stdin) {
    text += chunk;
  }
  if (!text.trim()) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

async function runCli() {
  try {
    const input = await readHookInput();
    const result = input
      ? await runSessionStartHook({ input })
      : { emit: true, context: UNKNOWN_CONTEXT };
    if (result.emit && result.context) {
      process.stdout.write(`${result.context}\n`);
    }
    process.exitCode = 0;
  } catch {
    process.stdout.write(`${UNKNOWN_CONTEXT}\n`);
    process.exitCode = 0;
  }
}

const isMain =
  process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));

if (isMain) {
  runCli();
}

export {
  UNKNOWN_CONTEXT,
  boundCache,
  decideSessionStartContext,
  defaultCachePath,
  runSessionStartHook,
};
