import assert from 'node:assert/strict';
import test from 'node:test';
import type {
  NormalizedWorkspaceEdit,
  TextDocumentSnapshot,
  WorkspaceRouteIdentity,
} from './index.js';
import {
  parseCodeActionPreviewBridgeRequest,
  parseCodeActionPreviewBridgeResponse,
  parseCodeActionsBridgeRequest,
  parseCodeActionsBridgeResponse,
} from './code-action-bridge.js';

const workspace: WorkspaceRouteIdentity = {
  workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA' as WorkspaceRouteIdentity['workspaceId'],
  generation: 4,
};

const snapshot: TextDocumentSnapshot = {
  file: 'src/a.ts',
  internalUri: 'file:///workspace/src/a.ts',
  rootAlias: 'app',
  boundaryFingerprint: 'a'.repeat(64),
  documentEpoch: 2,
  documentVersion: 7,
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
      newText: 'next',
      providerOrdinal: 0,
    }],
  }],
  targets: [snapshot],
};

test('Code Action bridge parsers accept only the bounded internal list contract', () => {
  const request = parseCodeActionsBridgeRequest({
    workspace,
    file: 'src/a.ts',
    range: { startLine: 1, startColumn: 1, endLine: 1, endColumn: 4 },
    onlyKinds: ['quickfix'],
    resultStart: 1,
    resultEnd: 25,
  });
  assert.deepEqual(request.onlyKinds, ['quickfix']);
  assert.throws(() => parseCodeActionsBridgeRequest({ ...request, injected: true }));
  assert.throws(() => parseCodeActionsBridgeRequest({ ...request, resultEnd: 101 }));
  assert.throws(() => parseCodeActionsBridgeRequest({
    ...request,
    range: { startLine: 2, startColumn: 1, endLine: 1, endColumn: 1 },
  }));

  const response = parseCodeActionsBridgeResponse({
    status: 'completed',
    sourceSnapshot: snapshot,
    candidates: [{
      title: 'Add missing import',
      kind: 'quickfix.import',
      preferred: true,
      normalizedEdit,
    }],
    available: 1,
    warnings: ['code_action_command_filtered'],
  });
  assert.equal(response.status, 'completed');
  if (response.status !== 'completed') return;
  assert.equal(response.candidates[0]?.preferred, true);
  assert.throws(() => parseCodeActionsBridgeResponse({
    ...response,
    candidates: [{ ...response.candidates[0], command: 'extension.privateCommand' }],
  }));
});

test('Code Action preview bridge freezes the cached-edit contract and public reason union', () => {
  const request = parseCodeActionPreviewBridgeRequest({
    workspace,
    sourceSnapshot: snapshot,
    normalizedEdit,
  });
  assert.equal(request.normalizedEdit.targets[0]?.internalUri, snapshot.internalUri);
  assert.throws(() => parseCodeActionPreviewBridgeRequest({ ...request, actionId: 'ac_hidden' }));

  assert.deepEqual(parseCodeActionPreviewBridgeResponse({
    status: 'actionNotPreviewable',
    reason: 'cachedActionInvalid',
  }), {
    status: 'actionNotPreviewable',
    reason: 'cachedActionInvalid',
  });
  assert.throws(() => parseCodeActionPreviewBridgeResponse({
    status: 'actionNotPreviewable',
    reason: 'providerSpecificReason',
  }));
});
