import assert from 'node:assert/strict';
import test from 'node:test';
import type { TextDocument } from 'vscode';
import {
  HIERARCHY_BRIDGE_METHODS,
  IPC_PROTOCOL_VERSION,
  parseHierarchyExpandBridgeResponse,
  parseHierarchyPrepareBridgeResponse,
  parseHierarchyReleaseBridgeResponse,
  type IpcRequest,
  type JsonObject,
  type RootAlias,
  type WorkspacePathAccess,
  type WorkspacePathContext,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  HierarchyProviderBridge,
  type HierarchyProviderHost,
} from './hierarchy-provider.js';

const workspaceRoot = 'D:\\workspace\\app';
const sourceFile = `${workspaceRoot}\\src\\hierarchy.cpp`;
const sourceText = [
  'export function leafCall(): number {',
  '  return 1;',
  '}',
  'export function middleCall(): number {',
  '  return leafCall();',
  '}',
  'export function rootCall(): number {',
  '  return middleCall();',
  '}',
  'export class BaseType {}',
  'export class MiddleType extends BaseType {}',
  'export class LeafType extends MiddleType {}',
].join('\n');

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

const request = (method: string, params: JsonObject): IpcRequest => ({
  protocolVersion: IPC_PROTOCOL_VERSION,
  kind: 'request',
  id: 'req_AAAAAAAAAAAAAAAAAAAAAA',
  method,
  deadlineAt: Date.now() + 10_000,
  params,
});

const point = (line: number, character: number) => ({ line, character });
const range = (line: number, start: number, end: number) => ({
  start: point(line, start),
  end: point(line, end),
});
const item = (name: string, kind: number, line: number, character: number) => ({
  name,
  kind,
  uri: { scheme: 'file', fsPath: sourceFile },
  range: range(line, character, character + name.length),
  selectionRange: range(line, character, character + name.length),
  data: { privateProviderState: name },
});

class FakeHierarchyHost implements HierarchyProviderHost {
  readonly calls: Array<{ readonly command: string; readonly args: readonly unknown[] }> = [];
  readonly events: string[] = [];
  readonly middleCall = item('middleCall', 11, 3, 16);
  readonly rootCall = item('rootCall', 11, 6, 16);
  readonly leafCall = item('leafCall', 11, 0, 16);
  readonly middleType = item('MiddleType', 4, 10, 13);
  readonly baseType = item('BaseType', 4, 9, 13);
  readonly leafType = item('LeafType', 4, 11, 13);
  readonly document = {
    uri: { scheme: 'file', fsPath: sourceFile },
    getText: () => sourceText,
  } as unknown as TextDocument;
  readonly callPrepareResults: unknown[][] = [];

  createPosition(line: number, character: number): unknown {
    return { line, character };
  }

  openTextDocument(): PromiseLike<TextDocument> {
    this.events.push('activate');
    return Promise.resolve(this.document);
  }

  executeCommand(command: string, ...args: readonly unknown[]): PromiseLike<unknown> {
    this.events.push(command);
    this.calls.push({ command, args });
    if (command === 'vscode.prepareCallHierarchy') {
      return Promise.resolve(this.callPrepareResults.shift() ?? [this.middleCall]);
    }
    if (command === 'vscode.provideIncomingCalls') {
      return Promise.resolve([{ from: this.rootCall, fromRanges: [range(7, 9, 19)] }]);
    }
    if (command === 'vscode.provideOutgoingCalls') {
      return Promise.resolve([{ to: this.leafCall, fromRanges: [range(4, 9, 17)] }]);
    }
    if (command === 'vscode.prepareTypeHierarchy') return Promise.resolve([this.middleType]);
    if (command === 'vscode.provideSupertypes') return Promise.resolve([this.baseType]);
    if (command === 'vscode.provideSubtypes') return Promise.resolve([this.leafType]);
    return Promise.reject(new Error(`command '${command}' not found`));
  }
}

test('cold C++ call hierarchy retries a transient empty prepare result in one request', async () => {
  const host = new FakeHierarchyHost();
  host.callPrepareResults.push([], [host.middleCall]);
  const bridge = new HierarchyProviderBridge(host, pathAccess, () => 1_000);
  const prepared = parseHierarchyPrepareBridgeResponse(await bridge.handle(
    context,
    request(HIERARCHY_BRIDGE_METHODS.prepare, {
      kind: 'call', file: 'src/hierarchy.cpp', line: 4, column: 17,
    }),
    new AbortController().signal,
  ));
  assert.equal(prepared.status, 'completed');
  assert.equal(host.calls.filter(({ command }) => command === 'vscode.prepareCallHierarchy').length, 2);
});

test('an empty C++ prepare outside a callable token remains a valid empty result', async () => {
  const host = new FakeHierarchyHost();
  host.callPrepareResults.push([]);
  const bridge = new HierarchyProviderBridge(host, pathAccess, () => 1_000);
  const prepared = parseHierarchyPrepareBridgeResponse(await bridge.handle(
    context,
    request(HIERARCHY_BRIDGE_METHODS.prepare, {
      kind: 'call', file: 'src/hierarchy.cpp', line: 1, column: 1,
    }),
    new AbortController().signal,
  ));
  assert.equal(prepared.status, 'completed');
  assert.equal(prepared.status === 'completed' && prepared.nodes.length, 0);
  assert.equal(host.calls.filter(({ command }) => command === 'vscode.prepareCallHierarchy').length, 1);
});

