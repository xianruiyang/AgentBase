import assert from 'node:assert/strict';
import path from 'node:path';
import test from 'node:test';
import type { Position, Range, TextDocument, TextEdit } from 'vscode';
import {
  createWorkspacePathContext,
  hostPathPlatform,
  systemRuntimePrimitives,
  type FormatPreviewBridgeRequest,
  type FormattingOptions,
  type WorkspacePathAccess,
  type WorkspaceRouteIdentity,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  FormatPreviewExecutor,
  type FormatPreviewHost,
} from './format-preview-provider.js';
import {
  DocumentEpochTracker,
  type DiskFileSnapshot,
} from './workspace-edit-normalizer.js';

const workspaceRoot = process.platform === 'win32' ? 'D:/workspace/app' : '/workspace/app';
const sourceFile = path.join(workspaceRoot, 'src', 'a.ts');
const workspace: WorkspaceRouteIdentity = {
  workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA' as WorkspaceRouteIdentity['workspaceId'],
  generation: 10,
};

const uri = (fsPath: string) => ({ scheme: 'file', fsPath });
const point = (line: number, character: number) => ({ line, character });
const range = (startLine: number, startCharacter: number, endLine: number, endCharacter: number) => ({
  start: point(startLine, startCharacter),
  end: point(endLine, endCharacter),
});
const textEdit = (value: ReturnType<typeof range>, newText: string) => ({
  kind: 'text',
  range: value,
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

class FakeFormatHost implements FormatPreviewHost {
  readonly calls: Array<{ readonly command: string; readonly args: readonly unknown[] }> = [];
  readonly disk = new Map<string, Uint8Array>();
  readonly document = new FakeDocument(sourceFile, '😀x();\n', 5);
  configured: FormattingOptions = { tabSize: 2, insertSpaces: false };
  mutateAfterProvider = false;
  result: unknown = [textEdit(range(0, 2, 0, 3), 'value')];

  constructor() {
    this.disk.set(sourceFile, new TextEncoder().encode(this.document.text));
  }

  createRange(value: ReturnType<typeof range>): Range {
    return value as Range;
  }

  executeCommand(command: string, ...args: readonly unknown[]): PromiseLike<unknown> {
    this.calls.push({ command, args });
    if (this.mutateAfterProvider) {
      this.document.text = 'changed();\n';
      this.document.version += 1;
    }
    return Promise.resolve(this.result);
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
    return fsPath === sourceFile
      ? Promise.resolve(this.document as unknown as TextDocument)
      : Promise.reject(new Error('Missing fake document.'));
  }

  readDiskFile(value: unknown): PromiseLike<DiskFileSnapshot> {
    const bytes = this.disk.get((value as { readonly fsPath: string }).fsPath);
    return Promise.resolve(bytes === undefined ? { exists: false } : { exists: true, bytes });
  }

  readFormattingOptions(): FormattingOptions {
    return this.configured;
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

const request = (
  overrides: Partial<FormatPreviewBridgeRequest> = {},
): FormatPreviewBridgeRequest => ({
  workspace,
  file: 'src/a.ts',
  ...overrides,
});

const fixture = async () => {
  const host = new FakeFormatHost();
  const executor = new FormatPreviewExecutor(host, {
    epochTracker: new DocumentEpochTracker(),
    pathAccess,
  });
  return { context: await workspaceContext(), executor, host };
};

const preview = (
  state: Awaited<ReturnType<typeof fixture>>,
  input = request(),
) => state.executor.preview(
  state.context,
  workspace,
  input,
  new AbortController().signal,
);

test('document format uses effective document options and normalizes UTF-16 text edits', async () => {
  const state = await fixture();
  state.host.disk.set(sourceFile, new TextEncoder().encode('disk snapshot differs\n'));
  const result = await preview(state);
  assert.equal(result.status, 'completed');
  if (result.status !== 'completed') return;
  assert.equal(state.host.calls[0]?.command, 'vscode.executeFormatDocumentProvider');
  assert.deepEqual(state.host.calls[0]?.args[1], { tabSize: 2, insertSpaces: false });
  assert.deepEqual(result.normalizedEdit.textChanges[0]?.edits[0], {
    range: { startLine: 1, startColumn: 3, endLine: 1, endColumn: 4 },
    startOffset: 2,
    endOffset: 3,
    oldText: 'x',
    newText: 'value',
    providerOrdinal: 0,
  });
});

test('range format converts one-based end-exclusive range without clamp and merges partial options', async () => {
  const state = await fixture();
  const result = await preview(state, request({
    range: { startLine: 1, startColumn: 3, endLine: 1, endColumn: 4 },
    options: { tabSize: 8 },
  }));
  assert.equal(result.status, 'completed');
  assert.equal(state.host.calls[0]?.command, 'vscode.executeFormatRangeProvider');
  assert.deepEqual(state.host.calls[0]?.args[1], range(0, 2, 0, 3));
  assert.deepEqual(state.host.calls[0]?.args[2], { tabSize: 8, insertSpaces: false });

  const invalid = await fixture();
  assert.deepEqual(await preview(invalid, request({
    range: { startLine: 1, startColumn: 3, endLine: 1, endColumn: 99 },
  })), { status: 'positionOutOfRange' });
  assert.equal(invalid.host.calls.length, 0);
});

test('empty format succeeds without targets and concurrent source changes fail before commit', async () => {
  const empty = await fixture();
  empty.host.result = [];
  assert.deepEqual(await preview(empty), {
    status: 'completed',
    normalizedEdit: { textChanges: [], targets: [] },
  });

  const changed = await fixture();
  changed.host.mutateAfterProvider = true;
  assert.deepEqual(await preview(changed), {
    status: 'documentChanged',
    reason: 'content',
    files: ['src/a.ts'],
  });
});

test('snippet, unknown, and overlapping format edits reject the whole preview', async () => {
  const snippet = await fixture();
  snippet.host.result = [{ kind: 'snippet', range: range(0, 2, 0, 3), snippet: 'value' }];
  assert.deepEqual(await preview(snippet), {
    status: 'editConflict',
    reason: 'unsupportedEdit',
    files: ['src/a.ts'],
  });

  const overlap = await fixture();
  overlap.host.result = [
    textEdit(range(0, 2, 0, 4), 'first'),
    textEdit(range(0, 3, 0, 5), 'second'),
  ];
  assert.deepEqual(await preview(overlap), {
    status: 'editConflict',
    reason: 'overlappingEdits',
    files: ['src/a.ts'],
  });
});
