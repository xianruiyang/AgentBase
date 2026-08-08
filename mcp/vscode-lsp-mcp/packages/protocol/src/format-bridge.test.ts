import assert from 'node:assert/strict';
import test from 'node:test';
import type {
  NormalizedWorkspaceEdit,
  TextDocumentSnapshot,
  WorkspaceRouteIdentity,
} from './index.js';
import {
  parseFormatPreviewBridgeRequest,
  parseFormatPreviewBridgeResponse,
} from './format-bridge.js';

const workspace: WorkspaceRouteIdentity = {
  workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA' as WorkspaceRouteIdentity['workspaceId'],
  generation: 9,
};

const target: TextDocumentSnapshot = {
  file: 'src/a.ts',
  internalUri: 'file:///workspace/src/a.ts',
  rootAlias: 'app',
  boundaryFingerprint: 'a'.repeat(64),
  documentEpoch: 2,
  documentVersion: 6,
  memoryContentSha256: 'b'.repeat(64),
  eol: 'lf',
  encoding: 'utf16-code-units',
  diskExists: true,
  diskByteSha256: 'c'.repeat(64),
  expectedPostContentSha256: 'd'.repeat(64),
};

const normalizedEdit: NormalizedWorkspaceEdit = {
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
  targets: [target],
};

test('format preview bridge accepts document/range requests and closes formatting options', () => {
  assert.deepEqual(parseFormatPreviewBridgeRequest({
    workspace,
    file: 'src/a.ts',
  }), {
    workspace,
    file: 'src/a.ts',
  });
  const ranged = parseFormatPreviewBridgeRequest({
    workspace,
    file: 'src/a.ts',
    range: { startLine: 1, startColumn: 2, endLine: 3, endColumn: 1 },
    options: { tabSize: 2 },
  });
  assert.deepEqual(ranged.options, { tabSize: 2 });
  assert.throws(() => parseFormatPreviewBridgeRequest({ ...ranged, injected: true }));
  assert.throws(() => parseFormatPreviewBridgeRequest({ ...ranged, options: {} }));
  assert.throws(() => parseFormatPreviewBridgeRequest({
    ...ranged,
    range: { startLine: 2, startColumn: 1, endLine: 1, endColumn: 1 },
  }));
});

test('format preview bridge preserves empty/complete previews and closed terminal details', () => {
  assert.deepEqual(parseFormatPreviewBridgeResponse({
    status: 'completed',
    normalizedEdit: { textChanges: [], targets: [] },
  }), {
    status: 'completed',
    normalizedEdit: { textChanges: [], targets: [] },
  });
  const completed = parseFormatPreviewBridgeResponse({ status: 'completed', normalizedEdit });
  assert.equal(completed.status, 'completed');
  assert.deepEqual(parseFormatPreviewBridgeResponse({
    status: 'editConflict',
    reason: 'overlappingEdits',
    files: ['src/a.ts'],
  }), {
    status: 'editConflict',
    reason: 'overlappingEdits',
    files: ['src/a.ts'],
  });
  assert.throws(() => parseFormatPreviewBridgeResponse({
    status: 'documentChanged',
    reason: 'providerSpecific',
  }));
  assert.throws(() => parseFormatPreviewBridgeResponse({
    status: 'completed',
    normalizedEdit,
    internalUri: 'file:///hidden',
  }));
});
