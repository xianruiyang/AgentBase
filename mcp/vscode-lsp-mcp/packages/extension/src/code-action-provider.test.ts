import assert from 'node:assert/strict';
import path from 'node:path';
import test from 'node:test';
import type { Position, Range, TextDocument, TextEdit } from 'vscode';
import {
  MUTATION_CODE_ACTION_PREVIEW_BRIDGE_METHOD,
  MUTATION_CODE_ACTIONS_BRIDGE_METHOD,
  canonicalizeJson,
  createWorkspacePathContext,
  hostPathPlatform,
  parseCodeActionPreviewBridgeResponse,
  parseCodeActionsBridgeResponse,
  systemRuntimePrimitives,
  type CodeActionPreviewBridgeRequest,
  type CodeActionsBridgeRequest,
  type JsonObject,
  type WorkspacePathAccess,
  type WorkspaceRouteIdentity,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  MutationApplyExecutor,
  type MutationApplyHost,
} from './mutation-apply-provider.js';
import {
  CodeActionProviderBridge,
  type CodeActionProviderHost,
} from './code-action-provider.js';
import {
  DocumentEpochTracker,
  type DiskFileSnapshot,
  type ProviderWorkspaceEdit,
} from './workspace-edit-normalizer.js';

const workspaceRoot = process.platform === 'win32' ? 'D:/workspace/app' : '/workspace/app';
const sourceFile = path.join(workspaceRoot, 'src', 'a.ts');
const targetFile = path.join(workspaceRoot, 'src', 'b.ts');
const workspace: WorkspaceRouteIdentity = {
  workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA' as WorkspaceRouteIdentity['workspaceId'],
  generation: 8,
};

const uri = (fsPath: string) => ({ scheme: 'file', fsPath });
const point = (line: number, character: number) => ({ line, character });
const range = (startLine: number, startCharacter: number, endLine: number, endCharacter: number) => ({
  start: point(startLine, startCharacter),
  end: point(endLine, endCharacter),
});
const providerTextEdit = (
  value: ReturnType<typeof range>,
  newText: string,
) => ({ kind: 'text', range: value, newText });
const providerEdit = (
  entries: readonly (readonly [unknown, readonly unknown[]])[],
  size = entries.length,
): ProviderWorkspaceEdit => ({ size, entries: () => entries });

const lineTable = (text: string): readonly { readonly start: number; readonly length: number }[] => {
  const lines: Array<{ readonly start: number; readonly length: number }> = [];
  let start = 0;
  for (let index = 0; index < text.length; index += 1) {
    if (text[index] === '\r' && text[index + 1] === '\n') {
      lines.push({ start, length: index - start });
      index += 1;
      start = index + 1;
    } else if (text[index] === '\n' || text[index] === '\r') {
      lines.push({ start, length: index - start });
      start = index + 1;
    }
  }
  lines.push({ start, length: text.length - start });
  return lines;
};

class FakeDocument {
  readonly uri: ReturnType<typeof uri>;
  eol = 1;
  text: string;
  version: number;

  constructor(fsPath: string, text: string, version: number) {
    this.uri = uri(fsPath);
    this.text = text;
    this.version = version;
  }

  getText(): string {
    return this.text;
  }

  validateRange(value: Range): Range {
    const lines = lineTable(this.text);
    const clamp = (candidate: Position): Position => {
      const line = Math.max(0, Math.min(candidate.line, lines.length - 1));
      return point(
        line,
        Math.max(0, Math.min(candidate.character, lines[line]?.length ?? 0)),
      ) as Position;
    };
    return { start: clamp(value.start), end: clamp(value.end) } as Range;
  }

  offsetAt(value: Position): number {
    const validated = this.validateRange({ start: value, end: value } as Range).start;
    return (lineTable(this.text)[validated.line]?.start ?? 0) + validated.character;
  }

  positionAt(rawOffset: number): Position {
    const offset = Math.max(0, Math.min(rawOffset, this.text.length));
    const lines = lineTable(this.text);
    for (let index = lines.length - 1; index >= 0; index -= 1) {
      const current = lines[index];
      if (current !== undefined && offset >= current.start) {
        return point(index, Math.min(offset - current.start, current.length)) as Position;
      }
    }
    return point(0, 0) as Position;
  }
}

class FakeCodeActionHost implements CodeActionProviderHost, MutationApplyHost {
  readonly calls: Array<{ readonly command: string; readonly args: readonly unknown[] }> = [];
  readonly disk = new Map<string, Uint8Array>();
  readonly documents = new Map<string, FakeDocument>();
  actions: readonly unknown[] = [];
  mutateSourceAfterProvider = false;

  constructor() {
    const source = new FakeDocument(sourceFile, 'old();', 3);
    const target = new FakeDocument(targetFile, 'const value = old;', 4);
    this.documents.set(sourceFile, source);
    this.documents.set(targetFile, target);
    this.disk.set(sourceFile, new TextEncoder().encode(source.text));
    this.disk.set(targetFile, new TextEncoder().encode(target.text));
  }

