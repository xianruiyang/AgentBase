import assert from 'node:assert/strict';
import test from 'node:test';
import {
  EXTENSION_ID,
  getExtensionDescriptor,
} from './extension.js';
import {
  ExtensionTransportHostError,
  createExtensionTransportServer,
} from './ipc-host.js';
import type { RawByteConnection, RawByteServer } from '@simplechat/vscode-lsp-mcp-protocol';

test('extension skeleton has an independent non-UI identity', () => {
  assert.deepEqual(getExtensionDescriptor(), {
    extensionId: EXTENSION_ID,
    protocolPackage: '@simplechat/vscode-lsp-mcp-protocol',
    registersUserInterface: false,
  });
});

const fakeServer: RawByteServer = {
  accept: (): Promise<RawByteConnection> => Promise.reject(new Error('not used')),
  close: (): Promise<void> => Promise.resolve(),
};

test('Windows transport requires the secure native factory and caps sessions at four', async () => {
  let options: { readonly name: string; readonly maxInstances: number } | undefined;
  const secureServer = { ...fakeServer, inspectSecurity: () => ({
    protectedDacl: true as const, ownerCurrentUser: true as const, currentUserFullControl: true as const,
    systemFullControl: true as const, otherUsersDenied: true as const, remoteClientsRejected: true as const,
    byteMode: true as const, firstInstance: true as const, maxInstances: 4,
  }) };
  const server = await createExtensionTransportServer({
    platform: 'win32',
    endpoint: { kind: 'namedPipe', address: '\\\\.\\pipe\\vscode-lsp-mcp-test' },
    windowsFactory: {
      create: (received) => {
        options = received;
        return secureServer;
      },
    },
  });
  assert.equal(server, secureServer);
  assert.deepEqual(options, { name: '\\\\.\\pipe\\vscode-lsp-mcp-test', maxInstances: 4 });
});

test('Windows has no Node pipe fallback when the secure adapter is unavailable', async () => {
  await assert.rejects(createExtensionTransportServer({
    platform: 'win32',
    endpoint: { kind: 'namedPipe', address: '\\\\.\\pipe\\vscode-lsp-mcp-test' },
    windowsFactory: null,
  }), (error: unknown) =>
    error instanceof ExtensionTransportHostError && error.reason === 'secureAdapterUnavailable');
  await assert.rejects(createExtensionTransportServer({
    platform: 'win32', endpoint: { kind: 'unix', address: '/tmp/test.sock' },
  }), (error: unknown) =>
    error instanceof ExtensionTransportHostError && error.reason === 'endpointMismatch');
});

test('Unix transport validates endpoint kind and forwards owner uid', async () => {
  let received: readonly [string, number] | undefined;
  const server = await createExtensionTransportServer({
    platform: 'linux', endpoint: { kind: 'unix', address: '/tmp/vlm/test.sock' }, unixUid: 42,
    unixFactory: (address, uid) => {
      received = [address, uid];
      return Promise.resolve(fakeServer);
    },
  });
  assert.equal(server, fakeServer);
  assert.deepEqual(received, ['/tmp/vlm/test.sock', 42]);
});
