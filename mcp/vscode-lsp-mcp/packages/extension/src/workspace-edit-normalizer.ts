import type {
  Range as VscodeRange,
  TextDocument,
  TextEdit as VscodeTextEdit,
  Uri,
  WorkspaceEdit,
} from 'vscode';
import {
  MEMORY_TEXT_ENCODING,
  TextEditInvariantError,
  logicalPathFromProviderLocation,
  resolveLogicalPath,
  sha256Utf16Text,
  simulateNormalizedTextEdits,
  sortAndValidateNormalizedTextEdits,
  systemRuntimePrimitives,
  systemWorkspacePathAccess,
  type NormalizedTextChange,
  type NormalizedTextEdit,
  type NormalizedWorkspaceEdit,
  type RuntimePrimitives,
  type TextDocumentSnapshot,
  type WorkspacePathAccess,
  type WorkspacePathContext,
} from '@simplechat/vscode-lsp-mcp-protocol';

interface ProviderUriLike {
  readonly scheme: string;
  readonly fsPath: string;
}

interface ProviderPointValue {
  readonly line: number;
  readonly character: number;
}

interface ProviderRangeValue {
  readonly start: ProviderPointValue;
  readonly end: ProviderPointValue;
}

interface CapturedProviderTextEdit {
  readonly range: ProviderRangeValue;
  readonly newText: string;
  readonly providerOrdinal: number;
}

interface CapturedProviderEntry {
  readonly location: ProviderUriLike;
  readonly uri: unknown;
  readonly edits: readonly CapturedProviderTextEdit[];
}

export interface ProviderWorkspaceEdit {
  readonly size: number;
  entries(): unknown;
}

export type DiskFileSnapshot =
  | { readonly exists: true; readonly bytes: Uint8Array }
  | { readonly exists: false };

export interface WorkspaceEditNormalizerHost {
  createRange(range: ProviderRangeValue): VscodeRange;
  fileUri(absolutePath: string): unknown;
  isTextEdit(value: unknown): value is VscodeTextEdit;
  openTextDocument(uri: unknown): PromiseLike<TextDocument>;
  readDiskFile(uri: unknown): PromiseLike<DiskFileSnapshot>;
  uriString(uri: unknown): string;
}

export type WorkspaceEditNormalizationErrorReason =
  | 'documentChangedDuringCapture'
  | 'documentMismatch'
  | 'duplicateTarget'
  | 'invalidDocument'
  | 'invalidRange'
  | 'overlappingEdits'
  | 'unsupportedEdit';

export class WorkspaceEditNormalizationError extends Error {
  readonly reason: WorkspaceEditNormalizationErrorReason;

  constructor(reason: WorkspaceEditNormalizationErrorReason, message: string) {
    super(message);
    this.name = 'WorkspaceEditNormalizationError';
    this.reason = reason;
  }
}

export class DocumentEpochTracker {
  readonly #epochs = new WeakMap<object, number>();
  #nextEpoch = 1;

