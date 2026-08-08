import assert from 'node:assert/strict';
import path from 'node:path';
import test from 'node:test';
import type { Position, Range, TextDocument, TextEdit } from 'vscode';
import {
  createWorkspacePathContext,
  hostPathPlatform,
  publicTextChangesFromNormalized,
  sha256Utf16Text,
  systemRuntimePrimitives,
  type WorkspacePathAccess,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  DocumentEpochTracker,
  WorkspaceEditNormalizationError,
  WorkspaceEditNormalizer,
  rebuildTextOnlyWorkspaceEdit,
  type DiskFileSnapshot,
  type ProviderWorkspaceEdit,
  type WorkspaceEditNormalizerHost,
} from './workspace-edit-normalizer.js';

const workspaceRoot = process.platform === 'win32' ? 'D:/workspace/app' : '/workspace/app';
const sourceFile = path.join(workspaceRoot, 'src', 'sample.ts');

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
  eol: number;
  version: number;
  text: string;

  constructor(fsPath: string, text: string, version = 1) {
    this.uri = uri(fsPath);
    this.text = text;
    this.version = version;
    this.eol = text.includes('\r\n') ? 2 : 1;
  }

  getText(): string {
    return this.text;
  }

  validateRange(value: Range): Range {
    const lines = lineTable(this.text);
    const clamp = (candidate: Position) => {
      const line = Math.max(0, Math.min(candidate.line, lines.length - 1));
      const current = lines[line];
      return point(line, Math.max(0, Math.min(candidate.character, current?.length ?? 0)));
    };
    return { start: clamp(value.start), end: clamp(value.end) } as Range;
  }

  offsetAt(value: Position): number {
    const validated = this.validateRange({ start: value, end: value } as Range).start;
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

class FakeNormalizerHost implements WorkspaceEditNormalizerHost {
  readonly documents = new Map<string, FakeDocument>();
  readonly disk = new Map<string, Uint8Array | undefined>();
  onReadDisk: (() => void) | undefined;

  createRange(value: ReturnType<typeof range>): Range {
    return value as Range;
  }

  fileUri(absolutePath: string): unknown {
    return uri(absolutePath);
  }

  isTextEdit(value: unknown): value is TextEdit {
    return value !== null && typeof value === 'object' &&
      (value as { readonly kind?: unknown }).kind === 'text';
  }

  openTextDocument(value: unknown): PromiseLike<TextDocument> {
    const fsPath = (value as { readonly fsPath: string }).fsPath;
    const document = this.documents.get(fsPath);
    if (document === undefined) throw new Error('Missing fake document.');
    return Promise.resolve(document as unknown as TextDocument);
  }

  readDiskFile(value: unknown): PromiseLike<DiskFileSnapshot> {
    this.onReadDisk?.();
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

const context = () => createWorkspacePathContext([{
  name: 'app',
  uriScheme: 'file',
  lexicalAbsolutePath: workspaceRoot,
}], hostPathPlatform, pathAccess, systemRuntimePrimitives);

const providerEdit = (
  entries: readonly (readonly [unknown, readonly unknown[]])[],
  size = entries.length,
): ProviderWorkspaceEdit => ({ size, entries: () => entries });

test('normalizer copies public text edits, preserves UTF-16 insertion order, and captures snapshots', async () => {
  const host = new FakeNormalizerHost();
  const text = 'A😀e\u0301\r\nnext\r\n';
  const document = new FakeDocument(sourceFile, text, 7);
  host.documents.set(sourceFile, document);
  host.disk.set(sourceFile, new TextEncoder().encode('disk copy\r\n'));
  const firstInsert = textEdit(range(1, 0, 1, 0), 'first-');
  const replaceEmoji = textEdit(range(0, 1, 0, 3), 'X');
  const secondInsert = textEdit(range(1, 0, 1, 0), 'second-');
  const raw = providerEdit([[uri(sourceFile), [firstInsert, replaceEmoji, secondInsert]]]);
  const normalizer = new WorkspaceEditNormalizer(host, { pathAccess });
  const pending = normalizer.normalize(await context(), raw);
  firstInsert.newText = 'mutated-after-capture';
  const normalized = await pending;

  assert.equal(normalized.textChanges.length, 1);
  assert.deepEqual(
    normalized.textChanges[0]?.edits.map((candidate) => [candidate.oldText, candidate.newText]),
    [['😀', 'X'], ['', 'first-'], ['', 'second-']],
  );
  assert.deepEqual(normalized.textChanges[0]?.edits[0]?.range, {
    startLine: 1,
    startColumn: 2,
    endLine: 1,
    endColumn: 4,
  });
  const target = normalized.targets[0];
  assert.equal(target?.documentVersion, 7);
  assert.equal(target?.documentEpoch, 1);
  assert.equal(target?.eol, 'crlf');
  assert.equal(target?.memoryContentSha256, sha256Utf16Text(text));
  assert.equal(
    target?.expectedPostContentSha256,
    sha256Utf16Text('AXe\u0301\r\nfirst-second-next\r\n'),
  );
  assert.equal(target?.diskExists, true);
  assert.equal(target?.internalUri.startsWith('file://'), true);

  const projected = publicTextChangesFromNormalized(normalized);
  const publicJson = JSON.stringify(projected);
  for (const forbidden of [
    'providerOrdinal', 'startOffset', 'targets', 'internalUri', 'Sha256', 'documentEpoch',
  ]) {
    assert.equal(publicJson.includes(forbidden), false);
  }
});

test('normalizer rejects resources, snippets, clamped ranges, overlaps, and duplicate logical targets', async () => {
  const host = new FakeNormalizerHost();
  host.documents.set(sourceFile, new FakeDocument(sourceFile, 'abcdef'));
  host.disk.set(sourceFile, new TextEncoder().encode('abcdef'));
  const normalizer = new WorkspaceEditNormalizer(host, { pathAccess });
  const workspace = await context();

  await assert.rejects(
    normalizer.normalize(workspace, providerEdit([[uri(sourceFile), [textEdit(range(0, 0, 0, 0), 'x')]]], 2)),
    (error: unknown) => error instanceof WorkspaceEditNormalizationError && error.reason === 'unsupportedEdit',
  );
  await assert.rejects(
    normalizer.normalize(workspace, providerEdit([[uri(sourceFile), [{
      kind: 'snippet', range: range(0, 0, 0, 0), snippet: '${1:x}',
    }]]])),
    (error: unknown) => error instanceof WorkspaceEditNormalizationError && error.reason === 'unsupportedEdit',
  );
  await assert.rejects(
    normalizer.normalize(workspace, providerEdit([[
      uri(sourceFile), [textEdit(range(0, 0, 0, 99), 'x')],
    ]])),
    (error: unknown) => error instanceof WorkspaceEditNormalizationError && error.reason === 'invalidRange',
  );
  await assert.rejects(
    normalizer.normalize(workspace, providerEdit([[uri(sourceFile), [
      textEdit(range(0, 1, 0, 4), 'x'),
      textEdit(range(0, 2, 0, 2), 'inside'),
    ]]])),
    (error: unknown) => error instanceof WorkspaceEditNormalizationError && error.reason === 'overlappingEdits',
  );
  await assert.rejects(
    normalizer.normalize(workspace, providerEdit([
      [uri(sourceFile), [textEdit(range(0, 0, 0, 0), 'a')]],
      [uri(sourceFile), [textEdit(range(0, 0, 0, 0), 'b')]],
    ])),
    (error: unknown) => error instanceof WorkspaceEditNormalizationError && error.reason === 'duplicateTarget',
  );
});

test('empty edits stay empty and multi-file targets sort without inventing disk state', async () => {
  const host = new FakeNormalizerHost();
  const alphaFile = path.join(workspaceRoot, 'src', 'alpha.ts');
  const zetaFile = path.join(workspaceRoot, 'src', 'zeta.ts');
  host.documents.set(alphaFile, new FakeDocument(alphaFile, 'alpha'));
  host.documents.set(zetaFile, new FakeDocument(zetaFile, 'zeta'));
  host.disk.set(zetaFile, new TextEncoder().encode('zeta'));
  const normalizer = new WorkspaceEditNormalizer(host, { pathAccess });
  const workspace = await context();

  assert.deepEqual(await normalizer.normalize(workspace, providerEdit([])), {
    textChanges: [],
    targets: [],
  });
  assert.deepEqual(await normalizer.normalize(workspace, providerEdit([[
    uri(alphaFile), [textEdit(range(0, 0, 0, 5), 'alpha')],
  ]])), {
    textChanges: [],
    targets: [],
  });
  const normalized = await normalizer.normalize(workspace, providerEdit([
    [uri(zetaFile), [textEdit(range(0, 0, 0, 0), 'Z')]],
    [uri(alphaFile), [textEdit(range(0, 0, 0, 0), 'A')]],
  ]));
  assert.deepEqual(normalized.textChanges.map(({ file }) => file), [
    'src/alpha.ts',
    'src/zeta.ts',
  ]);
  assert.deepEqual(normalized.targets.map(({ file, diskExists }) => [file, diskExists]), [
    ['src/alpha.ts', false],
    ['src/zeta.ts', true],
  ]);
});

test('document epochs are stable per lifecycle and capture rejects concurrent document changes', async () => {
  const tracker = new DocumentEpochTracker();
  const first = new FakeDocument(sourceFile, 'abc');
  const reopened = new FakeDocument(sourceFile, 'abc');
  assert.equal(tracker.epochFor(first as unknown as TextDocument), 1);
  assert.equal(tracker.epochFor(first as unknown as TextDocument), 1);
  assert.equal(tracker.epochFor(reopened as unknown as TextDocument), 2);

  const host = new FakeNormalizerHost();
  host.documents.set(sourceFile, first);
  host.disk.set(sourceFile, new TextEncoder().encode('abc'));
  host.onReadDisk = () => {
    first.version += 1;
    first.text = 'changed';
  };
  const normalizer = new WorkspaceEditNormalizer(host, { epochTracker: tracker, pathAccess });
  await assert.rejects(
    normalizer.normalize(await context(), providerEdit([[
      uri(sourceFile), [textEdit(range(0, 0, 0, 1), 'x')],
    ]])),
    (error: unknown) =>
      error instanceof WorkspaceEditNormalizationError && error.reason === 'documentChangedDuringCapture',
  );
});

test('rebuild creates a new text-only object from normalized logical changes', async () => {
  const host = new FakeNormalizerHost();
  host.documents.set(sourceFile, new FakeDocument(sourceFile, 'abc'));
  host.disk.set(sourceFile, new TextEncoder().encode('abc'));
  const workspace = await context();
  const provider = providerEdit([[uri(sourceFile), [
    textEdit(range(0, 1, 0, 1), 'first'),
    textEdit(range(0, 1, 0, 1), 'second'),
  ]]]);
  const normalized = await new WorkspaceEditNormalizer(host, { pathAccess }).normalize(workspace, provider);
  const rebuilt = await rebuildTextOnlyWorkspaceEdit(workspace, normalized, {
    createWorkspaceEdit: () => ({ sets: [] as unknown[] }),
    fileUri: (absolutePath) => ({ absolutePath }),
    createTextEdit: (rangeValue, newText) => ({ range: rangeValue, newText }),
    setTextEdits: (workspaceEdit, rebuiltUri, edits) => {
      workspaceEdit.sets.push({ uri: rebuiltUri, edits });
    },
  }, pathAccess);

  assert.notEqual(rebuilt, provider);
  assert.deepEqual(
    (rebuilt.sets[0] as { readonly edits: readonly { readonly newText: string }[] }).edits
      .map((candidate) => candidate.newText),
    ['first', 'second'],
  );
  assert.equal(JSON.stringify(rebuilt).includes('oldText'), false);
});
