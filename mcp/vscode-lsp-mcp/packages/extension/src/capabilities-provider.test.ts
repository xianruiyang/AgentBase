import assert from 'node:assert/strict';
import test from 'node:test';
import type { TextDocument } from 'vscode';
import {
  CAPABILITIES_BRIDGE_METHOD,
  IPC_PROTOCOL_VERSION,
  parseCapabilitiesBridgeResponse,
  type IpcRequest,
  type JsonObject,
  type RootAlias,
  type WorkspacePathAccess,
  type WorkspacePathContext,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  CapabilitiesProviderBridge,
  type CapabilitiesProviderHost,
} from './capabilities-provider.js';

const workspaceRoot = 'D:\\workspace\\app';
const sourceFile = `${workspaceRoot}\\src\\widget.ts`;

const context: WorkspacePathContext = {
  platform: 'win32',
  roots: [{
    alias: 'app' as RootAlias,
    name: 'App',
    folderIndex: 0,
    lexicalAbsolutePath: workspaceRoot,
    canonicalAbsolutePath: workspaceRoot,
    lexicalComparisonKey: workspaceRoot.toLowerCase(),
    canonicalComparisonKey: workspaceRoot.toLowerCase(),
  }],
};

const pathAccess: WorkspacePathAccess = {
  entryType: (value) => Promise.resolve(
    value.toLowerCase() === sourceFile.toLowerCase()
      ? 'file'
      : value.toLowerCase() === workspaceRoot.toLowerCase()
        ? 'directory'
        : 'missing',
  ),
  realpath: (value) => Promise.resolve(value),
};

const request = (params: JsonObject): IpcRequest => ({
  protocolVersion: IPC_PROTOCOL_VERSION,
  kind: 'request',
  id: 'req_AAAAAAAAAAAAAAAAAAAAAA',
  method: CAPABILITIES_BRIDGE_METHOD,
  deadlineAt: Date.now() + 10_000,
  params,
});

class FakeCapabilitiesHost implements CapabilitiesProviderHost {
  readonly calls: string[] = [];
  readonly events: string[] = [];
  readonly results = new Map<string, unknown>();
  readonly document = {
    uri: { scheme: 'file', fsPath: sourceFile },
    getText: () => 'export class Widget {}\n',
  } as unknown as TextDocument;
  diagnostics: readonly unknown[] = [];

  createPosition(line: number, character: number): unknown {
    return { line, character };
  }

  createRange(
    startLine: number,
    startCharacter: number,
    endLine: number,
    endCharacter: number,
  ): unknown {
    return { startLine, startCharacter, endLine, endCharacter };
  }

  executeCommand(command: string): PromiseLike<unknown> {
    this.calls.push(command);
    this.events.push(`command:${command}`);
    if (command === 'vscode.executeReferenceProvider') {
      return Promise.reject(new Error(`command '${command}' not found`));
    }
    if (command === 'vscode.executeImplementationProvider') {
      return new Promise<unknown>(() => undefined);
    }
    return Promise.resolve(this.results.get(command));
  }

  getDiagnostics(): unknown {
    return this.diagnostics;
  }

  openTextDocument(path: string): PromiseLike<TextDocument> {
    this.events.push(`open:${path}`);
    return Promise.resolve(this.document);
  }
}

test('file capability probes activate first and map only positive evidence to available', async () => {
  const host = new FakeCapabilitiesHost();
  host.results.set('vscode.executeDocumentSymbolProvider', [{ name: 'Widget' }]);
  host.results.set('vscode.executeDefinitionProvider', []);
  host.diagnostics = [{ message: 'fixture error' }];
  const bridge = new CapabilitiesProviderBridge(host, pathAccess, 100);
  const raw = await bridge.handle(context, request({
    file: 'src/widget.ts',
    capabilities: [
      'documentSymbols',
      'definition',
      'references',
      'implementation',
      'diagnostics',
      'commands',
    ],
  }), new AbortController().signal);

  assert.deepEqual(parseCapabilitiesBridgeResponse(raw), {
    status: 'completed',
    candidates: [
      { name: 'documentSymbols', status: 'available' },
      { name: 'definition', status: 'unknown', reason: 'probe_returned_no_evidence' },
      { name: 'references', status: 'unavailable', reason: 'provider_command_unavailable' },
      { name: 'implementation', status: 'timedOut', reason: 'provider_timed_out' },
      { name: 'diagnostics', status: 'available' },
      { name: 'commands', status: 'available' },
    ],
  });
  assert.equal(host.events[0], `open:${sourceFile}`);
  assert.equal(host.events.some((event) => event.startsWith('command:')), true);
});

test('workspace probes do not guess document capabilities without a file', async () => {
  const host = new FakeCapabilitiesHost();
  host.results.set('vscode.executeWorkspaceSymbolProvider', [{ name: 'Widget' }]);
  const bridge = new CapabilitiesProviderBridge(host, pathAccess, 5);
  const raw = await bridge.handle(context, request({
    capabilities: ['workspaceSymbols', 'documentSymbols', 'diagnostics', 'tasks'],
  }), new AbortController().signal);

  assert.deepEqual(parseCapabilitiesBridgeResponse(raw), {
    status: 'completed',
    candidates: [
      { name: 'workspaceSymbols', status: 'available' },
      { name: 'documentSymbols', status: 'unknown', reason: 'document_required' },
      { name: 'diagnostics', status: 'unknown', reason: 'document_required' },
      { name: 'tasks', status: 'available' },
    ],
  });
  assert.equal(host.events.some((event) => event.startsWith('open:')), false);
});

test('capability bridge fails closed for malformed probe parameters', async () => {
  const bridge = new CapabilitiesProviderBridge(new FakeCapabilitiesHost(), pathAccess, 5);
  assert.deepEqual(await bridge.handle(context, request({
    capabilities: ['definition', 'definition'],
  }), new AbortController().signal), { status: 'failed' });
});
