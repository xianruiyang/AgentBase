import assert from 'node:assert/strict';
import test from 'node:test';
import {
  parseDocumentSymbolBridgeResponse,
  parseWorkspaceSymbolBridgeResponse,
} from './symbol-bridge.js';

test('workspace symbol bridge responses are strict, logical, and frozen', () => {
  const parsed = parseWorkspaceSymbolBridgeResponse({
    status: 'completed',
    candidates: [{
      name: 'Widget',
      kind: 'class',
      file: 'src/widget.ts',
      line: 2,
      column: 3,
      container: 'App',
      snippet: 'class Widget {}',
    }],
    warnings: ['provider_candidate_invalid'],
    provider: { status: 'completed', elapsedMs: 12, attempts: 1 },
  });
  assert.equal(parsed.status, 'completed');
  if (parsed.status === 'completed') {
    assert.equal(parsed.candidates[0]?.file, 'src/widget.ts');
    assert.equal(Object.isFrozen(parsed), true);
    assert.equal(Object.isFrozen(parsed.candidates), true);
    assert.deepEqual(parsed.provider, { status: 'completed', elapsedMs: 12, attempts: 1 });
  }

  assert.throws(() => parseWorkspaceSymbolBridgeResponse({
    status: 'completed',
    candidates: [{ name: 'Widget', kind: 'class', file: 'D:/private.ts', line: 1, column: 1 }],
  }), /logical path/u);
  assert.throws(() => parseWorkspaceSymbolBridgeResponse({
    status: 'completed',
    candidates: [],
    extra: true,
  }), /unknown field/u);
});

test('document symbol bridge preserves complete paths and rejects malformed coordinates', () => {
  const parsed = parseDocumentSymbolBridgeResponse({
    status: 'completed',
    candidates: [{
      kind: 'method',
      path: ['Widget', 'run'],
      line: 4,
      column: 5,
      range: { startLine: 4, startColumn: 1, endLine: 8, endColumn: 2 },
    }],
  });
  assert.equal(parsed.status, 'completed');
  if (parsed.status === 'completed') {
    assert.deepEqual(parsed.candidates[0]?.path, ['Widget', 'run']);
    assert.deepEqual(parsed.candidates[0]?.range, {
      startLine: 4,
      startColumn: 1,
      endLine: 8,
      endColumn: 2,
    });
  }
  assert.throws(() => parseDocumentSymbolBridgeResponse({
    status: 'completed',
    candidates: [{ kind: 'method', path: [], line: 1, column: 1 }],
  }), /non-empty array/u);
  assert.throws(() => parseDocumentSymbolBridgeResponse({
    status: 'completed',
    candidates: [{ kind: 'method', path: ['run'], line: 0, column: 1 }],
  }), /positive safe integer/u);
});

test('symbol bridge terminal statuses contain no provider internals', () => {
  for (const status of ['unavailable', 'notReady', 'cancelled', 'timedOut', 'failed'] as const) {
    assert.deepEqual(parseWorkspaceSymbolBridgeResponse({ status }), { status });
  }
  assert.throws(
    () => parseWorkspaceSymbolBridgeResponse({ status: 'failed', command: 'private.command' }),
    /unknown field/u,
  );
  assert.deepEqual(parseWorkspaceSymbolBridgeResponse({
    status: 'timedOut',
    provider: { status: 'timedOut', elapsedMs: 90_000, attempts: 2 },
  }), {
    status: 'timedOut',
    provider: { status: 'timedOut', elapsedMs: 90_000, attempts: 2 },
  });
  assert.throws(() => parseWorkspaceSymbolBridgeResponse({
    status: 'failed',
    provider: { status: 'completed', elapsedMs: 1, attempts: 1 },
  }), /status must match/u);
});
