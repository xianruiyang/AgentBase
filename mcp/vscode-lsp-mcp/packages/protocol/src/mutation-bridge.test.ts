import assert from 'node:assert/strict';
import test from 'node:test';
import {
  APPLY_ATTEMPTS_PER_WORKSPACE,
  APPLY_ATTEMPT_TTL_MS,
  MUTATION_APPLY_BRIDGE_METHOD,
  parseMutationApplyBridgeRequest,
  parseMutationApplyBridgeResponse,
} from './mutation-bridge.js';

const request = () => ({
  workspace: { workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA', generation: 1 },
  applyAttemptId: 'ap_AAAAAAAAAAAAAAAAAAAAAA',
  normalizedEdit: {
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
  },
});

test('mutation bridge request parser owns the complete closed normalized DTO', () => {
  assert.equal(MUTATION_APPLY_BRIDGE_METHOD, 'mutation.apply');
  assert.equal(APPLY_ATTEMPT_TTL_MS, 600_000);
  assert.equal(APPLY_ATTEMPTS_PER_WORKSPACE, 256);
  const input = request();
  const parsed = parseMutationApplyBridgeRequest(input);
  input.normalizedEdit.textChanges[0]!.edits[0]!.newText = 'tampered';
  assert.equal(parsed.normalizedEdit.textChanges[0]?.edits[0]?.newText, 'new');
  assert.equal(Object.isFrozen(parsed.normalizedEdit.targets[0]), true);
});

test('mutation bridge request rejects unknown fields, malformed identities, and misaligned targets', () => {
  assert.throws(() => parseMutationApplyBridgeRequest({ ...request(), extra: true }), TypeError);
  assert.throws(() => parseMutationApplyBridgeRequest({
    ...request(),
    applyAttemptId: 'predictable',
  }), TypeError);
  const misaligned = request();
  misaligned.normalizedEdit.targets[0]!.file = 'src/other.ts';
  assert.throws(() => parseMutationApplyBridgeRequest(misaligned), TypeError);
  const leaked = request();
  Object.assign(leaked.normalizedEdit.targets[0]!, { physicalPath: 'D:\\outside.ts' });
  assert.throws(() => parseMutationApplyBridgeRequest(leaked), TypeError);
});

test('mutation bridge response parser preserves terminal states and bounded logical files', () => {
  assert.deepEqual(parseMutationApplyBridgeResponse({
    status: 'applied',
    changedFiles: ['src/a.ts'],
  }), { status: 'applied', changedFiles: ['src/a.ts'] });
  assert.deepEqual(parseMutationApplyBridgeResponse({
    status: 'documentChanged',
    reason: 'content',
    files: ['src/a.ts'],
    additionalFiles: 2,
  }), {
    status: 'documentChanged',
    reason: 'content',
    files: ['src/a.ts'],
    additionalFiles: 2,
  });
  assert.deepEqual(parseMutationApplyBridgeResponse({
    status: 'applyFailed',
    stage: 'readback',
    outcome: 'postconditionFailed',
  }), {
    status: 'applyFailed',
    stage: 'readback',
    outcome: 'postconditionFailed',
  });
});

test('mutation bridge response rejects leaks, duplicates, and invalid terminal combinations', () => {
  assert.throws(() => parseMutationApplyBridgeResponse({
    status: 'applied',
    changedFiles: ['src/a.ts', 'src/a.ts'],
  }), TypeError);
  assert.throws(() => parseMutationApplyBridgeResponse({
    status: 'documentChanged',
    reason: 'content',
    files: Array.from({ length: 101 }, (_, index) => `src/${index}.ts`),
  }), TypeError);
  assert.throws(() => parseMutationApplyBridgeResponse({
    status: 'applyFailed',
    stage: 'readback',
    outcome: 'unknown',
  }), TypeError);
  assert.throws(() => parseMutationApplyBridgeResponse({
    status: 'pathOutsideWorkspace',
    internalUri: 'file:///outside.ts',
  }), TypeError);
});