  applyEdit(): PromiseLike<boolean> {
    return Promise.reject(new Error('Apply is not used by Code Action preview validation.'));
  }

  createRange(value: ReturnType<typeof range>): Range {
    return value as Range;
  }

  createTextEdit(value: ReturnType<typeof range>, newText: string): unknown {
    return { range: value, newText };
  }

  createWorkspaceEdit(): unknown {
    return {};
  }

  executeCommand(command: string, ...args: readonly unknown[]): PromiseLike<unknown> {
    this.calls.push({ command, args });
    if (command !== 'vscode.executeCodeActionProvider') {
      return Promise.reject(new Error('Unexpected provider command.'));
    }
    if (this.mutateSourceAfterProvider) {
      const source = this.documents.get(sourceFile)!;
      source.text = 'changed();';
      source.version += 1;
    }
    return Promise.resolve(this.actions);
  }

  fileUri(absolutePath: string): unknown {
    return uri(absolutePath);
  }

  isTextEdit(value: unknown): value is TextEdit {
    return value !== null && typeof value === 'object' &&
      (value as { readonly kind?: unknown }).kind === 'text';
  }

  openTextDocument(value: unknown): PromiseLike<TextDocument> {
    const fsPath = typeof value === 'string'
      ? value
      : (value as { readonly fsPath: string }).fsPath;
    const document = this.documents.get(fsPath);
    return document === undefined
      ? Promise.reject(new Error('Missing fake document.'))
      : Promise.resolve(document as unknown as TextDocument);
  }

  readDiskFile(value: unknown): PromiseLike<DiskFileSnapshot> {
    const bytes = this.disk.get((value as { readonly fsPath: string }).fsPath);
    return Promise.resolve(bytes === undefined ? { exists: false } : { exists: true, bytes });
  }

  setTextEdits(): void {
    throw new Error('Apply is not used by Code Action preview validation.');
  }

  uriString(value: unknown): string {
    return `file://${(value as { readonly fsPath: string }).fsPath.replaceAll('\\', '/')}`;
  }
}

const pathAccess: WorkspacePathAccess = {
  entryType: (value) => Promise.resolve(value.endsWith('.ts') ? 'file' : 'directory'),
  realpath: (value) => Promise.resolve(value),
};

const workspaceContext = () => createWorkspacePathContext([{
  name: 'app',
  uriScheme: 'file',
  lexicalAbsolutePath: workspaceRoot,
}], hostPathPlatform, pathAccess, systemRuntimePrimitives);

const listRequest = (
  overrides: Partial<CodeActionsBridgeRequest> = {},
): CodeActionsBridgeRequest => ({
  workspace,
  file: 'src/a.ts',
  range: { startLine: 1, startColumn: 1, endLine: 1, endColumn: 4 },
  resultStart: 1,
  resultEnd: 10,
  ...overrides,
});

const fixture = async () => {
  const host = new FakeCodeActionHost();
  const tracker = new DocumentEpochTracker();
  const applyExecutor = new MutationApplyExecutor(host, {
    epochTracker: tracker,
    pathAccess,
    primitives: systemRuntimePrimitives,
  });
  const bridge = new CodeActionProviderBridge(host, {
    applyExecutor,
    epochTracker: tracker,
    pathAccess,
  });
  return { bridge, context: await workspaceContext(), host };
};

const handleList = async (
  state: Awaited<ReturnType<typeof fixture>>,
  request = listRequest(),
) => parseCodeActionsBridgeResponse(await state.bridge.handle(
  state.context,
  workspace,
  {
    method: MUTATION_CODE_ACTIONS_BRIDGE_METHOD,
    params: canonicalizeJson(request) as JsonObject,
  },
  new AbortController().signal,
));

const handlePreview = async (
  state: Awaited<ReturnType<typeof fixture>>,
  request: CodeActionPreviewBridgeRequest,
) => parseCodeActionPreviewBridgeResponse(await state.bridge.handle(
  state.context,
  workspace,
  {
    method: MUTATION_CODE_ACTION_PREVIEW_BRIDGE_METHOD,
    params: canonicalizeJson(request) as JsonObject,
  },
  new AbortController().signal,
));

