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
} from './mutation-cache.js';
import {
  MutationService,
  RENAME_PREVIEW_LIMITS,
  createMutationClientSessionId,
  type RenameWorkspaceConnector,
} from './rename-service.js';
import type {
  BridgeProbeSession,
  ConnectedWorkspaceRoute,
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
    setNow: (value) => { now = value; },
  };
};

const workspace: WorkspaceRouteIdentity = {
  workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA' as WorkspaceRouteIdentity['workspaceId'],
  generation: 3,
};

const target = (file: string, ordinal: number) => ({
  file,
  internalUri: `file:///workspace/${file}`,
  rootAlias: 'app',
  boundaryFingerprint: (ordinal % 16).toString(16).repeat(64),
  documentEpoch: ordinal + 1,
  documentVersion: 2,
  memoryContentSha256: 'b'.repeat(64),
  eol: 'lf' as const,
  encoding: 'utf16-code-units' as const,
  diskExists: true as const,
  diskByteSha256: 'c'.repeat(64),
  expectedPostContentSha256: 'd'.repeat(64),
});

const normalizedEdit = (): NormalizedWorkspaceEdit => ({
  textChanges: [
    {
      kind: 'text',
      file: 'src/a.ts',
      edits: [{
        range: { startLine: 1, startColumn: 1, endLine: 1, endColumn: 4 },
        startOffset: 0,
        endOffset: 3,
        oldText: 'old',
        newText: 'next',
        providerOrdinal: 0,
      }],
    },
    {
      kind: 'text',
      file: 'src/b.ts',
      edits: [{
        range: { startLine: 2, startColumn: 5, endLine: 2, endColumn: 8 },
        startOffset: 10,
        endOffset: 13,
        oldText: 'old',
        newText: 'next',
        providerOrdinal: 1,
      }],
    },
  ],
  targets: [target('src/a.ts', 0), target('src/b.ts', 1)],
});

class FakeSession implements BridgeProbeSession {
  readonly calls: Array<{
    readonly method: string;
    readonly options?: Parameters<BridgeProbeSession['call']>[2];
    readonly params: JsonObject;
  }> = [];
  closed = false;
  readonly response: unknown;

  constructor(response: unknown) {
    this.response = response;
  }

  call(
    method: string,
    params: JsonObject,
    options?: Parameters<BridgeProbeSession['call']>[2],
  ): Promise<unknown> {
    this.calls.push({ method, params, ...(options === undefined ? {} : { options }) });
    return Promise.resolve(this.response);
  }

  close(): Promise<void> {
    this.closed = true;
    return Promise.resolve();
  }
}

