import assert from 'node:assert/strict';
import { Buffer } from 'node:buffer';
import { createHash } from 'node:crypto';
import path from 'node:path';
import test from 'node:test';
import type { Position, Range, TextDocument } from 'vscode';
import {
  createWorkspacePathContext,
  hostPathPlatform,
  sha256Utf16Text,
  simulateNormalizedTextEdits,
  type MutationApplyBridgeRequest,
  type NormalizedTextEdit,
  type NormalizedWorkspaceEdit,
  type RuntimePrimitives,
  type WorkspacePathAccess,
  type WorkspaceRouteIdentity,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  DocumentEpochTracker,
  workspaceBoundaryFingerprint,
} from './workspace-edit-normalizer.js';
import {
  MutationApplyExecutor,
  type MutationApplyHost,
} from './mutation-apply-provider.js';

const workspaceRoot = process.platform === 'win32' ? 'D:/workspace/app' : '/workspace/app';
const sourceFile = path.join(workspaceRoot, 'src', 'sample.ts');
const activeWorkspace: WorkspaceRouteIdentity = {
  workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA' as WorkspaceRouteIdentity['workspaceId'],
  generation: 1,
};

const uri = (fsPath: string) => ({ scheme: 'file', fsPath });
const point = (line: number, character: number) => ({ line, character });

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

interface RebuiltEdit {
  readonly range: { readonly start: Position; readonly end: Position };
  readonly newText: string;
}

interface RebuiltWorkspaceEdit {
  readonly sets: Array<{ readonly uri: ReturnType<typeof uri>; readonly edits: readonly RebuiltEdit[] }>;
}

class FakeApplyHost implements MutationApplyHost {
  readonly documents = new Map<string, FakeDocument>();
  readonly disk = new Map<string, Uint8Array | undefined>();
  applyCalls = 0;
  applyMode: 'success' | 'false' | 'throw' | 'readbackMismatch' = 'success';
  lastWorkspaceEdit: unknown;

  applyEdit(value: unknown): PromiseLike<boolean> {
    this.applyCalls += 1;
    this.lastWorkspaceEdit = value;
    if (this.applyMode === 'throw') return Promise.reject(new Error('apply failed'));
    if (this.applyMode === 'false') return Promise.resolve(false);
    if (this.applyMode === 'readbackMismatch') return Promise.resolve(true);
    const workspaceEdit = value as RebuiltWorkspaceEdit;
    for (const set of workspaceEdit.sets) {
      const document = this.documents.get(set.uri.fsPath);
      if (document === undefined) throw new Error('Missing document.');
      const edits: NormalizedTextEdit[] = set.edits.map((edit, index) => {
        const startOffset = document.offsetAt(edit.range.start);
        const endOffset = document.offsetAt(edit.range.end);
        return {
          range: {
            startLine: edit.range.start.line + 1,
            startColumn: edit.range.start.character + 1,
            endLine: edit.range.end.line + 1,
            endColumn: edit.range.end.character + 1,
          },
          startOffset,
          endOffset,
          oldText: document.text.slice(startOffset, endOffset),
          newText: edit.newText,
          providerOrdinal: index,
        };
      });
      document.text = simulateNormalizedTextEdits(document.text, edits);
      document.version += 1;
    }
    return Promise.resolve(true);
  }

  createRange(value: { readonly start: Position; readonly end: Position }): Range {
    return value as Range;
  }

  createTextEdit(range: { readonly start: Position; readonly end: Position }, newText: string): unknown {
    return { range, newText };
  }

  createWorkspaceEdit(): RebuiltWorkspaceEdit {
    return { sets: [] };
  }

  fileUri(absolutePath: string): unknown {
    return uri(absolutePath);
  }

  openTextDocument(value: unknown): PromiseLike<TextDocument> {
    const document = this.documents.get((value as { readonly fsPath: string }).fsPath);
    return document === undefined
      ? Promise.reject(new Error('Document missing'))
      : Promise.resolve(document as unknown as TextDocument);
  }

  readDiskFile(value: unknown) {
    const bytes = this.disk.get((value as { readonly fsPath: string }).fsPath);
    return Promise.resolve(bytes === undefined
      ? { exists: false as const }
      : { exists: true as const, bytes });
  }

  setTextEdits(workspaceEdit: unknown, value: unknown, edits: readonly unknown[]): void {
    (workspaceEdit as RebuiltWorkspaceEdit).sets.push({
      uri: value as ReturnType<typeof uri>,
      edits: edits as readonly RebuiltEdit[],
    });
  }

