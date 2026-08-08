import assert from 'node:assert/strict';
import path from 'node:path';
import test from 'node:test';
import type { Position, Range, TextDocument, TextEdit } from 'vscode';
import {
  createWorkspacePathContext,
  hostPathPlatform,
  systemRuntimePrimitives,
  type RenamePreviewBridgeRequest,
  type WorkspacePathAccess,
  type WorkspaceRouteIdentity,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  DocumentEpochTracker,
  type DiskFileSnapshot,
  type ProviderWorkspaceEdit,
} from './workspace-edit-normalizer.js';
import {
  RenamePreviewExecutor,
  type RenamePreviewHost,
} from './rename-preview-provider.js';

const workspaceRoot = process.platform === 'win32' ? 'D:/workspace/app' : '/workspace/app';
const sourceFile = path.join(workspaceRoot, 'src', 'a.ts');
const otherFile = path.join(workspaceRoot, 'src', 'b.ts');
const workspace: WorkspaceRouteIdentity = {
  workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA' as WorkspaceRouteIdentity['workspaceId'],
  generation: 7,
};

const uri = (fsPath: string) => ({ scheme: 'file', fsPath });
const point = (line: number, character: number) => ({ line, character });
const range = (startLine: number, startCharacter: number, endLine: number, endCharacter: number) => ({
  start: point(startLine, startCharacter),
  end: point(endLine, endCharacter),
});
const textEdit = (rangeValue: ReturnType<typeof range>, newText: string) => ({
  kind: 'text',
  range: rangeValue,
  newText,
});

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

  constructor(fsPath: string, text: string, version = 1) {
    this.uri = uri(fsPath);
    this.text = text;
    this.version = version;
  }

  getText(): string {
    return this.text;
  }

  validatePosition(value: Position): Position {
    const lines = lineTable(this.text);
    const line = Math.max(0, Math.min(value.line, lines.length - 1));
    return point(line, Math.max(0, Math.min(value.character, lines[line]?.length ?? 0))) as Position;
  }

  validateRange(value: Range): Range {
    return {
      start: this.validatePosition(value.start),
      end: this.validatePosition(value.end),
    } as Range;
  }

  offsetAt(value: Position): number {
    const validated = this.validatePosition(value);
    const current = lineTable(this.text)[validated.line];
    return (current?.start ?? 0) + validated.character;
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

const providerEdit = (
  entries: readonly (readonly [unknown, readonly unknown[]])[],
  size = entries.length,
): ProviderWorkspaceEdit => ({ size, entries: () => entries });

class FakeRenameHost implements RenamePreviewHost {
  readonly calls: string[] = [];
  readonly disk = new Map<string, Uint8Array>();
  readonly documents = new Map<string, FakeDocument>();
  edit: ProviderWorkspaceEdit;
  identityResult: (fsPath: string, position: ReturnType<typeof point>) => unknown = () => ([{
    uri: uri(sourceFile),
    range: range(0, 0, 0, 3),
  }]);
  mutateAfterPrepare = false;
  referenceResult: unknown = [];
  prepareError: Error | undefined;
  prepareResult: unknown = range(0, 0, 0, 3);

  constructor() {
    const source = new FakeDocument(sourceFile, 'old();', 3);
    const other = new FakeDocument(otherFile, 'const ref = old;', 4);
    this.documents.set(sourceFile, source);
    this.documents.set(otherFile, other);
    this.disk.set(sourceFile, new TextEncoder().encode(source.text));
    this.disk.set(otherFile, new TextEncoder().encode(other.text));
    this.edit = providerEdit([
      [uri(otherFile), [textEdit(range(0, 12, 0, 15), 'next')]],
      [uri(sourceFile), [textEdit(range(0, 0, 0, 3), 'next')]],
    ]);
  }

  createPosition(line: number, character: number): Position {
    return point(line, character) as Position;
  }

  createRange(value: ReturnType<typeof range>): Range {
    return value as Range;
  }

  executeCommand(command: string, ...args: readonly unknown[]): PromiseLike<unknown> {
    this.calls.push(command);
    if (command === 'vscode.prepareRename') {
      if (this.prepareError !== undefined) return Promise.reject(this.prepareError);
      if (this.mutateAfterPrepare) {
        const source = this.documents.get(sourceFile)!;
        source.text = 'changed();';
        source.version += 1;
      }
      return Promise.resolve(this.prepareResult);
    }
    if (command === 'vscode.executeDocumentRenameProvider') return Promise.resolve(this.edit);
    if (command === 'vscode.executeDefinitionProvider') {
      return Promise.resolve(this.identityResult(
        (args[0] as { readonly fsPath: string }).fsPath,
        args[1] as ReturnType<typeof point>,
      ));
    }
    if (command === 'vscode.executeDeclarationProvider') return Promise.resolve([]);
    if (command === 'vscode.executeReferenceProvider') return Promise.resolve(this.referenceResult);
    return Promise.reject(new Error('Unexpected command.'));
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
    if (document === undefined) return Promise.reject(new Error('Missing fake document.'));
    return Promise.resolve(document as unknown as TextDocument);
  }

  readDiskFile(value: unknown): PromiseLike<DiskFileSnapshot> {
    const bytes = this.disk.get((value as { readonly fsPath: string }).fsPath);
    return Promise.resolve(bytes === undefined ? { exists: false } : { exists: true, bytes });
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

const request = (overrides: Partial<RenamePreviewBridgeRequest> = {}): RenamePreviewBridgeRequest => ({
  workspace,
  file: 'src/a.ts',
  line: 1,
  column: 2,
  newName: 'next',
  includeGlobs: ['src/**'],
  ...overrides,
});

const execute = async (host: FakeRenameHost, input = request()) => {
  const executor = new RenamePreviewExecutor(host, {
    epochTracker: new DocumentEpochTracker(),
    pathAccess,
  });
  return executor.preview(await workspaceContext(), workspace, input, new AbortController().signal);
};

test('rename preview prepares first and normalizes one complete multi-file text-only edit', async () => {
  const host = new FakeRenameHost();
  const result = await execute(host);
  assert.equal(result.status, 'completed');
  if (result.status !== 'completed') return;
  assert.deepEqual(host.calls, [
    'vscode.prepareRename',
    'vscode.executeDocumentRenameProvider',
    'vscode.executeDefinitionProvider',
    'vscode.executeDefinitionProvider',
    'vscode.executeDefinitionProvider',
  ]);
  assert.deepEqual(result.normalizedEdit.textChanges.map((change) => change.file), [
    'src/a.ts',
    'src/b.ts',
  ]);
  assert.deepEqual(result.normalizedEdit.textChanges.map((change) => change.edits[0]?.oldText), [
    'old',
    'old',
  ]);
  assert.equal(result.normalizedEdit.targets.length, 2);
});

test('prepare rejection is explicit, bounded, and prevents rename execution', async () => {
  const host = new FakeRenameHost();
  host.prepareError = new Error(`Cannot rename ${sourceFile}`);
  assert.deepEqual(await execute(host), {
    status: 'prepareRejected',
    reason: 'notRenameable',
  });
  assert.deepEqual(host.calls, ['vscode.prepareRename']);
});

test('resource operations and invalid prepare ranges reject the whole preview', async () => {
  const resourceHost = new FakeRenameHost();
  resourceHost.edit = providerEdit([
    [uri(sourceFile), [textEdit(range(0, 0, 0, 3), 'next')]],
  ], 2);
  assert.deepEqual(await execute(resourceHost), {
    status: 'editConflict',
    reason: 'unsupportedEdit',
  });

  const invalidPrepareHost = new FakeRenameHost();
  invalidPrepareHost.prepareResult = range(0, 0, 0, 99);
  assert.deepEqual(await execute(invalidPrepareHost), {
    status: 'prepareRejected',
    reason: 'invalidResult',
  });
  assert.deepEqual(invalidPrepareHost.calls, ['vscode.prepareRename']);
});

test('position clamp and source changes stop before a preview can be cached', async () => {
  const invalidPositionHost = new FakeRenameHost();
  assert.deepEqual(await execute(invalidPositionHost, request({ column: 99 })), {
    status: 'positionOutOfRange',
  });
  assert.deepEqual(invalidPositionHost.calls, []);

  const changedHost = new FakeRenameHost();
  changedHost.mutateAfterPrepare = true;
  assert.deepEqual(await execute(changedHost), {
    status: 'documentChanged',
    reason: 'content',
    files: ['src/a.ts'],
  });
  assert.deepEqual(changedHost.calls, ['vscode.prepareRename']);
});

test('workspace generation mismatch and escaped source never call providers', async () => {
  const host = new FakeRenameHost();
  assert.deepEqual(await execute(host, request({
    workspace: { ...workspace, generation: workspace.generation + 1 },
  })), { status: 'workspaceChanged' });
  assert.deepEqual(host.calls, []);

  assert.deepEqual(await execute(host, request({ file: '../outside.ts' })), {
    status: 'pathOutsideWorkspace',
  });
  assert.deepEqual(host.calls, []);
});

test('empty and text-mismatched rename edits are rejected without an applicable preview', async () => {
  const emptyHost = new FakeRenameHost();
  emptyHost.edit = providerEdit([]);
  assert.deepEqual(await execute(emptyHost), { status: 'noEdits' });
  assert.deepEqual(emptyHost.calls, [
    'vscode.prepareRename',
    'vscode.executeDocumentRenameProvider',
  ]);

  const textMismatchHost = new FakeRenameHost();
  textMismatchHost.edit = providerEdit([
    [uri(otherFile), [textEdit(range(0, 6, 0, 9), 'next')]],
    [uri(sourceFile), [textEdit(range(0, 0, 0, 3), 'next')]],
  ]);
  assert.deepEqual(await execute(textMismatchHost), {
    status: 'identityRejected',
    reason: 'textMismatch',
    checkedEdits: 0,
    totalEdits: 2,
    files: ['src/b.ts'],
  });
  assert.deepEqual(textMismatchHost.calls, [
    'vscode.prepareRename',
    'vscode.executeDocumentRenameProvider',
  ]);
});

test('rename scope rejects provider targets before semantic identity verification', async () => {
  const host = new FakeRenameHost();
  assert.deepEqual(await execute(host, request({ includeGlobs: ['src/a.ts'] })), {
    status: 'scopeRejected',
    files: ['src/b.ts'],
    totalFiles: 2,
  });
  assert.deepEqual(host.calls, [
    'vscode.prepareRename',
    'vscode.executeDocumentRenameProvider',
  ]);
});

test('same-name edits resolving to another definition reject the whole rename', async () => {
  const host = new FakeRenameHost();
  host.identityResult = (fsPath) => fsPath === otherFile
    ? [
        { uri: uri(sourceFile), range: range(0, 0, 0, 3) },
        { uri: uri(otherFile), range: range(0, 6, 0, 9) },
      ]
    : [{ uri: uri(sourceFile), range: range(0, 0, 0, 3) }];
  assert.deepEqual(await execute(host), {
    status: 'identityRejected',
    reason: 'mismatchedSymbol',
    checkedEdits: 1,
    totalEdits: 2,
    files: ['src/b.ts'],
  });
  assert.deepEqual(host.calls, [
    'vscode.prepareRename',
    'vscode.executeDocumentRenameProvider',
    'vscode.executeDefinitionProvider',
    'vscode.executeDefinitionProvider',
    'vscode.executeDefinitionProvider',
  ]);
});

test('unresolved rename edits require an exact target reference position', async () => {
  const acceptedHost = new FakeRenameHost();
  acceptedHost.identityResult = (fsPath) => fsPath === otherFile
    ? []
    : [{ uri: uri(sourceFile), range: range(0, 0, 0, 3) }];
  acceptedHost.referenceResult = [
    { uri: uri(sourceFile), range: range(0, 0, 0, 3) },
    { uri: uri(otherFile), range: range(0, 12, 0, 15) },
  ];
  assert.equal((await execute(acceptedHost)).status, 'completed');
  assert.equal(acceptedHost.calls.at(-1), 'vscode.executeReferenceProvider');

  const rejectedHost = new FakeRenameHost();
  rejectedHost.identityResult = acceptedHost.identityResult;
  rejectedHost.referenceResult = [
    { uri: uri(sourceFile), range: range(0, 0, 0, 3) },
  ];
  assert.deepEqual(await execute(rejectedHost), {
    status: 'identityRejected',
    reason: 'editUnresolved',
    checkedEdits: 1,
    totalEdits: 2,
    files: ['src/b.ts'],
  });
  assert.equal(rejectedHost.calls.at(-1), 'vscode.executeReferenceProvider');
});
