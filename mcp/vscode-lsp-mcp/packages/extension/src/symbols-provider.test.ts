import assert from 'node:assert/strict';
import path from 'node:path';
import test from 'node:test';
import type { TextDocument } from 'vscode';
import {
  IPC_PROTOCOL_VERSION,
  SYMBOL_BRIDGE_METHODS,
  createWorkspacePathContext,
  hostPathPlatform,
  parseDocumentSymbolBridgeResponse,
  parseWorkspaceSymbolBridgeResponse,
  systemRuntimePrimitives,
  type IpcRequest,
  type JsonObject,
  type WorkspacePathAccess,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  SymbolsProviderBridge,
  type SymbolsProviderHost,
} from './symbols-provider.js';

const workspaceRoot = process.platform === 'win32' ? 'D:/workspace/app' : '/workspace/app';
const sourceFile = path.join(workspaceRoot, 'src', 'widget.ts');
const outsideFile = process.platform === 'win32' ? 'D:/private/secret.ts' : '/private/secret.ts';

const pathAccess: WorkspacePathAccess = {
  entryType: (value) => Promise.resolve(path.extname(value) === '.ts' ? 'file' : 'directory'),
  realpath: (value) => Promise.resolve(value),
};

const context = () => createWorkspacePathContext([{
  name: 'app',
  uriScheme: 'file',
  lexicalAbsolutePath: workspaceRoot,
}], hostPathPlatform, pathAccess, systemRuntimePrimitives);

const request = (method: string, params: JsonObject): IpcRequest => ({
  protocolVersion: IPC_PROTOCOL_VERSION,
  kind: 'request',
  id: 'req_AAAAAAAAAAAAAAAAAAAAAA',
  method,
  deadlineAt: Date.now() + 10_000,
  params,
});

const position = (line: number, character: number) => ({ line, character });
const range = (line: number, character: number) => ({
  start: position(line, character),
  end: position(line, character + 1),
});
const uri = (fsPath: string) => ({ scheme: 'file', fsPath });

class FakeSymbolsHost implements SymbolsProviderHost {
  readonly calls: Array<{ readonly command: string; readonly args: readonly unknown[] }> = [];
  readonly results = new Map<string, unknown>();
  readonly document: TextDocument;

  constructor(text: string) {
    this.document = {
      uri: uri(sourceFile),
      getText: () => text,
    } as unknown as TextDocument;
  }

  executeCommand(command: string, ...args: readonly unknown[]): PromiseLike<unknown> {
    this.calls.push({ command, args });
    return Promise.resolve(this.results.get(command));
  }

  openTextDocument(): PromiseLike<TextDocument> {
    return Promise.resolve(this.document);
  }

  openProviderDocument(): PromiseLike<TextDocument> {
    return Promise.resolve(this.document);
  }
}

test('workspace symbol bridge maps logical locations, coordinates, snippets, and safe warnings', async () => {
  const host = new FakeSymbolsHost('header\nclass Widget {}\nfooter');
  host.results.set('vscode.executeWorkspaceSymbolProvider', [
    {
      name: 'Widget',
      kind: 4,
      containerName: 'App',
      location: { uri: uri(sourceFile), range: range(1, 6) },
    },
    {
      name: 'Secret',
      kind: 12,
      location: { uri: uri(outsideFile), range: range(0, 0) },
    },
    { name: '', kind: 4 },
  ]);
  const bridge = new SymbolsProviderBridge(host, pathAccess);
  const raw = await bridge.handle(
    await context(),
    request(SYMBOL_BRIDGE_METHODS.workspace, { query: 'Widget', contextLines: 1 }),
    new AbortController().signal,
  );
  const result = parseWorkspaceSymbolBridgeResponse(raw);

  assert.equal(result.status, 'completed');
  if (result.status === 'completed') {
    assert.deepEqual(result.candidates, [{
      name: 'Widget',
      kind: 'class',
      file: 'src/widget.ts',
      line: 2,
      column: 7,
      container: 'App',
      snippet: 'header\nclass Widget {}\nfooter',
    }]);
    assert.deepEqual(
      new Set(result.warnings),
      new Set(['provider_candidate_outside_workspace', 'provider_candidate_invalid']),
    );
  }
  assert.deepEqual(host.calls[0]?.args, ['Widget']);
});

test('document symbol bridge flattens hierarchical and flat providers in preorder with full paths', async () => {
  const host = new FakeSymbolsHost('class Widget {\n  run() {}\n}\nconst loose = 1;');
  host.results.set('vscode.executeDocumentSymbolProvider', [
    {
      name: 'Widget',
      kind: 4,
      selectionRange: range(0, 6),
      children: [{
        name: 'run',
        kind: 5,
        selectionRange: range(1, 2),
        children: [],
      }],
    },
    {
      name: 'loose',
      kind: 13,
      location: { uri: uri(sourceFile), range: range(3, 6) },
    },
    { name: 'Ghost', kind: 4, selectionRange: range(99, 0), children: [] },
  ]);
  const bridge = new SymbolsProviderBridge(host, pathAccess);
  const raw = await bridge.handle(
    await context(),
    request(SYMBOL_BRIDGE_METHODS.document, { file: 'src/widget.ts', contextLines: 1 }),
    new AbortController().signal,
  );
  const result = parseDocumentSymbolBridgeResponse(raw);

  assert.equal(result.status, 'completed');
  if (result.status === 'completed') {
    assert.deepEqual(result.candidates, [
      {
        kind: 'class',
        path: ['Widget'],
        line: 1,
        column: 7,
        snippet: 'class Widget {\n  run() {}',
      },
      {
        kind: 'method',
        path: ['Widget', 'run'],
        line: 2,
        column: 3,
        snippet: 'class Widget {\n  run() {}\n}',
      },
      {
        kind: 'constant',
        path: ['loose'],
        line: 4,
        column: 7,
        snippet: '}\nconst loose = 1;',
      },
    ]);
    assert.deepEqual(result.warnings, ['provider_candidate_invalid']);
  }
  assert.equal(host.calls[0]?.args[0], host.document.uri);
});

test('symbol bridge preserves provider unavailability instead of returning an empty collection', async () => {
  const host = new FakeSymbolsHost('class Widget {}');
  host.executeCommand = (command) => Promise.reject(new Error(`command '${command}' not found`));
  const bridge = new SymbolsProviderBridge(host, pathAccess);
  const raw = await bridge.handle(
    await context(),
    request(SYMBOL_BRIDGE_METHODS.workspace, { query: 'Widget', contextLines: 0 }),
    new AbortController().signal,
  );
  assert.deepEqual(parseWorkspaceSymbolBridgeResponse(raw), { status: 'unavailable' });
});