  uriString(value: unknown): string {
    return `file://${(value as { readonly fsPath: string }).fsPath.replaceAll('\\', '/')}`;
  }
}

interface RuntimeState {
  readonly primitives: RuntimePrimitives;
  setNow(value: number): void;
}

const runtime = (): RuntimeState => {
  let now = 0;
  return {
    primitives: {
      monotonicNowMs: () => now,
      secureRandomBytes: (length) => new Uint8Array(length),
      sha256Hex: (input) => createHash('sha256').update(input).digest('hex'),
    },
    setNow: (value) => {
      now = value;
    },
  };
};

const attemptId = (index: number): string => {
  const bytes = Buffer.alloc(16);
  bytes.writeUInt32BE(index, 12);
  return `ap_${bytes.toString('base64url')}`;
};

const edit = (
  startOffset: number,
  endOffset: number,
  oldText: string,
  newText: string,
  providerOrdinal = 0,
): NormalizedTextEdit => ({
  range: {
    startLine: 1,
    startColumn: startOffset + 1,
    endLine: 1,
    endColumn: endOffset + 1,
  },
  startOffset,
  endOffset,
  oldText,
  newText,
  providerOrdinal,
});

const fixture = async (text = 'old value') => {
  const state = runtime();
  let escapePath = false;
  const pathAccess: WorkspacePathAccess = {
    entryType: (value) => Promise.resolve(value.endsWith('.ts') ? 'file' : 'directory'),
    realpath: (value) => Promise.resolve(
      escapePath && value.endsWith('sample.ts')
        ? path.join(path.dirname(workspaceRoot), 'outside.ts')
        : value,
    ),
  };
  const context = await createWorkspacePathContext([{
    name: 'app',
    uriScheme: 'file',
    lexicalAbsolutePath: workspaceRoot,
  }], hostPathPlatform, pathAccess, state.primitives);
  const host = new FakeApplyHost();
  const document = new FakeDocument(sourceFile, text, 7);
  host.documents.set(sourceFile, document);
  host.disk.set(sourceFile, new TextEncoder().encode(text));
  const tracker = new DocumentEpochTracker();
  const replacedLength = Math.min(3, text.length);
  const normalizedEdits = [edit(0, replacedLength, text.slice(0, replacedLength), 'new')];
  const expected = simulateNormalizedTextEdits(text, normalizedEdits);
  const normalizedEdit: NormalizedWorkspaceEdit = {
    textChanges: [{ kind: 'text', file: 'src/sample.ts', edits: normalizedEdits }],
    targets: [{
      file: 'src/sample.ts',
      internalUri: host.uriString(uri(sourceFile)),
      rootAlias: context.roots[0]!.alias,
      boundaryFingerprint: workspaceBoundaryFingerprint(
        context,
        context.roots[0]!.alias,
        state.primitives,
      ),
      documentEpoch: tracker.epochFor(document as unknown as TextDocument),
      documentVersion: document.version,
      memoryContentSha256: sha256Utf16Text(text, state.primitives),
      eol: 'lf',
      encoding: 'utf16-code-units',
      diskExists: true,
      diskByteSha256: state.primitives.sha256Hex(new TextEncoder().encode(text)),
      expectedPostContentSha256: sha256Utf16Text(expected, state.primitives),
    }],
  };
  const request: MutationApplyBridgeRequest = {
    workspace: activeWorkspace,
    applyAttemptId: attemptId(1),
    normalizedEdit,
  };
  const executor = new MutationApplyExecutor(host, {
    epochTracker: tracker,
    pathAccess,
    primitives: state.primitives,
  });
  return {
    context,
    document,
    executor,
    host,
    request,
    state,
    tracker,
    setEscapePath: (value: boolean) => {
      escapePath = value;
    },
  };
};

const signal = (): AbortSignal => new AbortController().signal;

test('mutation apply rebuilds once, reads back all targets, and deduplicates attempts', async () => {
  const state = await fixture();
  const first = await state.executor.apply(state.context, activeWorkspace, state.request, signal());
  assert.deepEqual(first, { status: 'applied', changedFiles: ['src/sample.ts'] });
  assert.equal(state.document.text, 'new value');
  assert.equal(state.host.applyCalls, 1);
  assert.notEqual(state.host.lastWorkspaceEdit, state.request.normalizedEdit);

  const duplicate = await state.executor.apply(state.context, activeWorkspace, state.request, signal());
  assert.deepEqual(duplicate, first);
  assert.equal(state.host.applyCalls, 1);
  assert.equal(state.executor.attemptTombstoneCount(), 1);
});