  epochFor(document: TextDocument): number {
    const existing = this.#epochs.get(document);
    if (existing !== undefined) return existing;
    if (!Number.isSafeInteger(this.#nextEpoch) || this.#nextEpoch < 1) {
      throw new WorkspaceEditNormalizationError('invalidDocument', 'Document epoch capacity was exhausted.');
    }
    const epoch = this.#nextEpoch;
    this.#nextEpoch += 1;
    this.#epochs.set(document, epoch);
    return epoch;
  }
}

const asRecord = (value: unknown): Record<string, unknown> | undefined =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;

const pointFromValue = (value: unknown): ProviderPointValue | undefined => {
  const point = asRecord(value);
  return point !== undefined && Number.isSafeInteger(point.line) && (point.line as number) >= 0 &&
      (point.line as number) < Number.MAX_SAFE_INTEGER &&
      Number.isSafeInteger(point.character) && (point.character as number) >= 0 &&
      (point.character as number) < Number.MAX_SAFE_INTEGER
    ? { line: point.line as number, character: point.character as number }
    : undefined;
};

const rangeFromValue = (value: unknown): ProviderRangeValue | undefined => {
  const range = asRecord(value);
  const start = pointFromValue(range?.start);
  const end = pointFromValue(range?.end);
  return start === undefined || end === undefined ? undefined : { start, end };
};

const uriFromValue = (value: unknown): ProviderUriLike | undefined => {
  const uri = asRecord(value);
  return uri !== undefined && typeof uri.scheme === 'string' && typeof uri.fsPath === 'string' &&
      uri.fsPath.length > 0
    ? { scheme: uri.scheme, fsPath: uri.fsPath }
    : undefined;
};

const samePoint = (left: ProviderPointValue, right: ProviderPointValue): boolean =>
  left.line === right.line && left.character === right.character;

const sameRange = (left: ProviderRangeValue, right: VscodeRange): boolean =>
  samePoint(left.start, right.start) && samePoint(left.end, right.end);

const compareTextChanges = (left: NormalizedTextChange, right: NormalizedTextChange): number =>
  left.file < right.file ? -1 : left.file > right.file ? 1 : 0;

const freezeNormalizedEdit = (edit: NormalizedTextEdit): NormalizedTextEdit => Object.freeze({
  ...edit,
  range: Object.freeze({ ...edit.range }),
});

export const eolFromDocument = (document: TextDocument): 'lf' | 'crlf' => {
  if (document.eol === 1) return 'lf';
  if (document.eol === 2) return 'crlf';
  throw new WorkspaceEditNormalizationError('invalidDocument', 'Document has an unsupported end-of-line mode.');
};

export const workspaceBoundaryFingerprint = (
  context: WorkspacePathContext,
  rootAlias: string,
  primitives: RuntimePrimitives = systemRuntimePrimitives,
): string => {
  const root = context.roots.find((candidate) => candidate.alias === rootAlias);
  if (root === undefined) {
    throw new WorkspaceEditNormalizationError('documentMismatch', 'Workspace root identity was lost.');
  }
  return sha256Utf16Text([
    context.platform,
    root.alias,
    root.lexicalComparisonKey,
    root.canonicalComparisonKey,
  ].join('\u0000'), primitives);
};

const captureProviderEntries = (
  providerEdit: ProviderWorkspaceEdit,
  host: WorkspaceEditNormalizerHost,
): readonly CapturedProviderEntry[] => {
  const sizeBefore = providerEdit.size;
  if (!Number.isSafeInteger(sizeBefore) || sizeBefore < 0) {
    throw new WorkspaceEditNormalizationError('unsupportedEdit', 'WorkspaceEdit size is invalid.');
  }
  const rawEntries = providerEdit.entries();
  const sizeAfter = providerEdit.size;
  if (!Array.isArray(rawEntries) || sizeAfter !== sizeBefore || rawEntries.length !== sizeBefore) {
    throw new WorkspaceEditNormalizationError(
      'unsupportedEdit',
      'WorkspaceEdit contains non-text resources or changed while being captured.',
    );
  }
  let providerOrdinal = 0;
  const entries: CapturedProviderEntry[] = [];
  for (const rawEntry of rawEntries) {
    if (!Array.isArray(rawEntry) || rawEntry.length !== 2 || !Array.isArray(rawEntry[1]) ||
        rawEntry[1].length === 0) {
      throw new WorkspaceEditNormalizationError('unsupportedEdit', 'WorkspaceEdit entry is not a text edit list.');
    }
    const location = uriFromValue(rawEntry[0]);
    if (location === undefined || location.scheme !== 'file') {
      throw new WorkspaceEditNormalizationError('unsupportedEdit', 'WorkspaceEdit target is not a local file URI.');
    }
    const edits: CapturedProviderTextEdit[] = [];
    for (const rawEdit of rawEntry[1]) {
      if (!host.isTextEdit(rawEdit)) {
        throw new WorkspaceEditNormalizationError(
          'unsupportedEdit',
          'WorkspaceEdit contains a snippet or unknown edit type.',
        );
      }
      const editRecord = asRecord(rawEdit);
      const range = rangeFromValue(editRecord?.range);
      if (range === undefined || typeof editRecord?.newText !== 'string') {
        throw new WorkspaceEditNormalizationError('unsupportedEdit', 'TextEdit fields are malformed.');
      }
      edits.push(Object.freeze({ range, newText: editRecord.newText, providerOrdinal }));
      providerOrdinal += 1;
    }
    entries.push(Object.freeze({
      location: Object.freeze(location),
      uri: host.fileUri(location.fsPath),
      edits: Object.freeze(edits),
    }));
  }
  return Object.freeze(entries);
};

export interface WorkspaceEditNormalizerOptions {
  readonly epochTracker?: DocumentEpochTracker;
  readonly pathAccess?: WorkspacePathAccess;
  readonly primitives?: RuntimePrimitives;
}

export interface CapturedDocumentSnapshot {
  readonly document: TextDocument;
  readonly snapshot: TextDocumentSnapshot;
  readonly text: string;
  readonly uri: unknown;
}

export class WorkspaceEditNormalizer {
  readonly #host: WorkspaceEditNormalizerHost;
  readonly #epochTracker: DocumentEpochTracker;
  readonly #pathAccess: WorkspacePathAccess;
  readonly #primitives: RuntimePrimitives;

