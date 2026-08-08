import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import type { RuntimePrimitives } from './runtime.js';
import {
  TextEditInvariantError,
  publicTextChangesFromNormalized,
  sha256Utf16Text,
  simulateNormalizedTextEdits,
  sortAndValidateNormalizedTextEdits,
  type NormalizedTextEdit,
  type NormalizedWorkspaceEdit,
} from './mutation.js';

const range = (startColumn: number, endColumn: number) => ({
  startLine: 1,
  startColumn,
  endLine: 1,
  endColumn,
});

const edit = (
  startOffset: number,
  endOffset: number,
  oldText: string,
  newText: string,
  providerOrdinal: number,
): NormalizedTextEdit => ({
  range: range(startOffset + 1, endOffset + 1),
  startOffset,
  endOffset,
  oldText,
  newText,
  providerOrdinal,
});

test('text edit simulation preserves provider order for same-point inserts and UTF-16 text', () => {
  const text = 'A😀e\u0301\r\nnext';
  const edits = [
    edit(7, 7, '', 'first-', 2),
    edit(1, 3, '😀', 'X', 1),
    edit(7, 7, '', 'second-', 3),
  ];
  assert.equal(simulateNormalizedTextEdits(text, edits), 'AXe\u0301\r\nfirst-second-next');
  assert.deepEqual(
    sortAndValidateNormalizedTextEdits(text, edits).map((candidate) => candidate.providerOrdinal),
    [1, 2, 3],
  );
});

test('text edit conflicts reject overlaps and interior inserts but allow boundaries and adjacency', () => {
  assert.throws(
    () => sortAndValidateNormalizedTextEdits('abcdef', [
      edit(1, 4, 'bcd', 'x', 0),
      edit(2, 2, '', 'inside', 1),
    ]),
    (error: unknown) => error instanceof TextEditInvariantError && error.reason === 'overlappingEdits',
  );
  assert.throws(
    () => sortAndValidateNormalizedTextEdits('abcdef', [
      edit(1, 4, 'bcd', 'x', 0),
      edit(1, 4, 'bcd', 'y', 1),
    ]),
    (error: unknown) => error instanceof TextEditInvariantError && error.reason === 'overlappingEdits',
  );
  assert.deepEqual(
    sortAndValidateNormalizedTextEdits('abcdef', [
      edit(1, 3, 'bc', 'x', 0),
      edit(1, 1, '', 'start', 1),
      edit(3, 3, '', 'end', 2),
      edit(3, 5, 'de', 'y', 3),
    ]).map((candidate) => candidate.providerOrdinal),
    [1, 0, 2, 3],
  );
});

test('oldText and offset invariants fail closed', () => {
  assert.throws(
    () => simulateNormalizedTextEdits('abc', [edit(0, 2, 'wrong', 'x', 0)]),
    (error: unknown) => error instanceof TextEditInvariantError && error.reason === 'oldTextMismatch',
  );
  assert.throws(
    () => simulateNormalizedTextEdits('abc', [edit(0, 4, 'abc', 'x', 0)]),
    (error: unknown) => error instanceof TextEditInvariantError && error.reason === 'invalidRange',
  );
});

test('memory hashes cover exact UTF-16 code units including unpaired surrogates', () => {
  const primitives: RuntimePrimitives = {
    monotonicNowMs: () => 0,
    secureRandomBytes: (length) => new Uint8Array(length),
    sha256Hex: (input) => createHash('sha256').update(input).digest('hex'),
  };
  assert.notEqual(sha256Utf16Text('\ud800', primitives), sha256Utf16Text('\udfff', primitives));
  assert.equal(sha256Utf16Text('😀', primitives).length, 64);
});

test('public projection rebuilds only reviewable text fields and excludes snapshots', () => {
  const normalized: NormalizedWorkspaceEdit = {
    textChanges: [{
      kind: 'text',
      file: 'src/a.ts',
      edits: [edit(0, 0, '', 'x', 9)],
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
  };
  const projected = publicTextChangesFromNormalized(normalized);
  assert.deepEqual(projected, [{
    kind: 'text',
    file: 'src/a.ts',
    edits: [{ range: range(1, 1), oldText: '', newText: 'x' }],
  }]);
  const serialized = JSON.stringify(projected);
  for (const forbidden of [
    'targets', 'internalUri', 'Sha256', 'providerOrdinal', 'startOffset', 'documentVersion',
  ]) {
    assert.equal(serialized.includes(forbidden), false);
  }
});
