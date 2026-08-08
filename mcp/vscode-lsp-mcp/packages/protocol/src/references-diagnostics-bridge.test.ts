import assert from 'node:assert/strict';
import test from 'node:test';
import {
  parseDiagnosticsBridgeResponse,
  parseReferencesBridgeResponse,
} from './references-diagnostics-bridge.js';

test('references bridge parser accepts logical 1-based hits and strict terminal states', () => {
  assert.deepEqual(parseReferencesBridgeResponse({
    status: 'completed',
    candidates: [{ file: 'src/widget.ts', line: 2, column: 7, snippet: 'new Widget()' }],
    available: 3,
    warnings: ['reference_candidate_invalid'],
  }), {
    status: 'completed',
    candidates: [{ file: 'src/widget.ts', line: 2, column: 7, snippet: 'new Widget()' }],
    available: 3,
    warnings: ['reference_candidate_invalid'],
  });
  assert.deepEqual(parseReferencesBridgeResponse({ status: 'positionOutOfRange' }), {
    status: 'positionOutOfRange',
  });
  assert.throws(() => parseReferencesBridgeResponse({
    status: 'completed',
    candidates: [{ file: '../secret.ts', line: 1, column: 1 }],
  }));
  assert.throws(() => parseReferencesBridgeResponse({
    status: 'completed',
    candidates: [{ file: 'src/widget.ts', line: 1, column: 1 }],
    available: 0,
  }));
});

test('diagnostics bridge parser preserves complete ranges and optional public fields', () => {
  const value = {
    status: 'completed',
    candidates: [{
      file: 'src/widget.ts',
      range: { startLine: 2, startColumn: 3, endLine: 2, endColumn: 9 },
      severity: 'warning',
      message: 'Deprecated widget.',
      code: 6385,
      source: 'typescript',
      tags: ['deprecated'],
      relatedInformation: [{
        file: 'src/base.ts',
        range: { startLine: 1, startColumn: 1, endLine: 1, endColumn: 5 },
        message: 'Declared here.',
      }],
    }],
  };
  assert.deepEqual(parseDiagnosticsBridgeResponse(value), value);
});

test('diagnostics bridge parser rejects unsafe ranges, mixed fields, and reference-only status', () => {
  assert.throws(() => parseDiagnosticsBridgeResponse({ status: 'positionOutOfRange' }));
  assert.throws(() => parseDiagnosticsBridgeResponse({
    status: 'completed',
    candidates: [{
      file: 'src/widget.ts',
      range: { startLine: 2, startColumn: 3, endLine: 1, endColumn: 1 },
      severity: 'error',
      message: 'Broken.',
    }],
  }));
  assert.throws(() => parseDiagnosticsBridgeResponse({
    status: 'completed',
    candidates: [{
      file: 'src/widget.ts',
      range: { startLine: 1, startColumn: 1, endLine: 1, endColumn: 2 },
      severity: 'error',
      message: 'Broken.',
      uri: 'file:///private/widget.ts',
    }],
  }));
});
