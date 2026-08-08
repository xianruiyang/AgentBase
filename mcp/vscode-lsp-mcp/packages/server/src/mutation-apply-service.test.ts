import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import type {
  JsonObject,
  NormalizedWorkspaceEdit,
  RuntimePrimitives,
  WorkspaceRouteIdentity,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  createMutationCacheForTesting,
  type MutationCache,
  type MutationCacheIdentity,
  type MutationOperationKind,
} from './mutation-cache.js';
import {
  MutationApplyService,
  type MutationWorkspaceConnector,
} from './mutation-apply-service.js';
import {
  WorkspaceRoutingError,
  type BridgeProbeSession,
} from './workspace-router.js';

interface RuntimeState {
  readonly primitives: RuntimePrimitives;
  setNow(value: number): void;
}

const runtime = (): RuntimeState => {
  let now = 0;
  let randomCall = 0;
  return {
    primitives: {
      monotonicNowMs: () => now,
      secureRandomBytes: (length) => {
        const bytes = new Uint8Array(length);
        new DataView(bytes.buffer).setUint32(length - 4, ++randomCall);
        return bytes;
      },
      sha256Hex: (input) => createHash('sha256').update(input).digest('hex'),
    },
    setNow: (value) => {
      now = value;
    },
  };
};

const cacheIdentity = (clientSessionId = 'client-a'): MutationCacheIdentity => ({
  clientSessionId,
  workspace: {
    workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA' as WorkspaceRouteIdentity['workspaceId'],
    generation: 3,
  },
});

const normalizedEdit = (): NormalizedWorkspaceEdit => ({
  textChanges: [{
    kind: 'text',
    file: 'src/a.ts',
    edits: [{
      range: { startLine: 1, startColumn: 1, endLine: 1, endColumn: 4 },
      startOffset: 0,
      endOffset: 3,
      oldText: 'old',
      newText: 'new',
      providerOrdinal: 0,
    }],
  }],
  targets: [{
    file: 'src/a.ts',
    internalUri: 'file:///workspace/src/a.ts',
    rootAlias: 'app',
    boundaryFingerprint: 'a'.repeat(64),
    documentEpoch: 1,
    documentVersion: 2,
    memoryContentSha256: 'b'.repeat(64),
    eol: 'lf',
    encoding: 'utf16-code-units',
    diskExists: true,
    diskByteSha256: 'c'.repeat(64),
    expectedPostContentSha256: 'd'.repeat(64),
  }],
});

const commit = (cache: MutationCache, operationKind: MutationOperationKind = 'rename'): string => {
  const result = cache.commitPreview({
    identity: cacheIdentity(),
    operationKind,
    requestSummary: { symbol: 'old' },
    normalizedEdit: normalizedEdit(),
  });
  assert.ok(result.previewId);
  return result.previewId;
};

class FakeSession implements BridgeProbeSession {
  readonly response: unknown | (() => Promise<unknown>);
  calls: Array<{ readonly method: string; readonly params: JsonObject }> = [];
  closed = false;

  constructor(response: unknown | (() => Promise<unknown>)) {
    this.response = response;
  }

  call(method: string, params: JsonObject): Promise<unknown> {
    this.calls.push({ method, params });
    return typeof this.response === 'function' ? this.response() : Promise.resolve(this.response);
  }

  close(): Promise<void> {
    this.closed = true;
    return Promise.resolve();
  }
}

class FakeConnector implements MutationWorkspaceConnector {
  error: unknown;
  readonly sessions: FakeSession[] = [];
  response: unknown = { status: 'applied', changedFiles: ['src/a.ts'] };
  routes: WorkspaceRouteIdentity[] = [];

  connectWorkspaceRoute(workspace: WorkspaceRouteIdentity): Promise<BridgeProbeSession> {
    this.routes.push(workspace);
    if (this.error !== undefined) return Promise.reject(this.error);
    const session = new FakeSession(this.response);
    this.sessions.push(session);
    return Promise.resolve(session);
  }
}

