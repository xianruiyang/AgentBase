import type { ExtensionContext } from 'vscode';
import {
  PROTOCOL_PACKAGE_NAME,
  type WorkspaceMutationGate,
} from '@simplechat/vscode-lsp-mcp-protocol';
export * from './ipc-host.js';
export * from './extension-lifecycle.js';
export * from './provider-runtime.js';
export * from './capabilities-provider.js';
export * from './hierarchy-provider.js';
export * from './symbols-provider.js';
export * from './symbol-info-provider.js';
export * from './references-diagnostics-provider.js';
export * from './workspace-edit-normalizer.js';
export * from './mutation-gate.js';
export * from './mutation-apply-provider.js';
export * from './rename-preview-provider.js';
export * from './code-action-provider.js';
export * from './format-preview-provider.js';
export * from './command-policy-provider.js';
export * from './task-discovery.js';
export * from './task-jsonc.js';
export * from './command-arguments.js';
export * from './command-execution.js';
export * from './command-execution-provider.js';
import {
  createSystemExtensionRegistrationService,
  type ExtensionRegistrationService,
} from './extension-lifecycle.js';

export const EXTENSION_ID = 'simplechat.vscode-lsp-mcp-companion';

export interface ExtensionServiceBoundaries {
  readonly mutationGate: WorkspaceMutationGate;
}

export interface ExtensionDescriptor {
  readonly extensionId: typeof EXTENSION_ID;
  readonly protocolPackage: typeof PROTOCOL_PACKAGE_NAME;
  readonly registersUserInterface: false;
}

export function getExtensionDescriptor(): ExtensionDescriptor {
  return Object.freeze({
    extensionId: EXTENSION_ID,
    protocolPackage: PROTOCOL_PACKAGE_NAME,
    registersUserInterface: false,
  });
}

let activeService: ExtensionRegistrationService | undefined;

export async function activate(context: ExtensionContext): Promise<ExtensionDescriptor> {
  const vscode = await import('vscode');
  const service = await createSystemExtensionRegistrationService(vscode);
  await service.start();
  activeService = service;
  const rootsSubscription = vscode.workspace.onDidChangeWorkspaceFolders(() => {
    void service.refresh().catch(() => undefined);
  });
  context.subscriptions.push(rootsSubscription, {
    dispose: () => {
      void service.stop();
    },
  });
  return getExtensionDescriptor();
}

export async function deactivate(): Promise<void> {
  const service = activeService;
  activeService = undefined;
  await service?.stop();
}
