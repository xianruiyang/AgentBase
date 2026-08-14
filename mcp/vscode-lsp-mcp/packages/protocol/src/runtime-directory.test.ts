import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import {
  RuntimeSecurityError,
  createInstanceId,
  createIpcEndpoint,
  deriveRuntimeDirectoryRoot,
  type RuntimePrimitives,
} from './index.js';

const primitives: RuntimePrimitives = {
  monotonicNowMs: () => 0,
  secureRandomBytes: (length) => new Uint8Array(length).fill(7),
  sha256Hex: (input) => createHash('sha256').update(input).digest('hex'),
};

test('runtime directory derivation requires the secure Windows adapter', () => {
  assert.throws(
    () => deriveRuntimeDirectoryRoot({ platform: 'win32', environment: {} }),
    (error: unknown) => error instanceof RuntimeSecurityError &&
      error.reason === 'windowsAdapterUnavailable',
  );
  const derived = deriveRuntimeDirectoryRoot({
    platform: 'win32',
    environment: {},
    windowsSecurity: {
      ensureSecureRuntimeDirectory: () => ({
        path: 'C:\\runtime',
        currentUserSid: 'S-1-5-21-1',
        protectedDacl: true,
        reparsePoint: false,
      }),
      verifySecureRegistryFile: () => true,
    },
  });
  assert.equal(derived.root, 'C:\\runtime');
  assert.equal(derived.currentUserSid, 'S-1-5-21-1');
});

test('IPC endpoint is a collision-resistant Windows named pipe', () => {
  const instanceId = createInstanceId(primitives);
  const endpoint = createIpcEndpoint({
    platform: 'win32',
    root: 'C:\\runtime',
    registrations: 'C:\\runtime\\registrations',
    quarantine: 'C:\\runtime\\quarantine',
  }, instanceId, primitives, 'S-1-5-21-1');
  assert.equal(endpoint.kind, 'namedPipe');
  assert.match(endpoint.address, /^\\\\\.\\pipe\\vscode-lsp-mcp-[0-9a-f]{12}-[0-9a-f]{32}$/u);
});