class FakeConnector implements RenameWorkspaceConnector {
  applyResponse: unknown = { status: 'applied', changedFiles: ['src/a.ts', 'src/b.ts'] };
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

const fixture = () => {
  const clock = runtime();
  const cache = createMutationCacheForTesting({ primitives: clock.primitives });
  const connector = new FakeConnector();
  const service = new MutationService({
    cache,
    clientSessionId: 'client-stdio-a',
    connector,
  });
  return { cache, clock, connector, service };
};

const input = {
  workspaceId: workspace.workspaceId,
  file: 'src/a.ts',
  line: 1,
  column: 2,
  newName: 'next',
  includeGlobs: ['src/**'],
  timeoutMs: 90_000,
};

test('rename preview exposes only complete public edits and apply consumes the cached DTO once', async () => {
  const state = fixture();
  const preview = await state.service.renamePreview(input);
  assert.equal(preview.ok, true);
  if (!preview.ok) return;
  assert.match(preview.data.previewId ?? '', /^pv_[A-Za-z0-9_-]{22}$/u);
  assert.deepEqual(preview.data.changes.map((change) => change.file), ['src/a.ts', 'src/b.ts']);
  const publicJson = JSON.stringify(preview);
  for (const forbidden of ['internalUri', 'Sha256', 'documentEpoch', 'providerOrdinal', 'startOffset']) {
    assert.equal(publicJson.includes(forbidden), false);
  }
  const previewSession = state.connector.previewSessions[0]!;
  assert.equal(previewSession.calls[0]?.method, 'mutation.renamePreview');
  assert.deepEqual(previewSession.calls[0]?.params.workspace, workspace);
  assert.deepEqual(previewSession.calls[0]?.params.includeGlobs, ['src/**']);
  assert.equal(previewSession.calls[0]?.params.timeoutMs, 90_000);
  assert.equal(previewSession.calls[0]?.options?.maximumTimeoutMs, 125_000);
  assert.equal(previewSession.closed, true);

  const applied = await state.service.renameApply({ previewId: preview.data.previewId });
  assert.deepEqual(applied, {
    ok: true,
    data: { changedFiles: ['src/a.ts', 'src/b.ts'] },
  });
  assert.equal(state.connector.previewSessions.length, 1);
  assert.equal(state.connector.applySessions[0]?.calls[0]?.method, 'mutation.apply');
  assert.deepEqual(state.connector.routeRequests, [workspace]);
  assert.deepEqual(await state.service.renameApply({ previewId: preview.data.previewId }), {
    ok: false,
    error: {
      code: 'PREVIEW_NOT_FOUND',
      message: 'The preview is unavailable or has already been consumed.',
      retryable: false,
    },
  });
});

test('empty rename edit is explicit and never allocates an apply handle', async () => {
  const state = fixture();
  state.connector.previewResponse = {
    status: 'completed',
    normalizedEdit: { textChanges: [], targets: [] },
  };
  assert.deepEqual(await state.service.renamePreview(input), {
    ok: false,
    error: {
      code: 'RENAME_NO_EDITS',
      message: 'The rename provider returned no effective text edits; no preview was cached.',
      retryable: false,
      action: 'Confirm the exact symbol position with definition or references and choose a different target when the provider still reports no edits.',
    },
  });
  assert.equal(state.cache.stats().activePreviews, 0);
});

test('identity rejection is bounded, actionable, and never cached', async () => {
  const state = fixture();
  state.connector.previewResponse = {
    status: 'identityRejected',
    reason: 'mismatchedSymbol',
    checkedEdits: 3,
    totalEdits: 8,
    files: ['src/unrelated.ts'],
  };
  assert.deepEqual(await state.service.renamePreview(input), {
    ok: false,
    error: {
      code: 'RENAME_IDENTITY_UNVERIFIED',
      message: 'The rename provider mixed edits that do not belong to the selected symbol; no preview was cached.',
      retryable: false,
      action: 'Use definition and references at the exact source position, then retry only after the language service resolves every edit to the same symbol.',
      details: {
        reason: 'mismatchedSymbol',
        checkedEdits: 3,
        totalEdits: 8,
        files: ['src/unrelated.ts'],
      },
    },
  });
  assert.equal(state.cache.stats().activePreviews, 0);
});

test('identity verification timeout stays an explicit unverified rename and is never cached', async () => {
  const state = fixture();
  state.connector.previewResponse = {
    status: 'identityRejected',
    reason: 'providerTimedOut',
    checkedEdits: 1,
    totalEdits: 4,
    files: ['src/b.ts'],
  };
  assert.deepEqual(await state.service.renamePreview(input), {
    ok: false,
    error: {
      code: 'RENAME_IDENTITY_UNVERIFIED',
      message: 'Rename identity verification timed out before every edit could be proven; no preview was cached.',
      retryable: false,
      action: 'Wait for language indexing to settle or narrow the declared scope, then retry the preview; do not apply an unverified rename.',
      details: {
        reason: 'providerTimedOut',
        checkedEdits: 1,
        totalEdits: 4,
        files: ['src/b.ts'],
      },
    },
  });
  assert.equal(state.cache.stats().activePreviews, 0);
});

test('extension-side scope rejection is preserved without caching a preview', async () => {
  const state = fixture();
  state.connector.previewResponse = {
    status: 'scopeRejected',
    files: Array.from({ length: 10 }, (_, index) => `outside/file-${index}.ts`),
    additionalFiles: 2,
    totalFiles: 13,
  };
  const response = await state.service.renamePreview(input);
  assert.equal(response.ok, false);
  if (response.ok || response.error.code !== 'RENAME_SCOPE_VIOLATION') return;
  assert.match(response.error.message, /12 file\(s\)/u);
  assert.equal(response.error.details.files.length, 10);
  assert.equal(response.error.details.additionalFiles, 2);
  assert.equal(response.error.details.totalFiles, 13);
  assert.equal(state.cache.stats().activePreviews, 0);
});

test('rename preview rejects the complete edit when any provider target escapes the declared scope', async () => {
  const state = fixture();
  const response = await state.service.renamePreview({
    ...input,
    includeGlobs: ['src/a.ts'],
  });
  assert.deepEqual(response, {
    ok: false,
    error: {
      code: 'RENAME_SCOPE_VIOLATION',
      message: 'The rename provider returned 1 file(s) outside the declared path scope; no preview was cached.',
      retryable: false,
      action: 'Review the listed paths and broaden the glob scope only when every provider target is intentional.',
      details: { files: ['src/b.ts'], totalFiles: 2 },
    },
  });
  assert.equal(state.cache.stats().activePreviews, 0);
});

test('rename scope failures expose at most ten paths even when the provider result is large', async () => {
  const state = fixture();
  const outsideFiles = Array.from({ length: 12 }, (_, index) =>
    `outside/file-${String(index).padStart(2, '0')}.ts`);
  const files = ['src/a.ts', ...outsideFiles];
  state.connector.previewResponse = {
    status: 'completed',
    normalizedEdit: {
      textChanges: files.map((file, index) => ({
        kind: 'text' as const,
        file,
        edits: [{
          range: { startLine: 1, startColumn: 1, endLine: 1, endColumn: 2 },
          startOffset: 0,
          endOffset: 1,
          oldText: 'a',
          newText: 'b',
          providerOrdinal: index,
        }],
      })),
      targets: files.map(target),
    },
  };
  const response = await state.service.renamePreview({
    ...input,
    includeGlobs: ['src/a.ts'],
  });
  assert.equal(response.ok, false);
  if (response.ok || response.error.code !== 'RENAME_SCOPE_VIOLATION') return;
  assert.equal(response.error.details.files.length, 10);
  assert.equal(response.error.details.additionalFiles, 2);
  assert.equal(response.error.details.totalFiles, 13);
  assert.equal(JSON.stringify(response).includes('outside/file-10.ts'), false);
  assert.equal(state.cache.stats().activePreviews, 0);
});

test('rename preview rejects a source outside its declared scope before contacting the provider', async () => {
  const state = fixture();
  const response = await state.service.renamePreview({
    ...input,
    includeGlobs: ['other/**'],
  });
  assert.equal(response.ok, false);
  if (!response.ok) assert.equal(response.error.code, 'INVALID_ARGUMENT');
  assert.equal(state.connector.previewSessions.length, 0);
  assert.equal(state.cache.stats().activePreviews, 0);
});

test('oversized rename previews return counts only and never allocate an apply handle', async () => {
  const state = fixture();
  const edit = normalizedEdit();
  const firstChange = edit.textChanges[0]!;
  const oversizedEdit: NormalizedWorkspaceEdit = {
    textChanges: [{
      ...firstChange,
      edits: [{
        ...firstChange.edits[0]!,
        newText: 'x'.repeat(RENAME_PREVIEW_LIMITS.textCharacters + 1),
      }],
    }, edit.textChanges[1]!],
    targets: edit.targets,
  };
  state.connector.previewResponse = { status: 'completed', normalizedEdit: oversizedEdit };
  const response = await state.service.renamePreview(input);
  assert.equal(response.ok, false);
  if (response.ok) return;
  assert.equal(response.error.code, 'PREVIEW_TOO_LARGE');
  if (response.error.code !== 'PREVIEW_TOO_LARGE') return;
  assert.equal(response.error.details.changedFiles, 2);
  assert.equal(response.error.details.edits, 2);
  assert.ok(response.error.details.textCharacters > RENAME_PREVIEW_LIMITS.textCharacters);
  assert.equal(JSON.stringify(response).includes('x'.repeat(100)), false);
  assert.equal(state.cache.stats().activePreviews, 0);
});

test('prepare rejection becomes an actionable public error without exposing provider text', async () => {
  const state = fixture();
  state.connector.previewResponse = { status: 'prepareRejected', reason: 'notRenameable' };
  const response = await state.service.renamePreview(input);
  assert.deepEqual(response, {
    ok: false,
    error: {
      code: 'PROVIDER_UNAVAILABLE',
      message: 'Rename is not available at this position. Move to a renameable symbol and retry.',
      retryable: false,
    },
  });
  assert.equal(state.cache.stats().activePreviews, 0);
});

test('stale, expired, path-invalid, and repeated rename apply preserve preview state semantics', async () => {
  const staleState = fixture();
  const stalePreview = await staleState.service.renamePreview(input);
  assert.equal(stalePreview.ok, true);
  if (!stalePreview.ok) return;
  staleState.connector.applyResponse = {
    status: 'documentChanged',
    reason: 'content',
    files: ['src/a.ts'],
  };
  assert.deepEqual(await staleState.service.renameApply({ previewId: stalePreview.data.previewId }), {
    ok: false,
    error: {
      code: 'DOCUMENT_CHANGED',
      message: 'A mutation target changed after the preview was created.',
      retryable: false,
      details: { reason: 'content', files: ['src/a.ts'] },
    },
  });
  assert.equal(staleState.connector.previewSessions.length, 1);

  const expiredState = fixture();
  const expiredPreview = await expiredState.service.renamePreview(input);
  assert.equal(expiredPreview.ok, true);
  if (!expiredPreview.ok) return;
  expiredState.clock.setNow(300_000);
  assert.deepEqual(await expiredState.service.renameApply({ previewId: expiredPreview.data.previewId }), {
    ok: false,
    error: {
      code: 'PREVIEW_EXPIRED',
      message: 'The preview has expired.',
      retryable: false,
    },
  });
  assert.equal(expiredState.connector.applySessions.length, 0);

  const outsideState = fixture();
  const outsidePreview = await outsideState.service.renamePreview(input);
  assert.equal(outsidePreview.ok, true);
  if (!outsidePreview.ok) return;
  outsideState.connector.applyResponse = { status: 'pathOutsideWorkspace' };
  assert.deepEqual(await outsideState.service.renameApply({ previewId: outsidePreview.data.previewId }), {
    ok: false,
    error: {
      code: 'PATH_OUTSIDE_WORKSPACE',
      message: 'A mutation target is outside the selected workspace.',
      retryable: false,
    },
  });
  assert.deepEqual(await outsideState.service.renameApply({ previewId: outsidePreview.data.previewId }), {
    ok: false,
    error: {
      code: 'PREVIEW_NOT_FOUND',
      message: 'The preview is unavailable or has already been consumed.',
      retryable: false,
    },
  });
});

test('mutation client session IDs use one bounded 128-bit random value', () => {
  let calls = 0;
  const primitives: RuntimePrimitives = {
    monotonicNowMs: () => 0,
    secureRandomBytes: (length) => {
      calls += 1;
      assert.equal(length, 16);
      return new Uint8Array(16).fill(7);
    },
    sha256Hex: () => 'a'.repeat(64),
  };
  assert.match(createMutationClientSessionId(primitives), /^client_[A-Za-z0-9_-]{22}$/u);
  assert.equal(calls, 1);
});