test('same-epoch version/content/disk changes fail before apply with bounded logical files', async () => {
  const version = await fixture();
  version.document.version += 1;
  assert.deepEqual(
    await version.executor.apply(version.context, activeWorkspace, version.request, signal()),
    { status: 'documentChanged', reason: 'version', files: ['src/sample.ts'] },
  );
  assert.equal(version.host.applyCalls, 0);

  const content = await fixture();
  content.document.text = 'changed value';
  assert.deepEqual(
    await content.executor.apply(content.context, activeWorkspace, content.request, signal()),
    { status: 'documentChanged', reason: 'content', files: ['src/sample.ts'] },
  );
  assert.equal(content.host.applyCalls, 0);

  const disk = await fixture();
  disk.host.disk.delete(sourceFile);
  assert.deepEqual(
    await disk.executor.apply(disk.context, activeWorkspace, disk.request, signal()),
    { status: 'documentChanged', reason: 'existence', files: ['src/sample.ts'] },
  );
  assert.equal(disk.host.applyCalls, 0);
});

test('a reopened document epoch may change only when memory and disk snapshots remain equivalent', async () => {
  const state = await fixture();
  const reopened = new FakeDocument(sourceFile, 'old value', 99);
  state.host.documents.set(sourceFile, reopened);
  const response = await state.executor.apply(state.context, activeWorkspace, state.request, signal());
  assert.deepEqual(response, { status: 'applied', changedFiles: ['src/sample.ts'] });
  assert.equal(reopened.text, 'new value');
  assert.equal(state.host.applyCalls, 1);
});

test('one stale target in a multi-file edit prevents the single apply call and all writes', async () => {
  const state = await fixture();
  const otherFile = path.join(workspaceRoot, 'src', 'other.ts');
  const otherDocument = new FakeDocument(otherFile, 'old other', 4);
  state.host.documents.set(otherFile, otherDocument);
  state.host.disk.set(otherFile, new TextEncoder().encode('old other'));
  const otherEdits = [edit(0, 3, 'old', 'new')];
  const otherExpected = simulateNormalizedTextEdits('old other', otherEdits);
  const otherSnapshot = {
    file: 'src/other.ts',
    internalUri: state.host.uriString(uri(otherFile)),
    rootAlias: state.context.roots[0]!.alias,
    boundaryFingerprint: workspaceBoundaryFingerprint(
      state.context,
      state.context.roots[0]!.alias,
      state.state.primitives,
    ),
    documentEpoch: state.tracker.epochFor(otherDocument as unknown as TextDocument),
    documentVersion: otherDocument.version,
    memoryContentSha256: sha256Utf16Text('old other', state.state.primitives),
    eol: 'lf' as const,
    encoding: 'utf16-code-units' as const,
    diskExists: true as const,
    diskByteSha256: state.state.primitives.sha256Hex(new TextEncoder().encode('old other')),
    expectedPostContentSha256: sha256Utf16Text(otherExpected, state.state.primitives),
  };
  const mutable = state.request.normalizedEdit as unknown as {
    textChanges: Array<NormalizedWorkspaceEdit['textChanges'][number]>;
    targets: Array<NormalizedWorkspaceEdit['targets'][number]>;
  };
  mutable.textChanges.push({ kind: 'text', file: 'src/other.ts', edits: otherEdits });
  mutable.targets.push(otherSnapshot);
  otherDocument.version += 1;

  const response = await state.executor.apply(state.context, activeWorkspace, state.request, signal());
  assert.deepEqual(response, {
    status: 'documentChanged',
    reason: 'version',
    files: ['src/other.ts'],
  });
  assert.equal(state.host.applyCalls, 0);
  assert.equal(state.document.text, 'old value');
  assert.equal(otherDocument.text, 'old other');
});

