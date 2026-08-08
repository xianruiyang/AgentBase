import assert from 'node:assert/strict';
import test from 'node:test';
import {
  parseHierarchyExpandBridgeResponse,
  parseHierarchyPrepareBridgeResponse,
  parseHierarchyReleaseBridgeResponse,
} from './hierarchy-bridge.js';

const symbol = {
  name: 'middleCall',
  kind: 'function',
  file: 'app/src/hierarchy.ts',
  line: 4,
  column: 17,
} as const;

test('hierarchy bridge parsers preserve strict logical nodes and terminal states', () => {
  assert.deepEqual(parseHierarchyPrepareBridgeResponse({
    status: 'completed',
    traversalId: 'h1',
    nodes: [{ nodeId: 'n1', symbol }],
    warnings: ['provider_candidate_invalid'],
  }), {
    status: 'completed',
    traversalId: 'h1',
    nodes: [{ nodeId: 'n1', symbol }],
    warnings: ['provider_candidate_invalid'],
  });
  assert.deepEqual(parseHierarchyExpandBridgeResponse({
    status: 'completed',
    nodes: [{
      nodeId: 'n2',
      symbol: { ...symbol, name: 'leafCall', line: 1 },
      callSites: [{ startLine: 5, startColumn: 10, endLine: 5, endColumn: 18 }],
    }],
  }).status, 'completed');
  assert.deepEqual(parseHierarchyPrepareBridgeResponse({ status: 'positionOutOfRange' }), {
    status: 'positionOutOfRange',
  });
  assert.deepEqual(parseHierarchyExpandBridgeResponse({ status: 'timedOut' }), {
    status: 'timedOut',
  });
  assert.deepEqual(parseHierarchyReleaseBridgeResponse({ status: 'completed' }), {
    status: 'completed',
  });
});

test('hierarchy bridge parsers reject leaks, malformed ranges, duplicate IDs, and mixed terminals', () => {
  assert.throws(() => parseHierarchyPrepareBridgeResponse({
    status: 'completed', traversalId: 'h1', nodes: [{ nodeId: 'n1', symbol, providerData: {} }],
  }));
  assert.throws(() => parseHierarchyPrepareBridgeResponse({
    status: 'completed', traversalId: 'h1', nodes: [
      { nodeId: 'n1', symbol },
      { nodeId: 'n1', symbol },
    ],
  }));
  assert.throws(() => parseHierarchyExpandBridgeResponse({
    status: 'completed',
    nodes: [{
      nodeId: 'n2',
      symbol,
      callSites: [{ startLine: 5, startColumn: 9, endLine: 5, endColumn: 8 }],
    }],
  }));
  assert.throws(() => parseHierarchyPrepareBridgeResponse({
    status: 'failed', traversalId: 'h1', nodes: [],
  }));
  assert.throws(() => parseHierarchyExpandBridgeResponse({ status: 'positionOutOfRange' }));
  assert.throws(() => parseHierarchyReleaseBridgeResponse({ status: 'completed', traversalId: 'h1' }));
});
