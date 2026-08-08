import assert from 'node:assert/strict';
import test from 'node:test';
import type { TextChange, TextEdit } from './dto.js';
import {
  applyResultWindow,
  buildCandidateCollection,
  compareTextOrdinal,
  contextSnippetForLine,
  isSupportedLogicalGlob,
  matchesLogicalGlobs,
} from './collection.js';

test('result windows use one-based inclusive bounds and preserve available', () => {
  const values = Array.from({ length: 120 }, (_, index) => index + 1);
  assert.deepEqual(applyResultWindow(values).results, Array.from({ length: 20 }, (_, index) => index + 1));
  assert.deepEqual(
    applyResultWindow(values, { resultStart: 101 }).results,
    Array.from({ length: 20 }, (_, index) => index + 101),
  );
  assert.deepEqual(applyResultWindow(values, { resultEnd: 3 }).results, [1, 2, 3]);
  assert.equal(applyResultWindow(values, { resultStart: 1, resultEnd: 100 }).results.length, 100);

  const beyond = applyResultWindow(values, { resultStart: 121, resultEnd: 121 });
  assert.deepEqual(beyond.results, []);
  assert.equal(beyond.available, 120);
  assert.deepEqual(applyResultWindow([], { resultStart: 1, resultEnd: 1 }), {
    results: [],
    available: 0,
  });
});

test('result windows reject reversed, oversized, and unsafe bounds', () => {
  assert.throws(
    () => applyResultWindow([1], { resultStart: 2, resultEnd: 1 }),
    /must not precede/u,
  );
  assert.throws(
    () => applyResultWindow([1], { resultStart: 1, resultEnd: 101 }),
    /at most 100/u,
  );
  assert.throws(() => applyResultWindow([1], { resultStart: 0 }), /positive safe integers/u);
  assert.throws(
    () => applyResultWindow([1], { resultStart: Number.MAX_SAFE_INTEGER + 1 }),
    /positive safe integers/u,
  );
});

test('candidate pipeline filters globs, deduplicates, stably sorts, then slices', () => {
  const sources = [
    { id: 'duplicate', file: 'src/zeta.ts', rank: 1 },
    { id: 'beta', file: 'src/beta.ts', rank: 1 },
    { id: 'duplicate', file: 'src/zeta.ts', rank: 0 },
    { id: 'test', file: 'src/beta.test.ts', rank: 1 },
    { id: 'readme', file: 'README.md', rank: 1 },
    { id: 'dropped', file: 'src/drop.ts', rank: 1 },
  ] as const;
  const collection = buildCandidateCollection(sources, {
    normalize: (source) => source.id === 'dropped' ? undefined : source,
    filter: (candidate) => candidate.rank >= 1,
    logicalPath: (candidate) => candidate.file,
    includeGlobs: ['**/*.ts'],
    excludeGlobs: ['**/*.test.ts'],
    dedupeKey: (candidate) => candidate.id,
    compare: (left, right) => left.rank - right.rank,
    resultStart: 2,
    resultEnd: 2,
    warnings: ['provider_partial'],
  });

  assert.equal(collection.available, 2);
  assert.deepEqual(collection.results.map(({ id }) => id), ['beta']);
  assert.deepEqual(collection.warnings, ['provider_partial']);
  assert.equal(Object.isFrozen(collection), true);
  assert.equal(Object.isFrozen(collection.results), true);
});

test('candidate sort is deterministic and stable for equal comparator values', () => {
  const collection = buildCandidateCollection(['zeta', 'alpha', 'beta'], {
    normalize: (source) => ({ source, rank: 1 }),
    dedupeKey: ({ source }) => source,
    compare: (left, right) => left.rank - right.rank,
  });
  assert.deepEqual(collection.results.map(({ source }) => source), ['zeta', 'alpha', 'beta']);
  assert.equal(compareTextOrdinal('alpha', 'beta'), -1);
  assert.equal(compareTextOrdinal('beta', 'beta'), 0);
});

test('logical globs use slash paths, root-aware globstars, classes, and exclude precedence', () => {
  assert.equal(matchesLogicalGlobs('main.ts', { includeGlobs: ['**/*.ts'] }), true);
  assert.equal(matchesLogicalGlobs('src/main.ts', { includeGlobs: ['**/*.ts'] }), true);
  assert.equal(matchesLogicalGlobs('src/main.js', { includeGlobs: ['src/?ain.[tj]s'] }), true);
  assert.equal(matchesLogicalGlobs('src/main.ts', {
    includeGlobs: ['src/**'],
    excludeGlobs: ['**/*.ts'],
  }), false);
  assert.equal(matchesLogicalGlobs('docs/readme.md', { excludeGlobs: ['src/**'] }), true);
  assert.throws(() => matchesLogicalGlobs('src\\main.ts', {}), /forward slashes/u);
  assert.throws(
    () => buildCandidateCollection(['src/main.ts'], {
      normalize: (source) => source,
      includeGlobs: ['**/*.ts'],
      dedupeKey: (source) => source,
    }),
    /logicalPath selector/u,
  );
});

test('glob validation and matching share the same supported syntax', () => {
  for (const pattern of ['**/*.ts', 'src/?ain.[tj]s', 'src/[a-z].ts']) {
    assert.equal(isSupportedLogicalGlob(pattern), true, pattern);
  }
  for (const pattern of ['', 'src\\*.ts', 'src/***/x.ts', 'src/[].ts', 'src/[z-a].ts']) {
    assert.equal(isSupportedLogicalGlob(pattern), false, pattern);
  }
});

test('context snippets normalize newlines and clamp around document edges', () => {
  const text = 'one\r\ntwo\rthree\nfour';
  assert.equal(contextSnippetForLine(text, 1, 1), 'one\ntwo');
  assert.equal(contextSnippetForLine(text, 3, 1), 'two\nthree\nfour');
  assert.equal(contextSnippetForLine(text, 4, 2), 'two\nthree\nfour');
  assert.equal(contextSnippetForLine(text, 2, 0), undefined);
  assert.throws(() => contextSnippetForLine(text, 5, 1), /line count/u);
  assert.throws(() => contextSnippetForLine(text, 1, 6), /0 through 5/u);
});

test('candidate windows never slice edits nested in an atomic operation result', () => {
  const edit = (line: number): TextEdit => ({
    range: {
      startLine: line,
      startColumn: 1,
      endLine: line,
      endColumn: 1,
    },
    oldText: '',
    newText: 'x',
  });
  const change: TextChange = {
    kind: 'text',
    file: 'src/main.ts',
    edits: Array.from({ length: 125 }, (_, index) => edit(index + 1)),
  };
  const collection = applyResultWindow([{ changes: [change] }], {
    resultStart: 1,
    resultEnd: 1,
  });

  assert.equal(collection.results.length, 1);
  assert.equal(collection.results[0]?.changes[0]?.edits.length, 125);
});
