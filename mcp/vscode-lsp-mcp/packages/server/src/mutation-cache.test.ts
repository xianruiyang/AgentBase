import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import type {
  NormalizedWorkspaceEdit,
  RuntimePrimitives,
  TextDocumentSnapshot,
  WorkspaceRouteIdentity,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  ACTION_SET_TTL_MS,
  MUTATION_CACHE_LIMITS,
  PREVIEW_ACTIVE_TTL_MS,
  PREVIEW_TOMBSTONE_TTL_MS,
  MutationCacheError,
  createMutationCache,
  createMutationCacheForTesting,
  type MutationCache,
  type MutationCacheIdentity,
} from './mutation-cache.js';

interface FakeRuntime {
  readonly primitives: RuntimePrimitives;
  setNow(value: number): void;
}

const fakeRuntime = (constantRandom = false): FakeRuntime => {
  let now = 0;
  let randomCall = 0;
  return {
    primitives: {
      monotonicNowMs: () => now,
      secureRandomBytes: (length) => {
        const bytes = new Uint8Array(length);
        const value = constantRandom ? 1 : ++randomCall;
        new DataView(bytes.buffer).setUint32(length - 4, value);
        return bytes;
      },
      sha256Hex: (input) => createHash('sha256').update(input).digest('hex'),
    },
    setNow: (value) => {
      now = value;
    },
  };
};

const identity = (
  clientSessionId = 'client-a',
  workspaceId = 'ws_AAAAAAAAAAAAAAAAAAAAAA',
  generation = 1,
): MutationCacheIdentity => ({
  clientSessionId,
  workspace: {
    workspaceId: workspaceId as WorkspaceRouteIdentity['workspaceId'],
    generation,
  },
});