  constructor(host: WorkspaceEditNormalizerHost, options: WorkspaceEditNormalizerOptions = {}) {
    this.#host = host;
    this.#epochTracker = options.epochTracker ?? new DocumentEpochTracker();
    this.#pathAccess = options.pathAccess ?? systemWorkspacePathAccess;
    this.#primitives = options.primitives ?? systemRuntimePrimitives;
  }

  async captureDocument(
    context: WorkspacePathContext,
    logicalFile: string,
  ): Promise<CapturedDocumentSnapshot> {
    const resolved = await resolveLogicalPath(context, logicalFile, this.#pathAccess);
    const uri = this.#host.fileUri(resolved.lexicalAbsolutePath);
    const document = await this.#host.openTextDocument(uri);
    const documentLocation = uriFromValue(document.uri);
    if (documentLocation === undefined || documentLocation.scheme !== 'file') {
      throw new WorkspaceEditNormalizationError('documentMismatch', 'Opened document is not a local file.');
    }
    const documentPath = await logicalPathFromProviderLocation(context, {
      uriScheme: documentLocation.scheme,
      lexicalAbsolutePath: documentLocation.fsPath,
    }, this.#pathAccess);
    if (documentPath.logicalPath !== resolved.logicalPath ||
        documentPath.rootAlias !== resolved.root.alias) {
      throw new WorkspaceEditNormalizationError(
        'documentMismatch',
        'Opened document does not match the requested logical file.',
      );
    }
    if (!Number.isSafeInteger(document.version) || document.version < 0) {
      throw new WorkspaceEditNormalizationError('invalidDocument', 'Document version is invalid.');
    }
    const documentVersion = document.version;
    const documentEpoch = this.#epochTracker.epochFor(document);
    const text = document.getText();
    const eol = eolFromDocument(document);
    const disk = await this.#host.readDiskFile(document.uri);
    if (document.version !== documentVersion || document.getText() !== text ||
        eolFromDocument(document) !== eol) {
      throw new WorkspaceEditNormalizationError(
        'documentChangedDuringCapture',
        'Document changed while its source snapshot was being captured.',
      );
    }
    const memoryContentSha256 = sha256Utf16Text(text, this.#primitives);
    const base = {
      file: resolved.logicalPath,
      internalUri: this.#host.uriString(document.uri),
      rootAlias: resolved.root.alias,
      boundaryFingerprint: workspaceBoundaryFingerprint(
        context,
        resolved.root.alias,
        this.#primitives,
      ),
      documentEpoch,
      documentVersion,
      memoryContentSha256,
      eol,
      encoding: MEMORY_TEXT_ENCODING,
      expectedPostContentSha256: memoryContentSha256,
    } as const;
    const snapshot: TextDocumentSnapshot = disk.exists
      ? Object.freeze({
          ...base,
          diskExists: true,
          diskByteSha256: this.#primitives.sha256Hex(new Uint8Array(disk.bytes)),
        })
      : Object.freeze({ ...base, diskExists: false });
    return Object.freeze({ document, snapshot, text, uri: document.uri });
  }

  async #normalizeEntry(
    context: WorkspacePathContext,
    entry: CapturedProviderEntry,
  ): Promise<{
    readonly change: NormalizedTextChange;
    readonly target: TextDocumentSnapshot;
  } | undefined> {
    const providerPath = await logicalPathFromProviderLocation(context, {
      uriScheme: entry.location.scheme,
      lexicalAbsolutePath: entry.location.fsPath,
    }, this.#pathAccess);
    const document = await this.#host.openTextDocument(entry.uri);
    const documentLocation = uriFromValue(document.uri);
    if (documentLocation === undefined || documentLocation.scheme !== 'file') {
      throw new WorkspaceEditNormalizationError('documentMismatch', 'Opened document is not a local file.');
    }
    const documentPath = await logicalPathFromProviderLocation(context, {
      uriScheme: documentLocation.scheme,
      lexicalAbsolutePath: documentLocation.fsPath,
    }, this.#pathAccess);
    if (documentPath.logicalPath !== providerPath.logicalPath ||
        documentPath.rootAlias !== providerPath.rootAlias) {
      throw new WorkspaceEditNormalizationError(
        'documentMismatch',
        'Opened document does not match the WorkspaceEdit target.',
      );
    }
    if (!Number.isSafeInteger(document.version) || document.version < 0) {
      throw new WorkspaceEditNormalizationError('invalidDocument', 'Document version is invalid.');
    }
    const documentVersion = document.version;
    const documentEpoch = this.#epochTracker.epochFor(document);
    const text = document.getText();
    const eol = eolFromDocument(document);
    const normalizedEdits: NormalizedTextEdit[] = [];
    for (const captured of entry.edits) {
      const vscodeRange = this.#host.createRange(captured.range);
      let validated: VscodeRange;
      try {
        validated = document.validateRange(vscodeRange);
      } catch {
        throw new WorkspaceEditNormalizationError('invalidRange', 'TextEdit range validation failed.');
      }
      if (!sameRange(captured.range, validated)) {
        throw new WorkspaceEditNormalizationError(
          'invalidRange',
          'TextEdit range would be clamped by VS Code.',
        );
      }
      const startOffset = document.offsetAt(validated.start);
      const endOffset = document.offsetAt(validated.end);
      if (!samePoint(captured.range.start, document.positionAt(startOffset)) ||
          !samePoint(captured.range.end, document.positionAt(endOffset))) {
        throw new WorkspaceEditNormalizationError(
          'invalidRange',
          'TextEdit range does not round-trip on its document snapshot.',
        );
      }
      normalizedEdits.push(freezeNormalizedEdit({
        range: {
          startLine: captured.range.start.line + 1,
          startColumn: captured.range.start.character + 1,
          endLine: captured.range.end.line + 1,
          endColumn: captured.range.end.character + 1,
        },
        oldText: text.slice(startOffset, endOffset),
        newText: captured.newText,
        startOffset,
        endOffset,
        providerOrdinal: captured.providerOrdinal,
      }));
    }

    let sortedEdits: readonly NormalizedTextEdit[];
    let expectedPostContent: string;
    try {
      sortedEdits = sortAndValidateNormalizedTextEdits(text, normalizedEdits);
      expectedPostContent = simulateNormalizedTextEdits(text, sortedEdits);
    } catch (error) {
      if (error instanceof TextEditInvariantError) {
        throw new WorkspaceEditNormalizationError(
          error.reason === 'overlappingEdits' ? 'overlappingEdits' : 'invalidRange',
          error.message,
        );
      }
      throw error;
    }

    if (expectedPostContent === text) return undefined;

    const disk = await this.#host.readDiskFile(entry.uri);
    if (document.version !== documentVersion || document.getText() !== text ||
        eolFromDocument(document) !== eol) {
      throw new WorkspaceEditNormalizationError(
        'documentChangedDuringCapture',
        'Document changed while its WorkspaceEdit snapshot was being captured.',
      );
    }
    const boundaryFingerprint = workspaceBoundaryFingerprint(
      context,
      providerPath.rootAlias,
      this.#primitives,
    );
    const targetBase = {
      file: providerPath.logicalPath,
      internalUri: this.#host.uriString(entry.uri),
      rootAlias: providerPath.rootAlias,
      boundaryFingerprint,
      documentEpoch,
      documentVersion,
      memoryContentSha256: sha256Utf16Text(text, this.#primitives),
      eol,
      encoding: MEMORY_TEXT_ENCODING,
      expectedPostContentSha256: sha256Utf16Text(expectedPostContent, this.#primitives),
    } as const;
    const target: TextDocumentSnapshot = disk.exists
      ? Object.freeze({
          ...targetBase,
          diskExists: true,
          diskByteSha256: this.#primitives.sha256Hex(new Uint8Array(disk.bytes)),
        })
      : Object.freeze({ ...targetBase, diskExists: false });
    return Object.freeze({
      change: Object.freeze({
        kind: 'text',
        file: providerPath.logicalPath,
        edits: Object.freeze(sortedEdits.map(freezeNormalizedEdit)),
      }),
      target,
    });
  }

  async normalize(
    context: WorkspacePathContext,
    providerEdit: ProviderWorkspaceEdit,
  ): Promise<NormalizedWorkspaceEdit> {
    const entries = captureProviderEntries(providerEdit, this.#host);
    const normalized: Array<{
      readonly change: NormalizedTextChange;
      readonly target: TextDocumentSnapshot;
    }> = [];
    const files = new Set<string>();
    for (const entry of entries) {
      const result = await this.#normalizeEntry(context, entry);
      if (result === undefined) continue;
      if (files.has(result.change.file)) {
        throw new WorkspaceEditNormalizationError(
          'duplicateTarget',
          'WorkspaceEdit contains duplicate logical targets.',
        );
      }
      files.add(result.change.file);
      normalized.push(result);
    }
    normalized.sort((left, right) => compareTextChanges(left.change, right.change));
    return Object.freeze({
      textChanges: Object.freeze(normalized.map(({ change }) => change)),
      targets: Object.freeze(normalized.map(({ target }) => target)),
    });
  }
}

interface ZeroBasedRangeValue {
  readonly start: ProviderPointValue;
  readonly end: ProviderPointValue;
}

export interface TextOnlyWorkspaceEditRebuildHost<TWorkspaceEdit, TUri, TTextEdit> {
  createTextEdit(range: ZeroBasedRangeValue, newText: string): TTextEdit;
  createWorkspaceEdit(): TWorkspaceEdit;
  fileUri(absolutePath: string): TUri;
  setTextEdits(workspaceEdit: TWorkspaceEdit, uri: TUri, edits: readonly TTextEdit[]): void;
}

export const rebuildTextOnlyWorkspaceEdit = async <TWorkspaceEdit, TUri, TTextEdit>(
  context: WorkspacePathContext,
  normalized: NormalizedWorkspaceEdit,
  host: TextOnlyWorkspaceEditRebuildHost<TWorkspaceEdit, TUri, TTextEdit>,
  pathAccess: WorkspacePathAccess = systemWorkspacePathAccess,
): Promise<TWorkspaceEdit> => {
  const rebuilt = host.createWorkspaceEdit();
  for (const change of normalized.textChanges) {
    const resolved = await resolveLogicalPath(context, change.file, pathAccess, { allowMissing: true });
    const uri = host.fileUri(resolved.lexicalAbsolutePath);
    const edits = change.edits.map((edit) => host.createTextEdit({
      start: { line: edit.range.startLine - 1, character: edit.range.startColumn - 1 },
      end: { line: edit.range.endLine - 1, character: edit.range.endColumn - 1 },
    }, edit.newText));
    host.setTextEdits(rebuilt, uri, Object.freeze(edits));
  }
  return rebuilt;
};

export const createVscodeWorkspaceEditNormalizerHost = (
  vscode: typeof import('vscode'),
): WorkspaceEditNormalizerHost => Object.freeze({
  createRange: (range: ProviderRangeValue): VscodeRange => new vscode.Range(
    range.start.line,
    range.start.character,
    range.end.line,
    range.end.character,
  ),
  fileUri: (absolutePath: string): Uri => vscode.Uri.file(absolutePath),
  isTextEdit: (value: unknown): value is VscodeTextEdit =>
    value instanceof vscode.TextEdit && Object.getPrototypeOf(value) === vscode.TextEdit.prototype,
  openTextDocument: (uri: unknown) => vscode.workspace.openTextDocument(uri as Uri),
  readDiskFile: async (uri: unknown): Promise<DiskFileSnapshot> => {
    try {
      return { exists: true, bytes: await vscode.workspace.fs.readFile(uri as Uri) };
    } catch (error) {
      if (error instanceof vscode.FileSystemError && error.code === 'FileNotFound') {
        return { exists: false };
      }
      throw error;
    }
  },
  uriString: (uri: unknown): string => (uri as Uri).toString(),
});

export const createVscodeWorkspaceEditRebuildHost = (
  vscode: typeof import('vscode'),
): TextOnlyWorkspaceEditRebuildHost<WorkspaceEdit, Uri, VscodeTextEdit> => Object.freeze({
  createTextEdit: (range: ZeroBasedRangeValue, newText: string): VscodeTextEdit =>
    vscode.TextEdit.replace(new vscode.Range(
    range.start.line,
    range.start.character,
    range.end.line,
    range.end.character,
  ), newText),
  createWorkspaceEdit: (): WorkspaceEdit => new vscode.WorkspaceEdit(),
  fileUri: (absolutePath: string): Uri => vscode.Uri.file(absolutePath),
  setTextEdits: (
    workspaceEdit: WorkspaceEdit,
    uri: Uri,
    edits: readonly VscodeTextEdit[],
  ): void => workspaceEdit.set(uri, [...edits]),
});
