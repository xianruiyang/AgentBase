import { PROTOCOL_PACKAGE_NAME } from '@simplechat/vscode-lsp-mcp-protocol';
export * from './bridge-client.js';
export * from './command-policy.js';
export * from './command-service.js';
export * from './mcp-server.js';
export * from './mutation-cache.js';
export * from './mutation-apply-service.js';
export * from './rename-service.js';
export * from './workspace-router.js';

export const SERVER_PACKAGE_NAME = '@simplechat/vscode-lsp-mcp-server';

export interface ServerDescriptor {
  readonly packageName: typeof SERVER_PACKAGE_NAME;
  readonly protocolPackage: typeof PROTOCOL_PACKAGE_NAME;
  readonly transport: 'stdio';
  readonly emitsProtocolOnlyOnStdout: true;
}

export function getServerDescriptor(): ServerDescriptor {
  return Object.freeze({
    packageName: SERVER_PACKAGE_NAME,
    protocolPackage: PROTOCOL_PACKAGE_NAME,
    transport: 'stdio',
    emitsProtocolOnlyOnStdout: true,
  });
}
