import assert from 'node:assert/strict';
import test from 'node:test';
import {
  PROTOCOL_PACKAGE_NAME,
  createWorkspaceId,
  systemRuntimePrimitives,
  type WorkspaceRouteIdentity,
} from './index.js';

test('protocol skeleton exposes deterministic runtime boundaries', () => {
  const route: WorkspaceRouteIdentity = {
    workspaceId: createWorkspaceId(systemRuntimePrimitives),
    generation: 1,
  };

  assert.equal(PROTOCOL_PACKAGE_NAME, '@simplechat/vscode-lsp-mcp-protocol');
  assert.equal(route.generation, 1);
  assert.equal(
    systemRuntimePrimitives.sha256Hex(Buffer.from('abc')),
    'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
  );
  assert.equal(systemRuntimePrimitives.secureRandomBytes(16).byteLength, 16);
  assert.ok(systemRuntimePrimitives.monotonicNowMs() >= 0);
});

test('secure random boundary rejects unsafe lengths', () => {
  assert.throws(() => systemRuntimePrimitives.secureRandomBytes(0), RangeError);
  assert.throws(() => systemRuntimePrimitives.secureRandomBytes(65_537), RangeError);
});