const fixture = () => {
  const clock = runtime();
  const cache = createMutationCacheForTesting({ primitives: clock.primitives });
  const connector = new FakeConnector();
  const service = new MutationApplyService({ cache, connector });
  return { cache, clock, connector, service };
};

test('server route preflight derives workspace from cache, claims once, and sends private apply DTO', async () => {
  const state = fixture();
  const previewId = commit(state.cache);
  const response = await state.service.applyPreview('client-a', previewId, 'rename');
  assert.deepEqual(response, { ok: true, data: { changedFiles: ['src/a.ts'] } });
  assert.deepEqual(state.connector.routes, [cacheIdentity().workspace]);
  assert.equal(state.connector.sessions.length, 1);
  const session = state.connector.sessions[0]!;
  assert.equal(session.calls[0]?.method, 'mutation.apply');
  assert.match(session.calls[0]?.params.applyAttemptId as string, /^ap_[A-Za-z0-9_-]{22}$/u);
  assert.equal((session.calls[0]?.params.normalizedEdit as JsonObject).targets !== undefined, true);
  assert.equal(session.closed, true);
  assert.equal(state.cache.stats().totalChargeBytes, 0);
  assert.equal(state.cache.stats().previewTombstones, 1);
  assert.deepEqual(await state.service.applyPreview('client-a', previewId, 'rename'), {
    ok: false,
    error: {
      code: 'PREVIEW_NOT_FOUND',
      message: 'The preview is unavailable or has already been consumed.',
      retryable: false,
    },
  });
});

test('rename, Code Action, and format preview handles cannot cross apply operations', async () => {
  const pairs: ReadonlyArray<{
    readonly expected: MutationOperationKind;
    readonly wrong: MutationOperationKind;
  }> = [
    { expected: 'rename', wrong: 'format' },
    { expected: 'codeAction', wrong: 'rename' },
    { expected: 'format', wrong: 'codeAction' },
  ];
  for (const pair of pairs) {
    const state = fixture();
    const previewId = commit(state.cache, pair.expected);
    const rejected = await state.service.applyPreview('client-a', previewId, pair.wrong);
    assert.equal(rejected.ok, false);
    if (!rejected.ok) assert.equal(rejected.error.code, 'PREVIEW_NOT_FOUND');
    assert.equal(state.cache.peekPreviewForClient('client-a', previewId).status, 'active');
    assert.equal(state.connector.sessions.length, 0);
    assert.equal((await state.service.applyPreview('client-a', previewId, pair.expected)).ok, true);
  }
});

test('route disconnect before claim leaves preview active and retryable', async () => {
  const state = fixture();
  const previewId = commit(state.cache);
  state.connector.error = new WorkspaceRoutingError('disconnected', 'offline');
  const disconnected = await state.service.applyPreview('client-a', previewId, 'rename');
  assert.deepEqual(disconnected, {
    ok: false,
    error: {
      code: 'WORKSPACE_DISCONNECTED',
      message: 'The workspace route is not currently connected.',
      retryable: true,
      details: { phase: 'preflight', outcome: 'notStarted' },
    },
  });
  assert.equal(state.cache.peekPreviewForClient('client-a', previewId).status, 'active');
  state.connector.error = undefined;
  assert.equal((await state.service.applyPreview('client-a', previewId, 'rename')).ok, true);
});

test('missing rotated route consumes stale preview without revealing its workspace', async () => {
  const state = fixture();
  const previewId = commit(state.cache);
  state.connector.error = new WorkspaceRoutingError('notFound', 'rotated');
  const response = await state.service.applyPreview('client-a', previewId, 'rename');
  assert.equal(response.ok, false);
  if (!response.ok) assert.equal(response.error.code, 'PREVIEW_NOT_FOUND');
  assert.equal(state.cache.peekPreviewForClient('client-a', previewId).status, 'notFound');
  assert.equal(state.cache.stats().totalChargeBytes, 0);
});

