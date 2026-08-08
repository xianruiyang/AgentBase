import assert from 'node:assert/strict';
import path from 'node:path';
import test from 'node:test';
import type { TextDocument } from 'vscode';
import {
  IPC_PROTOCOL_VERSION,
  SYMBOL_INFO_BRIDGE_METHOD,
  createWorkspacePathContext,
  hostPathPlatform,
  parseSymbolInfoBridgeResponse,
  systemRuntimePrimitives,
  type IpcRequest,
  type JsonObject,
  type WorkspacePathAccess,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  SymbolInfoProviderBridge,
  type SymbolInfoProviderHost,
} from './symbol-info-provider.js';

const workspaceRoot = process.platform === 'win32' ? 'D:/workspace/app' : '/workspace/app';
const sourceFile = path.join(workspaceRoot, 'src', 'widget.ts');
const uri = (fsPath: string) => ({ scheme: 'file', fsPath });
const point = (line: number, character: number) => ({ line, character });
const range = (line: number, character: number) => ({
  start: point(line, character),
  end: point(line, character + 1),
});

const pathAccess: WorkspacePathAccess = {
  entryType: (value) => Promise.resolve(path.extname(value) === '.ts' ? 'file' : 'directory'),
  realpath: (value) => Promise.resolve(value),
};

const context = () => createWorkspacePathContext([{
  name: 'app',
  uriScheme: 'file',
  lexicalAbsolutePath: workspaceRoot,
}], hostPathPlatform, pathAccess, systemRuntimePrimitives);

const request = (params: JsonObject): IpcRequest => ({
  protocolVersion: IPC_PROTOCOL_VERSION,
  kind: 'request',
  id: 'req_AAAAAAAAAAAAAAAAAAAAAA',
  method: SYMBOL_INFO_BRIDGE_METHOD,
  deadlineAt: Date.now() + 10_000,
  params,
});

class FakeSymbolInfoHost implements SymbolInfoProviderHost {
  readonly calls: Array<{ readonly command: string; readonly args: readonly unknown[] }> = [];
  readonly positions: Array<{ readonly line: number; readonly character: number }> = [];
  readonly results = new Map<string, unknown>();
  readonly document: TextDocument;

  constructor(text: string) {
    this.document = { uri: uri(sourceFile), getText: () => text } as unknown as TextDocument;
  }

  createPosition(line: number, character: number): unknown {
    const value = { line, character };
    this.positions.push(value);
    return value;
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

test('symbol info bridge invokes selected providers and maps fixed-group DTOs', async () => {
  const host = new FakeSymbolInfoHost('header\nclass Widget {}\nfooter');
  host.results.set('vscode.executeHoverProvider', [{
    contents: [' Widget docs\r\n', { language: 'ts', value: 'class Widget {}' }],
  }]);
  host.results.set('vscode.executeDefinitionProvider', [{
    targetUri: uri(sourceFile),
    targetRange: range(0, 0),
    targetSelectionRange: range(1, 6),
  }]);
  host.results.set('vscode.executeSignatureHelpProvider', {
    activeSignature: 1,
    activeParameter: 0,
    signatures: [
      {
        label: 'build(name: string)',
        activeParameter: 0,
        documentation: { value: 'Builds a widget.' },
        parameters: [{ label: [6, 18], documentation: 'Widget name.' }],
      },
      { label: 'build()', documentation: 'Builds the default widget.', parameters: [] },
    ],
  });
  const bridge = new SymbolInfoProviderBridge(host, pathAccess);
  const raw = await bridge.handle(await context(), request({
    file: 'src/widget.ts',
    line: 2,
    column: 7,
    include: ['signatureHelp', 'definition', 'hover'],
    contextLines: 1,
  }), new AbortController().signal);
  const result = parseSymbolInfoBridgeResponse(raw);

  assert.equal(result.status, 'completed');
  if (result.status === 'completed') {
    assert.deepEqual(result.candidates, [
      { type: 'hover', text: 'Widget docs\n\n```ts\nclass Widget {}\n```' },
      {
        type: 'definition',
        file: 'src/widget.ts',
        line: 2,
        column: 7,
        snippet: 'header\nclass Widget {}\nfooter',
      },
      {
        type: 'signatureHelp',
        label: 'build()',
        activeSignature: true,
        documentation: 'Builds the default widget.',
      },
      {
        type: 'signatureHelp',
        label: 'build(name: string)',
        activeSignature: false,
        activeParameter: 0,
        documentation: 'Builds a widget.',
        parameters: [{ label: 'name: string', documentation: 'Widget name.' }],
      },
    ]);
  }
  assert.deepEqual(host.calls.map(({ command }) => command), [
    'vscode.executeHoverProvider',
    'vscode.executeDefinitionProvider',
    'vscode.executeSignatureHelpProvider',
  ]);
  assert.deepEqual(host.positions, [
    { line: 1, character: 6 },
    { line: 1, character: 6 },
    { line: 1, character: 6 },
  ]);
});

test('symbol info bridge exposes an out-of-range provider state instead of an empty result', async () => {
  const host = new FakeSymbolInfoHost('class Widget {}');
  host.results.set('vscode.executeDefinitionProvider', []);
  const bridge = new SymbolInfoProviderBridge(host, pathAccess);
  const raw = await bridge.handle(await context(), request({
    file: 'src/widget.ts',
    line: 9,
    column: 1,
    include: ['definition'],
    contextLines: 0,
  }), new AbortController().signal);

  assert.deepEqual(parseSymbolInfoBridgeResponse(raw), { status: 'positionOutOfRange' });
  assert.equal(host.calls.length, 0);
});