test('Code Action provider filters unsafe candidates, prefers stably, deduplicates, and windows safely', async () => {
  const state = await fixture();
  const sourceFix = providerEdit([
    [uri(sourceFile), [providerTextEdit(range(0, 0, 0, 3), 'fixed')]],
  ]);
  const targetFix = providerEdit([
    [uri(targetFile), [providerTextEdit(range(0, 14, 0, 17), 'fixed')]],
  ]);
  state.host.actions = [
    { title: 'Duplicate fix', kind: 'quickfix', edit: sourceFix },
    { title: 'Preferred target fix', kind: 'refactor.rewrite', isPreferred: true, edit: targetFix },
    { title: 'Duplicate fix', kind: 'quickfix', isPreferred: true, edit: sourceFix },
    { title: 'Disabled', kind: 'quickfix', disabled: { reason: 'private details' }, edit: sourceFix },
    { title: 'Command', kind: 'quickfix', command: { command: 'private.command' }, edit: sourceFix },
    { title: 'Missing edit', kind: 'quickfix' },
    { title: 'Resource operation', kind: 'quickfix', edit: providerEdit([
      [uri(sourceFile), [providerTextEdit(range(0, 0, 0, 3), 'fixed')]],
    ], 2) },
    { title: 'Snippet', kind: 'quickfix', edit: providerEdit([
      [uri(sourceFile), [{ kind: 'snippet', range: range(0, 0, 0, 3), snippet: 'fixed' }]],
    ]) },
  ];

  const response = await handleList(state);
  assert.equal(response.status, 'completed');
  if (response.status !== 'completed') return;
  assert.deepEqual(response.candidates.map((candidate) => ({
    title: candidate.title,
    preferred: candidate.preferred,
  })), [
    { title: 'Preferred target fix', preferred: true },
    { title: 'Duplicate fix', preferred: true },
  ]);
  assert.equal(response.available, 2);
  assert.deepEqual(response.warnings, [
    'code_action_command_filtered',
    'code_action_disabled_filtered',
    'code_action_missing_edit_filtered',
    'code_action_unsupported_edit_filtered',
  ]);
  assert.equal(JSON.stringify(response).includes('private.command'), false);
  assert.equal(JSON.stringify(response).includes('private details'), false);
  assert.deepEqual(state.host.calls[0]?.args.slice(2), [undefined, 100]);
  assert.deepEqual(state.host.calls[0]?.args[1], range(0, 0, 0, 3));

  const window = await handleList(state, listRequest({ resultStart: 2, resultEnd: 2 }));
  assert.equal(window.status, 'completed');
  if (window.status !== 'completed') return;
  assert.deepEqual(window.candidates.map((candidate) => candidate.title), ['Duplicate fix']);
  assert.equal(window.available, 2);

  const quickFixes = await handleList(state, listRequest({ onlyKinds: ['quickfix'] }));
  assert.equal(quickFixes.status, 'completed');
  if (quickFixes.status !== 'completed') return;
  assert.deepEqual(quickFixes.candidates.map((candidate) => candidate.title), ['Duplicate fix']);
});

test('Code Action list rejects clamped ranges and source changes before caching candidates', async () => {
  const invalid = await fixture();
  invalid.host.actions = [];
  assert.deepEqual(await handleList(invalid, listRequest({
    range: { startLine: 1, startColumn: 1, endLine: 1, endColumn: 99 },
  })), { status: 'positionOutOfRange' });
  assert.equal(invalid.host.calls.length, 0);

  const changed = await fixture();
  changed.host.actions = [{
    title: 'Fix',
    kind: 'quickfix',
    edit: providerEdit([
      [uri(targetFile), [providerTextEdit(range(0, 14, 0, 17), 'fixed')]],
    ]),
  }];
  changed.host.mutateSourceAfterProvider = true;
  assert.deepEqual(await handleList(changed), {
    status: 'documentChanged',
    reason: 'content',
    files: ['src/a.ts'],
  });
});

test('Code Action preview validates cached source and targets without another Provider call', async () => {
  const state = await fixture();
  state.host.actions = [{
    title: 'Fix target',
    kind: 'quickfix',
    edit: providerEdit([
      [uri(targetFile), [providerTextEdit(range(0, 14, 0, 17), 'fixed')]],
    ]),
  }];
  const listed = await handleList(state);
  assert.equal(listed.status, 'completed');
  if (listed.status !== 'completed') return;
  const request: CodeActionPreviewBridgeRequest = {
    workspace,
    sourceSnapshot: listed.sourceSnapshot,
    normalizedEdit: listed.candidates[0]!.normalizedEdit,
  };
  assert.deepEqual(await handlePreview(state, request), { status: 'ready' });
  assert.equal(state.host.calls.length, 1);

  state.host.documents.get(targetFile)!.version += 1;
  assert.deepEqual(await handlePreview(state, request), {
    status: 'documentChanged',
    reason: 'version',
    files: ['src/b.ts'],
  });
  assert.equal(state.host.calls.length, 1);

  state.host.documents.get(targetFile)!.version -= 1;
  const candidate = listed.candidates[0]!;
  const badEdit = {
    textChanges: [{
      ...candidate.normalizedEdit.textChanges[0]!,
      edits: [{
        ...candidate.normalizedEdit.textChanges[0]!.edits[0]!,
        range: { startLine: 1, startColumn: 100, endLine: 1, endColumn: 100 },
        startOffset: 99,
        endOffset: 99,
        oldText: '',
      }],
    }],
    targets: candidate.normalizedEdit.targets,
  };
  assert.deepEqual(await handlePreview(state, { ...request, normalizedEdit: badEdit }), {
    status: 'actionNotPreviewable',
    reason: 'cachedActionInvalid',
  });
  assert.equal(state.host.calls.length, 1);
});