test('call hierarchy bridge activates first, retains private items, and maps call-site frames', async () => {
  const host = new FakeHierarchyHost();
  const bridge = new HierarchyProviderBridge(host, pathAccess, () => 1_000);
  const prepared = parseHierarchyPrepareBridgeResponse(await bridge.handle(
    context,
    request(HIERARCHY_BRIDGE_METHODS.prepare, {
      kind: 'call', file: 'src/hierarchy.cpp', line: 4, column: 17,
    }),
    new AbortController().signal,
  ));
  assert.equal(prepared.status, 'completed');
  if (prepared.status !== 'completed') return;
  assert.deepEqual(prepared.nodes, [{
    nodeId: 'n1',
    symbol: {
      name: 'middleCall', kind: 'function', file: 'src/hierarchy.cpp', line: 4, column: 17,
    },
  }]);
  assert.deepEqual(host.events.slice(0, 2), ['activate', 'vscode.prepareCallHierarchy']);
  assert.equal(JSON.stringify(prepared).includes('privateProviderState'), false);

  const incoming = parseHierarchyExpandBridgeResponse(await bridge.handle(
    context,
    request(HIERARCHY_BRIDGE_METHODS.expand, {
      traversalId: prepared.traversalId, nodeId: 'n1', direction: 'incoming',
    }),
    new AbortController().signal,
  ));
  assert.deepEqual(incoming, {
    status: 'completed',
    nodes: [{
      nodeId: 'n2',
      symbol: {
        name: 'rootCall', kind: 'function', file: 'src/hierarchy.cpp', line: 7, column: 17,
      },
      callSites: [{ startLine: 8, startColumn: 10, endLine: 8, endColumn: 20 }],
    }],
  });
  assert.equal((host.calls.at(-1)?.args[0] as { data?: unknown }).data !== undefined, true);

  const released = parseHierarchyReleaseBridgeResponse(await bridge.handle(
    context,
    request(HIERARCHY_BRIDGE_METHODS.release, { traversalId: prepared.traversalId }),
    new AbortController().signal,
  ));
  assert.deepEqual(released, { status: 'completed' });
  assert.deepEqual(await bridge.handle(
    context,
    request(HIERARCHY_BRIDGE_METHODS.expand, {
      traversalId: prepared.traversalId, nodeId: 'n1', direction: 'outgoing',
    }),
    new AbortController().signal,
  ), { status: 'failed' });
});

test('type hierarchy bridge maps supertype and subtype nodes and rejects cross-kind directions', async () => {
  const host = new FakeHierarchyHost();
  const bridge = new HierarchyProviderBridge(host, pathAccess, () => 1_000);
  const prepared = parseHierarchyPrepareBridgeResponse(await bridge.handle(
    context,
    request(HIERARCHY_BRIDGE_METHODS.prepare, {
      kind: 'type', file: 'src/hierarchy.cpp', line: 11, column: 14,
    }),
    new AbortController().signal,
  ));
  assert.equal(prepared.status, 'completed');
  if (prepared.status !== 'completed') return;
  const supertype = parseHierarchyExpandBridgeResponse(await bridge.handle(
    context,
    request(HIERARCHY_BRIDGE_METHODS.expand, {
      traversalId: prepared.traversalId, nodeId: 'n1', direction: 'supertype',
    }),
    new AbortController().signal,
  ));
  const subtype = parseHierarchyExpandBridgeResponse(await bridge.handle(
    context,
    request(HIERARCHY_BRIDGE_METHODS.expand, {
      traversalId: prepared.traversalId, nodeId: 'n1', direction: 'subtype',
    }),
    new AbortController().signal,
  ));
  assert.equal(supertype.status === 'completed' && supertype.nodes[0]?.symbol.name, 'BaseType');
  assert.equal(subtype.status === 'completed' && subtype.nodes[0]?.symbol.name, 'LeafType');
  assert.deepEqual(await bridge.handle(
    context,
    request(HIERARCHY_BRIDGE_METHODS.expand, {
      traversalId: prepared.traversalId, nodeId: 'n1', direction: 'incoming',
    }),
    new AbortController().signal,
  ), { status: 'failed' });
});

test('hierarchy bridge fails closed for malformed requests and invalid positions', async () => {
  const host = new FakeHierarchyHost();
  const bridge = new HierarchyProviderBridge(host, pathAccess, () => 1_000);
  assert.deepEqual(await bridge.handle(
    context,
    request(HIERARCHY_BRIDGE_METHODS.prepare, {
      kind: 'call', file: 'src/hierarchy.cpp', line: 99, column: 1,
    }),
    new AbortController().signal,
  ), { status: 'positionOutOfRange' });
  assert.deepEqual(await bridge.handle(
    context,
    request(HIERARCHY_BRIDGE_METHODS.expand, {
      traversalId: 'bad', nodeId: 'n1', direction: 'incoming',
    }),
    new AbortController().signal,
  ), { status: 'failed' });
});