const normalizedEdit = (file = 'src/a.ts', newText = 'replacement'): NormalizedWorkspaceEdit => ({
  textChanges: [{
    kind: 'text',
    file,
    edits: [{
      range: {
        startLine: 1,
        startColumn: 1,
        endLine: 1,
        endColumn: 4,
      },
      startOffset: 0,
      endOffset: 3,
      oldText: 'old',
      newText,
      providerOrdinal: 0,
    }],
  }],
  targets: [{
    file,
    internalUri: `file:///workspace/${file}`,
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

const sourceSnapshot = (edit: NormalizedWorkspaceEdit): TextDocumentSnapshot => edit.targets[0]!;

const commitPreview = (
  cache: MutationCache,
  cacheIdentity = identity(),
  edit = normalizedEdit(),
): string => {
  const result = cache.commitPreview({
    identity: cacheIdentity,
    operationKind: 'rename',
    requestSummary: { symbol: 'old' },
    normalizedEdit: edit,
  });
  assert.ok(result.previewId);
  return result.previewId;
};

const commitActionSet = (
  cache: MutationCache,
  cacheIdentity = identity(),
  candidateCount = 2,
) => {
  const edit = normalizedEdit();
  const result = cache.commitActionSet({
    identity: cacheIdentity,
    requestSummary: { file: 'src/a.ts', line: 1, column: 1 },
    sourceSnapshot: sourceSnapshot(edit),
    candidates: Array.from({ length: candidateCount }, (_, index) => ({
      title: `Action ${index + 1}`,
      kind: 'quickfix',
      normalizedEdit: normalizedEdit('src/a.ts', `replacement-${index}`),
    })),
    available: candidateCount,
  });
  assert.ok(result.actionSetId);
  return { ...result, actionSetId: result.actionSetId };
};

test('production and deterministic test factories allocate opaque 128-bit handles', () => {
  assert.equal(createMutationCache.length, 0);
  const productionId = commitPreview(createMutationCache());
  assert.match(productionId, /^pv_[A-Za-z0-9_-]{22}$/u);

  const runtime = fakeRuntime();
  const cache = createMutationCacheForTesting({ primitives: runtime.primitives });
  const previewId = commitPreview(cache);
  const actionSet = commitActionSet(cache);
  assert.match(previewId, /^pv_[A-Za-z0-9_-]{22}$/u);
  assert.match(actionSet.actionSetId, /^as_[A-Za-z0-9_-]{22}$/u);
  for (const action of actionSet.actions) assert.match(action.actionId, /^ac_[A-Za-z0-9_-]{22}$/u);
});

test('preview cache owns its JSON payload and exposes only its opaque id on commit', () => {
  const runtime = fakeRuntime();
  const cache = createMutationCacheForTesting({ primitives: runtime.primitives });
  const edit = normalizedEdit();
  const result = cache.commitPreview({
    identity: identity(),
    operationKind: 'rename',
    requestSummary: { symbol: 'old' },
    normalizedEdit: edit,
  });
  assert.deepEqual(Object.keys(result), ['previewId']);
  assert.ok(result.previewId);

  const mutableEdit = edit as unknown as {
    textChanges: Array<{ edits: Array<{ newText: string }> }>;
    targets: Array<{ internalUri: string }>;
  };
  mutableEdit.textChanges[0]!.edits[0]!.newText = 'tampered';
  mutableEdit.targets[0]!.internalUri = 'file:///outside.ts';
  const found = cache.peekPreview(identity(), result.previewId);
  assert.equal(found.status, 'active');
  if (found.status === 'active') {
    assert.match(found.preview.applyAttemptId, /^ap_[A-Za-z0-9_-]{22}$/u);
    assert.equal(found.preview.normalizedEdit.textChanges[0]?.edits[0]?.newText, 'replacement');
    assert.equal(found.preview.normalizedEdit.targets[0]?.internalUri, 'file:///workspace/src/a.ts');
    assert.equal(Object.isFrozen(found.preview.normalizedEdit.targets[0]), true);
  }
});

test('preview binding, claim, applying, and completion semantics prevent replay', () => {
  const runtime = fakeRuntime();
  const cache = createMutationCacheForTesting({ primitives: runtime.primitives });
  const owner = identity();
  const previewId = commitPreview(cache, owner);
  assert.equal(cache.peekPreview(identity('client-b'), previewId).status, 'notFound');
  assert.equal(cache.peekPreview(identity('client-a', 'ws_BBBBBBBBBBBBBBBBBBBBBB'), previewId).status, 'notFound');
  assert.equal(cache.peekPreview(owner, previewId).status, 'active');

  const first = cache.claimPreview(owner, previewId);
  assert.equal(first.status, 'claimed');
  assert.equal(cache.claimPreview(owner, previewId).status, 'notFound');
  assert.equal(cache.peekPreview(owner, previewId).status, 'notFound');
  const applyingStats = cache.stats();
  assert.equal(applyingStats.activePreviews, 0);
  assert.equal(applyingStats.applyingPreviews, 1);
  assert.equal(applyingStats.actionSets, 0);
  assert.equal(applyingStats.previewTombstones, 0);
  assert.ok(applyingStats.totalChargeBytes > 0);
  if (first.status === 'claimed') {
    assert.equal(cache.completePreviewClaim({ preview: first.claim.preview }), false);
    assert.equal(cache.completePreviewClaim(first.claim), true);
    assert.equal(cache.completePreviewClaim(first.claim), false);
  }
  assert.equal(cache.claimPreview(owner, previewId).status, 'notFound');
  assert.equal(cache.stats().totalChargeBytes, 0);
  assert.equal(cache.stats().previewTombstones, 1);
});

test('preview TTL and tombstone TTL use exact monotonic boundaries without refresh', () => {
  const runtime = fakeRuntime();
  const cache = createMutationCacheForTesting({ primitives: runtime.primitives });
  const previewId = commitPreview(cache);
  runtime.setNow(PREVIEW_ACTIVE_TTL_MS - 1);
  assert.equal(cache.peekPreview(identity(), previewId).status, 'active');
  runtime.setNow(PREVIEW_ACTIVE_TTL_MS);
  assert.equal(cache.peekPreview(identity(), previewId).status, 'expired');
  runtime.setNow(PREVIEW_ACTIVE_TTL_MS + PREVIEW_TOMBSTONE_TTL_MS - 1);
  assert.equal(cache.peekPreview(identity(), previewId).status, 'expired');
  runtime.setNow(PREVIEW_ACTIVE_TTL_MS + PREVIEW_TOMBSTONE_TTL_MS);
  assert.equal(cache.peekPreview(identity(), previewId).status, 'notFound');
});

test('empty results allocate no handles or cache payloads', () => {
  const runtime = fakeRuntime();
  const cache = createMutationCacheForTesting({ primitives: runtime.primitives });
  const preview = cache.commitPreview({
    identity: identity(),
    operationKind: 'format',
    requestSummary: {},
    normalizedEdit: { textChanges: [], targets: [] },
  });
  const actions = cache.commitActionSet({
    identity: identity(),
    requestSummary: {},
    sourceSnapshot: sourceSnapshot(normalizedEdit()),
    candidates: [],
    available: 0,
  });
  assert.deepEqual(preview, {});
  assert.deepEqual(actions, { actions: [], available: 0 });
  assert.deepEqual(cache.stats(), {
    activePreviews: 0,
    applyingPreviews: 0,
    actionSets: 0,
    previewTombstones: 0,
    totalChargeBytes: 0,
  });
});

test('action-set results exclude cached edits and claims consume exactly one action', () => {
  const runtime = fakeRuntime();
  const cache = createMutationCacheForTesting({ primitives: runtime.primitives });
  const actionSet = commitActionSet(cache);
  const publicJson = JSON.stringify(actionSet);
  for (const forbidden of ['normalizedEdit', 'sourceSnapshot', 'internalUri', 'Sha256']) {
    assert.equal(publicJson.includes(forbidden), false);
  }
  const firstAction = actionSet.actions[0]!;
  const secondAction = actionSet.actions[1]!;
  assert.equal(
    cache.claimActionForClient('client-b', actionSet.actionSetId, firstAction.actionId).status,
    'notFound',
  );
  assert.equal(cache.claimAction(identity('client-b'), actionSet.actionSetId, firstAction.actionId).status, 'notFound');
  const first = cache.claimActionForClient('client-a', actionSet.actionSetId, firstAction.actionId);
  assert.equal(first.status, 'claimed');
  assert.equal(cache.claimAction(identity(), actionSet.actionSetId, firstAction.actionId).status, 'notFound');
  const second = cache.claimAction(identity(), actionSet.actionSetId, secondAction.actionId);
  assert.equal(second.status, 'claimed');
  assert.equal(cache.stats().actionSets, 0);
});

test('action-set cache owns and freezes source snapshots and normalized edits', () => {
  const runtime = fakeRuntime();
  const cache = createMutationCacheForTesting({ primitives: runtime.primitives });
  const edit = normalizedEdit();
  const source = sourceSnapshot(edit);
  const candidate = normalizedEdit('src/a.ts', 'owned-replacement');
  const result = cache.commitActionSet({
    identity: identity(),
    requestSummary: { file: 'src/a.ts' },
    sourceSnapshot: source,
    candidates: [{ title: 'Owned action', normalizedEdit: candidate }],
    available: 1,
  });
  assert.ok(result.actionSetId);
  const mutableSource = source as unknown as { internalUri: string };
  mutableSource.internalUri = 'file:///tampered.ts';
  const mutableCandidate = candidate as unknown as {
    textChanges: Array<{ edits: Array<{ newText: string }> }>;
  };
  mutableCandidate.textChanges[0]!.edits[0]!.newText = 'tampered';
  const claimed = cache.claimAction(identity(), result.actionSetId, result.actions[0]!.actionId);
  assert.equal(claimed.status, 'claimed');
  if (claimed.status === 'claimed') {
    assert.equal(claimed.claim.sourceSnapshot.internalUri, 'file:///workspace/src/a.ts');
    assert.equal(claimed.claim.action.normalizedEdit.textChanges[0]?.edits[0]?.newText, 'owned-replacement');
    assert.equal(Object.isFrozen(claimed.claim.sourceSnapshot), true);
    assert.equal(Object.isFrozen(claimed.claim.action.normalizedEdit), true);
  }
});

test('action-set invalidation removes unclaimed siblings and TTL does not refresh', () => {
  const runtime = fakeRuntime();
  const cache = createMutationCacheForTesting({ primitives: runtime.primitives });
  const firstSet = commitActionSet(cache);
  const firstClaim = cache.claimAction(identity(), firstSet.actionSetId, firstSet.actions[0]!.actionId);
  assert.equal(firstClaim.status, 'claimed');
  if (firstClaim.status === 'claimed') {
    assert.equal(cache.invalidateActionSet(firstClaim.claim), true);
    assert.equal(cache.invalidateActionSet(firstClaim.claim), false);
  }
  assert.equal(
    cache.claimAction(identity(), firstSet.actionSetId, firstSet.actions[1]!.actionId).status,
    'notFound',
  );

  const expiringSet = commitActionSet(cache);
  runtime.setNow(ACTION_SET_TTL_MS - 1);
  assert.equal(
    cache.claimAction(identity('client-b'), expiringSet.actionSetId, expiringSet.actions[0]!.actionId).status,
    'notFound',
  );
  runtime.setNow(ACTION_SET_TTL_MS);
  assert.equal(
    cache.claimAction(identity(), expiringSet.actionSetId, expiringSet.actions[0]!.actionId).status,
    'notFound',
  );
});

test('per-workspace and per-client capacity evict the oldest active preview', () => {
  assert.deepEqual(MUTATION_CACHE_LIMITS, {
    previewsPerClient: 64,
    previewsPerWorkspace: 16,
    actionSetsPerClient: 32,
    actionSetsPerWorkspace: 8,
    tombstonesPerClient: 256,
    sharedBytes: 64 * 1024 * 1024,
    frameBytes: 16 * 1024 * 1024,
  });
  const workspaceRuntime = fakeRuntime();
  const workspaceCache = createMutationCacheForTesting({ primitives: workspaceRuntime.primitives });
  const workspaceIds = Array.from({ length: 17 }, () => commitPreview(workspaceCache));
  assert.equal(workspaceCache.peekPreview(identity(), workspaceIds[0]!).status, 'notFound');
  assert.equal(workspaceCache.stats().activePreviews, 16);

  const clientRuntime = fakeRuntime();
  const clientCache = createMutationCacheForTesting({ primitives: clientRuntime.primitives });
  const clientIds = Array.from({ length: 65 }, (_, index) => commitPreview(
    clientCache,
    identity('client-a', `ws_${String(index).padStart(22, 'A')}`),
  ));
  assert.equal(clientCache.peekPreview(identity('client-a', `ws_${'0'.padStart(22, 'A')}`), clientIds[0]!).status, 'notFound');
  assert.equal(clientCache.stats().activePreviews, 64);
});

test('per-workspace and per-client capacity evict the oldest action set', () => {
  const workspaceRuntime = fakeRuntime();
  const workspaceCache = createMutationCacheForTesting({ primitives: workspaceRuntime.primitives });
  const workspaceSets = Array.from({ length: 9 }, () => commitActionSet(workspaceCache));
  assert.equal(
    workspaceCache.claimAction(identity(), workspaceSets[0]!.actionSetId, workspaceSets[0]!.actions[0]!.actionId).status,
    'notFound',
  );
  assert.equal(workspaceCache.stats().actionSets, 8);

  const clientRuntime = fakeRuntime();
  const clientCache = createMutationCacheForTesting({ primitives: clientRuntime.primitives });
  const clientSets = Array.from({ length: 33 }, (_, index) => commitActionSet(
    clientCache,
    identity('client-a', `ws_${String(index).padStart(22, 'B')}`),
  ));
  assert.equal(
    clientCache.claimAction(
      identity('client-a', `ws_${'0'.padStart(22, 'B')}`),
      clientSets[0]!.actionSetId,
      clientSets[0]!.actions[0]!.actionId,
    ).status,
    'notFound',
  );
  assert.equal(clientCache.stats().actionSets, 32);
});

test('shared byte pressure evicts active payloads but never an applying preview', () => {
  const sizingRuntime = fakeRuntime();
  const sizingCache = createMutationCacheForTesting({ primitives: sizingRuntime.primitives });
  commitPreview(sizingCache);
  const charge = sizingCache.stats().totalChargeBytes;
  assert.ok(charge > 0);
  const limits = { sharedBytes: charge * 2 - 1, frameBytes: charge };

  const evictionRuntime = fakeRuntime();
  const evictionCache = createMutationCacheForTesting({ primitives: evictionRuntime.primitives, limits });
  const firstId = commitPreview(evictionCache);
  commitPreview(evictionCache);
  assert.equal(evictionCache.peekPreview(identity(), firstId).status, 'notFound');
  assert.equal(evictionCache.stats().activePreviews, 1);
  assert.ok(evictionCache.stats().totalChargeBytes <= limits.sharedBytes);

  const applyingRuntime = fakeRuntime();
  const applyingCache = createMutationCacheForTesting({ primitives: applyingRuntime.primitives, limits });
  const applyingId = commitPreview(applyingCache);
  assert.equal(applyingCache.claimPreview(identity(), applyingId).status, 'claimed');
  assert.throws(
    () => commitPreview(applyingCache),
    (error: unknown) => error instanceof MutationCacheError && error.reason === 'capacity',
  );
  assert.equal(applyingCache.stats().applyingPreviews, 1);
  assert.equal(applyingCache.stats().totalChargeBytes, charge);
});

test('failed shared-budget admission restores active entries evicted during planning', () => {
  const smallSizingRuntime = fakeRuntime();
  const smallSizingCache = createMutationCacheForTesting({ primitives: smallSizingRuntime.primitives });
  commitPreview(smallSizingCache);
  const smallCharge = smallSizingCache.stats().totalChargeBytes;

  const largeEdit = normalizedEdit('src/a.ts', 'x'.repeat(smallCharge * 3));
  const largeSizingRuntime = fakeRuntime();
  const largeSizingCache = createMutationCacheForTesting({ primitives: largeSizingRuntime.primitives });
  commitPreview(largeSizingCache, identity(), largeEdit);
  const largeCharge = largeSizingCache.stats().totalChargeBytes;
  assert.ok(largeCharge > smallCharge * 2);

  const runtime = fakeRuntime();
  const cache = createMutationCacheForTesting({
    primitives: runtime.primitives,
    limits: { sharedBytes: largeCharge, frameBytes: largeCharge },
  });
  const applyingId = commitPreview(cache);
  const activeId = commitPreview(cache);
  assert.equal(cache.claimPreview(identity(), applyingId).status, 'claimed');
  assert.throws(
    () => commitPreview(cache, identity(), largeEdit),
    (error: unknown) => error instanceof MutationCacheError && error.reason === 'capacity',
  );
  assert.equal(cache.peekPreview(identity(), activeId).status, 'active');
  assert.equal(cache.stats().activePreviews, 1);
  assert.equal(cache.stats().applyingPreviews, 1);
  assert.equal(cache.stats().totalChargeBytes, smallCharge * 2);
});

test('frame limits, malformed JSON, broken clocks, and random collisions fail closed', () => {
  const sizingRuntime = fakeRuntime();
  const sizingCache = createMutationCacheForTesting({ primitives: sizingRuntime.primitives });
  commitPreview(sizingCache);
  const charge = sizingCache.stats().totalChargeBytes;

  const boundedRuntime = fakeRuntime();
  const bounded = createMutationCacheForTesting({
    primitives: boundedRuntime.primitives,
    limits: { sharedBytes: charge - 1, frameBytes: charge - 1 },
  });
  assert.throws(
    () => commitPreview(bounded),
    (error: unknown) => error instanceof MutationCacheError && error.reason === 'capacity',
  );
  assert.equal(bounded.stats().totalChargeBytes, 0);

  const payloadRuntime = fakeRuntime();
  const payloadCache = createMutationCacheForTesting({ primitives: payloadRuntime.primitives });
  assert.throws(
    () => payloadCache.commitPreview({
      identity: identity(),
      operationKind: 'rename',
      requestSummary: { bad: undefined } as unknown as Record<string, never>,
      normalizedEdit: normalizedEdit(),
    }),
    (error: unknown) => error instanceof MutationCacheError && error.reason === 'payload',
  );

  const clockRuntime = fakeRuntime();
  const clockCache = createMutationCacheForTesting({ primitives: clockRuntime.primitives });
  clockCache.stats();
  clockRuntime.setNow(-1);
  assert.throws(
    () => clockCache.stats(),
    (error: unknown) => error instanceof MutationCacheError && error.reason === 'clock',
  );

  const collisionRuntime = fakeRuntime(true);
  const collisionCache = createMutationCacheForTesting({ primitives: collisionRuntime.primitives });
  commitPreview(collisionCache);
  assert.throws(
    () => commitPreview(collisionCache),
    (error: unknown) => error instanceof MutationCacheError && error.reason === 'randomness',
  );
});

test('preview tombstones are bounded per client and carry no payload charge', () => {
  const runtime = fakeRuntime();
  const cache = createMutationCacheForTesting({ primitives: runtime.primitives });
  for (let index = 0; index < MUTATION_CACHE_LIMITS.tombstonesPerClient + 1; index += 1) {
    const previewId = commitPreview(cache);
    const claimed = cache.claimPreview(identity(), previewId);
    assert.equal(claimed.status, 'claimed');
    if (claimed.status === 'claimed') assert.equal(cache.completePreviewClaim(claimed.claim), true);
  }
  assert.equal(cache.stats().previewTombstones, MUTATION_CACHE_LIMITS.tombstonesPerClient);
  assert.equal(cache.stats().totalChargeBytes, 0);
});
