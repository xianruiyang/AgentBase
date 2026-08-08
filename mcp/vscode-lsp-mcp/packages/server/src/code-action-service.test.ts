import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import type {
  JsonObject,
  NormalizedWorkspaceEdit,
  RuntimePrimitives,
  TextDocumentSnapshot,
  WorkspaceRouteIdentity,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  ACTION_SET_TTL_MS,
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
  generation: 5,
};

const snapshot = (post = 'd'): TextDocumentSnapshot => ({
  file: 'src/a.ts',
  internalUri: 'file:///workspace/src/a.ts',
  rootAlias: 'app',
  boundaryFingerprint: 'a'.repeat(64),
  documentEpoch: 1,
  documentVersion: 3,
  memoryContentSha256: 'b'.repeat(64),
  eol: 'lf',
  encoding: 'utf16-code-units',
  diskExists: true,
  diskByteSha256: 'c'.repeat(64),
  expectedPostContentSha256: post.repeat(64),
});

const normalizedEdit = (newText: string, post: string): NormalizedWorkspaceEdit => ({
  textChanges: [{
    kind: 'text',
    file: 'src/a.ts',
    edits: [{
      range: { startLine: 1, startColumn: 1, endLine: 1, endColumn: 4 },
      startOffset: 0,
      endOffset: 3,
      oldText: 'old',
      newText,
      providerOrdinal: 0,
    }],
  }],
  targets: [snapshot(post)],
});

