import assert from 'node:assert/strict';
import test from 'node:test';
import {
  MUTATION_RENAME_PREVIEW_BRIDGE_METHOD,
  parseRenamePreviewBridgeRequest,
  parseRenamePreviewBridgeResponse,
} from './rename-bridge.js';

const workspace = { workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA', generation: 4 };

const normalizedEdit = () => ({
  textChanges: [{
    kind: 'text',
    file: 'src/a.ts',
    edits: [{
      range: { startLine: 1, startColumn: 1, endLine: 1, endColumn: 4 },
      oldText: 'old',
      newText: 'new',
      startOffset: 0,
      endOffset: 3,
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

test('rename bridge owns a closed exact-generation request', () => {
  assert.equal(MUTATION_RENAME_PREVIEW_BRIDGE_METHOD, 'mutation.renamePreview');
  assert.deepEqual(parseRenamePreviewBridgeRequest({
    workspace,
    file: 'src/a.ts',
    line: 1,
    column: 2,
    newName: 'next',
    includeGlobs: ['src/**'],
    timeoutMs: 90_000,
  }), {
    workspace,
    file: 'src/a.ts',
    line: 1,
    column: 2,
    newName: 'next',
    includeGlobs: ['src/**'],
    timeoutMs: 90_000,
  });
  assert.throws(() => parseRenamePreviewBridgeRequest({
    workspace,
    file: 'src/a.ts',
    line: 1,
    column: 2,
    newName: 'next',
    includeGlobs: ['src/**'],
    internalUri: 'file:///outside.ts',
  }), TypeError);
  assert.throws(() => parseRenamePreviewBridgeRequest({
    workspace: { ...workspace, generation: 0 },
    file: 'src/a.ts',
    line: 1,
    column: 2,
    newName: 'next',
    includeGlobs: ['src/**'],
  }), TypeError);
  assert.throws(() => parseRenamePreviewBridgeRequest({
    workspace,
    file: 'src/a.ts',
    line: 1,
    column: 2,
    newName: 'next',
  }), TypeError);
  assert.throws(() => parseRenamePreviewBridgeRequest({
    workspace,
    file: 'src/a.ts',
    line: 1,
    column: 2,
    newName: 'next',
    includeGlobs: ['src/**'],
    timeoutMs: 90_001,
  }), TypeError);
});

test('rename bridge accepts complete and empty normalized previews without leaking private variants', () => {
  const parsed = parseRenamePreviewBridgeResponse({
    status: 'completed',
    normalizedEdit: normalizedEdit(),
  });
  assert.equal(parsed.status, 'completed');
  if (parsed.status === 'completed') {
    assert.equal(parsed.normalizedEdit.textChanges[0]?.edits[0]?.newText, 'new');
    assert.equal(Object.isFrozen(parsed.normalizedEdit.targets[0]), true);
  }
  assert.deepEqual(parseRenamePreviewBridgeResponse({
    status: 'completed',
    normalizedEdit: { textChanges: [], targets: [] },
  }), {
    status: 'completed',
    normalizedEdit: { textChanges: [], targets: [] },
  });
  assert.throws(() => parseRenamePreviewBridgeResponse({
    status: 'completed',
    normalizedEdit: { textChanges: [], targets: [], providerEdit: {} },
  }), TypeError);
});

test('rename bridge preserves actionable prepare and mutation failures as closed states', () => {
  assert.deepEqual(parseRenamePreviewBridgeResponse({
    status: 'scopeRejected',
    files: ['outside/a.ts'],
    additionalFiles: 2,
    totalFiles: 5,
  }), {
    status: 'scopeRejected',
    files: ['outside/a.ts'],
    additionalFiles: 2,
    totalFiles: 5,
  });
  assert.deepEqual(parseRenamePreviewBridgeResponse({
    status: 'prepareRejected',
    reason: 'notRenameable',
  }), { status: 'prepareRejected', reason: 'notRenameable' });
  assert.deepEqual(parseRenamePreviewBridgeResponse({
    status: 'documentChanged',
    reason: 'version',
    files: ['src/a.ts'],
  }), { status: 'documentChanged', reason: 'version', files: ['src/a.ts'] });
  assert.deepEqual(parseRenamePreviewBridgeResponse({
    status: 'editConflict',
    reason: 'unsupportedEdit',
  }), { status: 'editConflict', reason: 'unsupportedEdit' });
  assert.deepEqual(parseRenamePreviewBridgeResponse({ status: 'noEdits' }), {
    status: 'noEdits',
  });
  assert.deepEqual(parseRenamePreviewBridgeResponse({
    status: 'identityRejected',
    reason: 'mismatchedSymbol',
    checkedEdits: 2,
    totalEdits: 5,
    files: ['src/other.ts'],
  }), {
    status: 'identityRejected',
    reason: 'mismatchedSymbol',
    checkedEdits: 2,
    totalEdits: 5,
    files: ['src/other.ts'],
  });
  assert.deepEqual(parseRenamePreviewBridgeResponse({
    status: 'identityRejected',
    reason: 'providerTimedOut',
    checkedEdits: 1,
    totalEdits: 2,
    files: ['src/b.ts'],
  }), {
    status: 'identityRejected',
    reason: 'providerTimedOut',
    checkedEdits: 1,
    totalEdits: 2,
    files: ['src/b.ts'],
  });
  assert.throws(() => parseRenamePreviewBridgeResponse({
    status: 'identityRejected',
    reason: 'mismatchedSymbol',
    checkedEdits: 6,
    totalEdits: 5,
  }), TypeError);
  assert.throws(() => parseRenamePreviewBridgeResponse({
    status: 'prepareRejected',
    reason: 'provider_message',
  }), TypeError);
  assert.throws(() => parseRenamePreviewBridgeResponse({
    status: 'pathOutsideWorkspace',
    file: 'D:\\outside.ts',
  }), TypeError);
});
