import assert from 'node:assert/strict';
import test from 'node:test';
import { getServerDescriptor } from './index.js';

test('server skeleton reserves stdio for protocol messages', () => {
  assert.deepEqual(getServerDescriptor(), {
    packageName: '@simplechat/vscode-lsp-mcp-server',
    protocolPackage: '@simplechat/vscode-lsp-mcp-protocol',
    transport: 'stdio',
    emitsProtocolOnlyOnStdout: true,
  });
});