test('workspace boundary, range clamp, overlap, and no-op integrity failures never call applyEdit', async () => {
  const escaped = await fixture();
  escaped.setEscapePath(true);
  assert.deepEqual(
    await escaped.executor.apply(escaped.context, activeWorkspace, escaped.request, signal()),
    { status: 'pathOutsideWorkspace' },
  );
  assert.equal(escaped.host.applyCalls, 0);

  const changedRoot = await fixture();
  (changedRoot.request.normalizedEdit.targets[0] as { boundaryFingerprint: string })
    .boundaryFingerprint = 'f'.repeat(64);
  assert.deepEqual(
    await changedRoot.executor.apply(
      changedRoot.context,
      activeWorkspace,
      changedRoot.request,
      signal(),
    ),
    { status: 'documentChanged', reason: 'workspace', files: ['src/sample.ts'] },
  );
  assert.equal(changedRoot.host.applyCalls, 0);

  const clamped = await fixture();
  const clampedEdit = clamped.request.normalizedEdit.textChanges[0]!.edits[0]!;
  (clampedEdit.range as { endColumn: number }).endColumn = 999;
  assert.deepEqual(
    await clamped.executor.apply(clamped.context, activeWorkspace, clamped.request, signal()),
    { status: 'editConflict', reason: 'rangeOutOfBounds', files: ['src/sample.ts'] },
  );
  assert.equal(clamped.host.applyCalls, 0);

  const overlapping = await fixture();
  const change = overlapping.request.normalizedEdit.textChanges[0]!;
  (change as unknown as { edits: NormalizedTextEdit[] }).edits = [
    edit(0, 3, 'old', 'new', 0),
    edit(1, 2, 'l', 'x', 1),
  ];
  assert.deepEqual(
    await overlapping.executor.apply(overlapping.context, activeWorkspace, overlapping.request, signal()),
    { status: 'editConflict', reason: 'overlappingEdits', files: ['src/sample.ts'] },
  );
  assert.equal(overlapping.host.applyCalls, 0);

  const noOp = await fixture();
  const target = noOp.request.normalizedEdit.targets[0]!;
  (target as { expectedPostContentSha256: string }).expectedPostContentSha256 =
    target.memoryContentSha256;
  assert.deepEqual(
    await noOp.executor.apply(noOp.context, activeWorkspace, noOp.request, signal()),
    { status: 'editConflict', reason: 'ambiguousOperationOrder', files: ['src/sample.ts'] },
  );
  assert.equal(noOp.host.applyCalls, 0);
});

test('apply false, apply exception, and readback mismatch remain whole-operation failures', async () => {
  const notApplied = await fixture();
  notApplied.host.applyMode = 'false';
  assert.deepEqual(
    await notApplied.executor.apply(notApplied.context, activeWorkspace, notApplied.request, signal()),
    { status: 'applyFailed', stage: 'apply', outcome: 'notApplied' },
  );

  const unknown = await fixture();
  unknown.host.applyMode = 'throw';
  assert.deepEqual(
    await unknown.executor.apply(unknown.context, activeWorkspace, unknown.request, signal()),
    { status: 'applyFailed', stage: 'apply', outcome: 'unknown' },
  );

  const mismatch = await fixture();
  mismatch.host.applyMode = 'readbackMismatch';
  assert.deepEqual(
    await mismatch.executor.apply(mismatch.context, activeWorkspace, mismatch.request, signal()),
    { status: 'applyFailed', stage: 'readback', outcome: 'postconditionFailed' },
  );
});

test('same-point inserts preserve provider order through rebuilt apply', async () => {
  const state = await fixture('x');
  const edits = [edit(0, 0, '', 'first-', 4), edit(0, 0, '', 'second-', 5)];
  const target = state.request.normalizedEdit.targets[0]!;
  (state.request.normalizedEdit.textChanges[0] as unknown as { edits: NormalizedTextEdit[] }).edits = edits;
  (target as { memoryContentSha256: string }).memoryContentSha256 =
    sha256Utf16Text('x', state.state.primitives);
  (target as { diskByteSha256: string }).diskByteSha256 =
    state.state.primitives.sha256Hex(new TextEncoder().encode('x'));
  (target as { expectedPostContentSha256: string }).expectedPostContentSha256 =
    sha256Utf16Text('first-second-x', state.state.primitives);
  const response = await state.executor.apply(state.context, activeWorkspace, state.request, signal());
  assert.deepEqual(response, { status: 'applied', changedFiles: ['src/sample.ts'] });
  assert.equal(state.document.text, 'first-second-x');
});

test('apply attempt tombstones are capped per workspace and expire on exact monotonic TTL', async () => {
  const state = await fixture();
  for (let index = 1; index <= 257; index += 1) {
    const request = { ...state.request, applyAttemptId: attemptId(index) };
    await state.executor.apply(state.context, activeWorkspace, request, signal());
  }
  assert.equal(state.executor.attemptTombstoneCount(), 256);
  state.state.setNow(599_999);
  assert.equal(state.executor.attemptTombstoneCount(), 256);
  state.state.setNow(600_000);
  assert.equal(state.executor.attemptTombstoneCount(), 0);
});
