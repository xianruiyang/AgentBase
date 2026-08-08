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
  PREVIEW_ACTIVE_TTL_MS,
  createMutationCacheForTesting,
} from './mutation-cache.js';
import {
  MutationService,
  type RenameWorkspaceConnector,
} from './rename-service.js';
import type {
  BridgeProbeSession,
  ConnectedWorkspaceRoute,
} from './workspace-router.js';

const workspace: WorkspaceRouteIdentity = {
  workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA' as WorkspaceRouteIdentity['workspaceId'],
  generation: 11,
};

const normalizedEdit = (): NormalizedWorkspaceEdit => ({
  textChanges: [{
    kind: 'text',
    file: 'src/a.ts',
    edits: [{
      range: { startLine: 1, startColumn: 3, endLine: 1, endColumn: 4 },
      startOffset: 2,
      endOffset: 3,
      oldText: 'x',
      newText: 'value',
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

class FakeSession implements BridgeProbeSession {
  readonly calls: Array<{ readonly method: string; readonly params: JsonObject }> = [];
  closed = false;
  readonly response: unknown;

  constructor(response: unknown) {
    this.response = response;
  }

  call(method: string, params: JsonObject): Promise<unknown> {
    this.calls.push({ method, params });
    return Promise.resolve(this.response);
  }

  close(): Promise<void> {
    this.closed = true;
    return Promise.resolve();
  }
}

class FakeConnector implements RenameWorkspaceConnector {
  applyResponse: unknown = { status: 'applied', changedFiles: ['src/a.ts'] };
  readonly applySessions: FakeSession[] = [];
  readonly previewSessions: FakeSession[] = [];
  previewResponse: unknown = { status: 'completed', normalizedEdit: normalizedEdit() };
  readonly routeRequests: WorkspaceRouteIdentity[] = [];

  connectWorkspaceBinding(workspaceId: string): Promise<ConnectedWorkspaceRoute> {
    assert.equal(workspaceId, workspace.workspaceId);
    const session = new FakeSession(this.previewResponse);
    this.previewSessions.push(session);
    return Promise.resolve({ workspace, session });
  }

  connectWorkspaceRoute(route: WorkspaceRouteIdentity): Promise<BridgeProbeSession> {
    this.routeRequests.push(route);
    const session = new FakeSession(this.applyResponse);
    this.applySessions.push(session);
    return Promise.resolve(session);
  }
}

const runtime = () => {
  let now = 0;
  let randomCall = 0;
  const primitives: RuntimePrimitives = {
    monotonicNowMs: () => now,
    secureRandomBytes: (length) => {
      const bytes = new Uint8Array(length);
      new DataView(bytes.buffer).setUint32(length - 4, ++randomCall);
      return bytes;
    },
    sha256Hex: (input) => createHash('sha256').update(input).digest('hex'),
  };
  return { primitives, setNow: (value: number) => { now = value; } };
};

const fixture = () => {
  const clock = runtime();
  const cache = createMutationCacheForTesting({ primitives: clock.primitives });
  const connector = new FakeConnector();
  const service = new MutationService({ cache, clientSessionId: 'client-format', connector });
  return { cache, clock, connector, service };
};

const input = {
  workspaceId: workspace.workspaceId,
  file: 'src/a.ts',
  range: { startLine: 1, startColumn: 3, endLine: 1, endColumn: 4 },
  options: { tabSize: 2 },
};

test('format preview exposes only reviewable edits and apply consumes the cached format once', async () => {
  const state = fixture();
  const preview = await state.service.formatPreview(input);
  assert.equal(preview.ok, true);
  if (!preview.ok) return;
  assert.match(preview.data.previewId ?? '', /^pv_[A-Za-z0-9_-]{22}$/u);
  assert.deepEqual(preview.data.changes, [{
    kind: 'text',
    file: 'src/a.ts',
    edits: [{
      range: { startLine: 1, startColumn: 3, endLine: 1, endColumn: 4 },
      oldText: 'x',
      newText: 'value',
    }],
  }]);
  const publicJson = JSON.stringify(preview);
  for (const forbidden of ['internalUri', 'Sha256', 'documentEpoch', 'providerOrdinal', 'startOffset']) {
    assert.equal(publicJson.includes(forbidden), false);
  }
  assert.equal(state.connector.previewSessions[0]?.calls[0]?.method, 'mutation.formatPreview');
  assert.deepEqual(state.connector.previewSessions[0]?.calls[0]?.params.range, input.range);
  assert.deepEqual(state.connector.previewSessions[0]?.calls[0]?.params.options, input.options);
  assert.equal(state.connector.previewSessions[0]?.closed, true);

  assert.deepEqual(await state.service.formatApply({ previewId: preview.data.previewId }), {
    ok: true,
    data: { changedFiles: ['src/a.ts'] },
  });
  assert.equal(state.connector.applySessions[0]?.calls[0]?.method, 'mutation.apply');
  assert.deepEqual(state.connector.routeRequests, [workspace]);
  assert.equal((await state.service.formatApply({ previewId: preview.data.previewId })).ok, false);
  assert.equal(state.connector.previewSessions.length, 1);
});

test('empty format allocates no handle and range/conflict terminals never enter the cache', async () => {
  const empty = fixture();
  empty.connector.previewResponse = {
    status: 'completed',
    normalizedEdit: { textChanges: [], targets: [] },
  };
  assert.deepEqual(await empty.service.formatPreview({
    workspaceId: workspace.workspaceId,
    file: 'src/a.ts',
  }), {
    ok: true,
    data: { changes: [] },
  });
  assert.equal(empty.cache.stats().activePreviews, 0);

  const outside = fixture();
  outside.connector.previewResponse = { status: 'positionOutOfRange' };
  const position = await outside.service.formatPreview(input);
  assert.equal(position.ok, false);
  if (!position.ok) assert.equal(position.error.code, 'POSITION_OUT_OF_RANGE');

  const conflict = fixture();
  conflict.connector.previewResponse = {
    status: 'editConflict',
    reason: 'overlappingEdits',
    files: ['src/a.ts'],
  };
  assert.deepEqual(await conflict.service.formatPreview(input), {
    ok: false,
    error: {
      code: 'EDIT_CONFLICT',
      message: 'The formatting edit cannot be represented as one safe text-only preview.',
      retryable: false,
      details: { reason: 'overlappingEdits', files: ['src/a.ts'] },
    },
  });
  assert.equal(conflict.cache.stats().activePreviews, 0);
});

test('format previews preserve exact TTL and stale apply rejection semantics', async () => {
  const expired = fixture();
  const expiredPreview = await expired.service.formatPreview(input);
  assert.equal(expiredPreview.ok, true);
  if (!expiredPreview.ok) return;
  expired.clock.setNow(PREVIEW_ACTIVE_TTL_MS);
  const expiredApply = await expired.service.formatApply({ previewId: expiredPreview.data.previewId });
  assert.equal(expiredApply.ok, false);
  if (!expiredApply.ok) assert.equal(expiredApply.error.code, 'PREVIEW_EXPIRED');
  assert.equal(expired.connector.applySessions.length, 0);

  const stale = fixture();
  const stalePreview = await stale.service.formatPreview(input);
  assert.equal(stalePreview.ok, true);
  if (!stalePreview.ok) return;
  stale.connector.applyResponse = {
    status: 'documentChanged',
    reason: 'content',
    files: ['src/a.ts'],
  };
  assert.deepEqual(await stale.service.formatApply({ previewId: stalePreview.data.previewId }), {
    ok: false,
    error: {
      code: 'DOCUMENT_CHANGED',
      message: 'A mutation target changed after the preview was created.',
      retryable: false,
      details: { reason: 'content', files: ['src/a.ts'] },
    },
  });
  assert.equal((await stale.service.formatApply({ previewId: stalePreview.data.previewId })).ok, false);
});