const listResponse = () => ({
  status: 'completed',
  sourceSnapshot: snapshot(),
  candidates: [
    {
      title: 'Preferred fix',
      kind: 'quickfix',
      preferred: true,
      normalizedEdit: normalizedEdit('preferred', 'e'),
    },
    {
      title: 'Secondary fix',
      kind: 'refactor.rewrite',
      preferred: false,
      normalizedEdit: normalizedEdit('secondary', 'f'),
    },
  ],
  available: 2,
  warnings: ['code_action_command_filtered'],
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
  bindingResponse: unknown = listResponse();
  readonly bindingSessions: FakeSession[] = [];
  readonly routeRequests: WorkspaceRouteIdentity[] = [];
  readonly routeResponses: unknown[] = [];
  readonly routeSessions: FakeSession[] = [];

  connectWorkspaceBinding(workspaceId: string): Promise<ConnectedWorkspaceRoute> {
    assert.equal(workspaceId, workspace.workspaceId);
    const session = new FakeSession(this.bindingResponse);
    this.bindingSessions.push(session);
    return Promise.resolve({ workspace, session });
  }

  connectWorkspaceRoute(route: WorkspaceRouteIdentity): Promise<BridgeProbeSession> {
    this.routeRequests.push(route);
    const session = new FakeSession(this.routeResponses.shift() ?? { status: 'failed' });
    this.routeSessions.push(session);
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

const input = {
  workspaceId: workspace.workspaceId,
  file: 'src/a.ts',
  range: { startLine: 1, startColumn: 1, endLine: 1, endColumn: 4 },
  onlyKinds: ['quickfix', 'refactor'],
  resultStart: 1,
  resultEnd: 10,
};

const fixture = () => {
  const clock = runtime();
  const cache = createMutationCacheForTesting({ primitives: clock.primitives });
  const connector = new FakeConnector();
  const service = new MutationService({ cache, clientSessionId: 'client-a', connector });
  return { cache, clock, connector, service };
};

test('Code Action list, one-shot preview, and apply share cached DTOs without rerunning Provider', async () => {
  const state = fixture();
  const listed = await state.service.codeActions(input);
  assert.equal(listed.ok, true);
  if (!listed.ok) return;
  assert.match(listed.data.actionSetId ?? '', /^as_[A-Za-z0-9_-]{22}$/u);
  assert.deepEqual(listed.data.results.map((action) => action.title), [
    'Preferred fix',
    'Secondary fix',
  ]);
  assert.deepEqual(listed.data.warnings, ['code_action_command_filtered']);
  const publicJson = JSON.stringify(listed);
  for (const forbidden of [
    'preferred',
    'internalUri',
    'Sha256',
    'documentEpoch',
    'providerOrdinal',
    'startOffset',
  ]) {
    assert.equal(publicJson.includes(forbidden), false);
  }
  assert.equal(state.connector.bindingSessions[0]?.calls[0]?.method, 'mutation.codeActions');
  assert.equal(state.connector.bindingSessions[0]?.closed, true);

  const first = listed.data.results[0]!;
  state.connector.routeResponses.push(
    { status: 'ready' },
    { status: 'applied', changedFiles: ['src/a.ts'] },
  );
  const preview = await state.service.codeActionPreview({
    actionSetId: listed.data.actionSetId,
    actionId: first.actionId,
  });
  assert.equal(preview.ok, true);
  if (!preview.ok) return;
  assert.equal(state.connector.bindingSessions.length, 1);
  assert.equal(state.connector.routeSessions[0]?.calls[0]?.method, 'mutation.codeActionPreview');
  assert.deepEqual(preview.data.changes.map((change) => change.file), ['src/a.ts']);

  assert.deepEqual(await state.service.codeActionApply({ previewId: preview.data.previewId }), {
    ok: true,
    data: { changedFiles: ['src/a.ts'] },
  });
  assert.equal(state.connector.routeSessions[1]?.calls[0]?.method, 'mutation.apply');
  assert.deepEqual(await state.service.codeActionPreview({
    actionSetId: listed.data.actionSetId,
    actionId: first.actionId,
  }), {
    ok: false,
    error: {
      code: 'ACTION_SET_NOT_FOUND',
      message: 'The Code Action candidate is unavailable, expired, or has already been consumed.',
      retryable: false,
    },
  });
});

test('document changes invalidate siblings, while candidate-local failures consume only one action', async () => {
  const changed = fixture();
  const changedList = await changed.service.codeActions(input);
  assert.equal(changedList.ok, true);
  if (!changedList.ok) return;
  changed.connector.routeResponses.push({
    status: 'documentChanged',
    reason: 'content',
    files: ['src/a.ts'],
  });
  assert.deepEqual(await changed.service.codeActionPreview({
    actionSetId: changedList.data.actionSetId,
    actionId: changedList.data.results[0]!.actionId,
  }), {
    ok: false,
    error: {
      code: 'DOCUMENT_CHANGED',
      message: 'A Code Action source or target changed after the candidates were listed.',
      retryable: false,
      details: { reason: 'content', files: ['src/a.ts'] },
    },
  });
  assert.equal(changed.cache.stats().actionSets, 0);
  assert.equal((await changed.service.codeActionPreview({
    actionSetId: changedList.data.actionSetId,
    actionId: changedList.data.results[1]!.actionId,
  })).ok, false);
  assert.equal(changed.connector.routeSessions.length, 1);

  const local = fixture();
  const localList = await local.service.codeActions(input);
  assert.equal(localList.ok, true);
  if (!localList.ok) return;
  local.connector.routeResponses.push(
    { status: 'actionNotPreviewable', reason: 'cachedActionInvalid' },
    { status: 'ready' },
  );
  const rejected = await local.service.codeActionPreview({
    actionSetId: localList.data.actionSetId,
    actionId: localList.data.results[0]!.actionId,
  });
  assert.equal(rejected.ok, false);
  if (rejected.ok) return;
  assert.equal(rejected.error.code, 'ACTION_NOT_PREVIEWABLE');
  assert.equal(local.cache.stats().actionSets, 1);
  assert.equal((await local.service.codeActionPreview({
    actionSetId: localList.data.actionSetId,
    actionId: localList.data.results[1]!.actionId,
  })).ok, true);
});

test('ActionSet expiry and client ownership both fail closed without consuming another client set', async () => {
  const state = fixture();
  const listed = await state.service.codeActions(input);
  assert.equal(listed.ok, true);
  if (!listed.ok) return;
  const otherClient = new MutationService({
    cache: state.cache,
    clientSessionId: 'client-b',
    connector: state.connector,
  });
  const action = listed.data.results[0]!;
  assert.equal((await otherClient.codeActionPreview({
    actionSetId: listed.data.actionSetId,
    actionId: action.actionId,
  })).ok, false);
  assert.equal(state.cache.stats().actionSets, 1);

  state.clock.setNow(ACTION_SET_TTL_MS);
  assert.equal((await state.service.codeActionPreview({
    actionSetId: listed.data.actionSetId,
    actionId: action.actionId,
  })).ok, false);
  assert.equal(state.cache.stats().actionSets, 0);
  assert.equal(state.connector.routeSessions.length, 0);
});