test('bridge terminal failures map to closed public errors and consume the preview', async () => {
  const cases: Array<{
    readonly bridge: unknown;
    readonly code: string;
    readonly details?: unknown;
  }> = [
    { bridge: { status: 'pathOutsideWorkspace' }, code: 'PATH_OUTSIDE_WORKSPACE' },
    {
      bridge: { status: 'documentChanged', reason: 'version', files: ['src/a.ts'] },
      code: 'DOCUMENT_CHANGED',
      details: { reason: 'version', files: ['src/a.ts'] },
    },
    {
      bridge: { status: 'editConflict', reason: 'overlappingEdits', files: ['src/a.ts'] },
      code: 'EDIT_CONFLICT',
      details: { reason: 'overlappingEdits', files: ['src/a.ts'] },
    },
    {
      bridge: { status: 'applyFailed', stage: 'apply', outcome: 'notApplied' },
      code: 'APPLY_FAILED',
      details: { stage: 'apply', outcome: 'notApplied' },
    },
    {
      bridge: { status: 'applyFailed', stage: 'readback', outcome: 'postconditionFailed' },
      code: 'APPLY_FAILED',
      details: { stage: 'readback', outcome: 'postconditionFailed' },
    },
  ];
  for (const candidate of cases) {
    const state = fixture();
    const previewId = commit(state.cache);
    state.connector.response = candidate.bridge;
    const response = await state.service.applyPreview('client-a', previewId, 'rename');
    assert.equal(response.ok, false);
    if (!response.ok) {
      assert.equal(response.error.code, candidate.code);
      if (candidate.details !== undefined) assert.deepEqual(response.error.details, candidate.details);
      assert.equal('changedFiles' in response.error, false);
    }
    assert.equal(state.cache.peekPreviewForClient('client-a', previewId).status, 'notFound');
  }
});

test('post-claim transport or parser failure is outcome unknown and never retryable', async () => {
  for (const bridge of [
    () => Promise.reject(new Error('disconnected')),
    { status: 'applied', changedFiles: [], internalUri: 'file:///leak' },
  ]) {
    const state = fixture();
    const previewId = commit(state.cache);
    state.connector.response = bridge;
    const response = await state.service.applyPreview('client-a', previewId, 'rename');
    assert.deepEqual(response, {
      ok: false,
      error: {
        code: 'WORKSPACE_DISCONNECTED',
        message: 'The mutation outcome could not be verified.',
        retryable: false,
        details: { phase: 'apply', outcome: 'unknown' },
      },
    });
    assert.equal(state.cache.peekPreviewForClient('client-a', previewId).status, 'notFound');
  }
});

test('client-scoped lookup hides foreign previews and exact TTL expiry wins before routing', async () => {
  const state = fixture();
  const previewId = commit(state.cache);
  assert.equal((await state.service.applyPreview('client-b', previewId, 'rename')).ok, false);
  assert.equal((await state.service.applyPreview('client-a', previewId, 'codeAction')).ok, false);
  assert.equal(state.connector.routes.length, 0);
  assert.equal(state.cache.peekPreviewForClient('client-a', previewId).status, 'active');
  state.clock.setNow(300_000);
  const expired = await state.service.applyPreview('client-a', previewId, 'rename');
  assert.equal(expired.ok, false);
  if (!expired.ok) assert.equal(expired.error.code, 'PREVIEW_EXPIRED');
  assert.equal(state.connector.routes.length, 0);
});

test('two concurrent apply calls dispatch at most once after atomic claim', async () => {
  const state = fixture();
  let release = (): void => undefined;
  const pending = new Promise<unknown>((resolve) => {
    release = () => resolve({ status: 'applied', changedFiles: ['src/a.ts'] });
  });
  state.connector.response = () => pending;
  const previewId = commit(state.cache);
  const first = state.service.applyPreview('client-a', previewId, 'rename');
  while (state.connector.sessions[0]?.calls.length !== 1) await Promise.resolve();
  const second = await state.service.applyPreview('client-a', previewId, 'rename');
  assert.equal(second.ok, false);
  if (!second.ok) assert.equal(second.error.code, 'PREVIEW_NOT_FOUND');
  release();
  assert.equal((await first).ok, true);
  assert.equal(state.connector.sessions.length, 1);
});
