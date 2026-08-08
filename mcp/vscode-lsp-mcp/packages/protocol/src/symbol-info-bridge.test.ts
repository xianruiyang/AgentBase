import assert from 'node:assert/strict';
import test from 'node:test';
import { parseSymbolInfoBridgeResponse } from './symbol-info-bridge.js';

test('symbol info bridge parser preserves strict discriminated candidates', () => {
  assert.deepEqual(parseSymbolInfoBridgeResponse({
    status: 'completed',
    candidates: [
      { type: 'hover', text: 'Widget docs' },
      {
        type: 'definition',
        file: 'src/widget.ts',
        line: 2,
        column: 7,
        snippet: 'class Widget {}',
      },
      {
        type: 'signatureHelp',
        label: 'build(name: string)',
        activeSignature: true,
        activeParameter: 0,
        documentation: 'Builds a widget.',
        parameters: [{ label: 'name: string', documentation: 'Widget name.' }],
      },
    ],
    warnings: ['definition_candidate_invalid'],
  }), {
    status: 'completed',
    candidates: [
      { type: 'hover', text: 'Widget docs' },
      {
        type: 'definition',
        file: 'src/widget.ts',
        line: 2,
        column: 7,
        snippet: 'class Widget {}',
      },
      {
        type: 'signatureHelp',
        label: 'build(name: string)',
        activeSignature: true,
        activeParameter: 0,
        documentation: 'Builds a widget.',
        parameters: [{ label: 'name: string', documentation: 'Widget name.' }],
      },
    ],
    warnings: ['definition_candidate_invalid'],
  });
});

test('symbol info bridge parser accepts terminal states and rejects mixed or unsafe shapes', () => {
  assert.deepEqual(parseSymbolInfoBridgeResponse({ status: 'positionOutOfRange' }), {
    status: 'positionOutOfRange',
  });
  assert.throws(() => parseSymbolInfoBridgeResponse({
    status: 'completed',
    candidates: [{ type: 'hover', text: 'docs', file: 'src/widget.ts' }],
  }));
  assert.throws(() => parseSymbolInfoBridgeResponse({
    status: 'completed',
    candidates: [{ type: 'definition', file: '../secret.ts', line: 1, column: 1 }],
  }));
  assert.throws(() => parseSymbolInfoBridgeResponse({
    status: 'completed',
    candidates: [{ type: 'signatureHelp', label: 'build()', activeSignature: 0 }],
  }));
});
