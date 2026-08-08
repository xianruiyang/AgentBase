import type {
  Range as VscodeRange,
  TextDocument,
  TextEdit as VscodeTextEdit,
  Uri,
  WorkspaceEdit,
} from 'vscode';
import {
  APPLY_ATTEMPTS_PER_WORKSPACE,
  APPLY_ATTEMPT_TTL_MS,
  MUTATION_APPLY_BRIDGE_METHOD,
  TextEditInvariantError,
  WorkspaceBoundaryError,
  canonicalizeJson,
  parseMutationApplyBridgeRequest,
  resolveLogicalPath,
  sha256Utf16Text,
  simulateNormalizedTextEdits,
  sortAndValidateNormalizedTextEdits,
  systemRuntimePrimitives,
  systemWorkspacePathAccess,
  type JsonObject,
  type JsonValue,
  type MutationApplyBridgeRequest,
  type MutationApplyBridgeResponse,
  type NormalizedTextChange,
  type NormalizedWorkspaceEdit,
  type RuntimePrimitives,
  type TextDocumentSnapshot,
  type WorkspaceMutationGate,
  type WorkspacePathAccess,
  type WorkspacePathContext,
  type WorkspaceRouteIdentity,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  DocumentEpochTracker,
  createVscodeWorkspaceEditNormalizerHost,
  createVscodeWorkspaceEditRebuildHost,
  eolFromDocument,
  rebuildTextOnlyWorkspaceEdit,
  workspaceBoundaryFingerprint,
  type DiskFileSnapshot,
} from './workspace-edit-normalizer.js';
import { WorkspaceExclusiveMutationGate } from './mutation-gate.js';

interface ZeroBasedPoint {
  readonly line: number;
  readonly character: number;
}

interface ZeroBasedRange {
  readonly start: ZeroBasedPoint;
  readonly end: ZeroBasedPoint;
}

export interface MutationApplyHost {
  applyEdit(workspaceEdit: unknown): PromiseLike<boolean>;
  createRange(range: ZeroBasedRange): VscodeRange;
  createTextEdit(range: ZeroBasedRange, newText: string): unknown;
  createWorkspaceEdit(): unknown;
  fileUri(absolutePath: string): unknown;
  openTextDocument(uri: unknown): PromiseLike<TextDocument>;
  readDiskFile(uri: unknown): PromiseLike<DiskFileSnapshot>;
  setTextEdits(workspaceEdit: unknown, uri: unknown, edits: readonly unknown[]): void;
  uriString(uri: unknown): string;
}

export interface MutationBridgeRequest {
  readonly method: string;
  readonly params: JsonObject;
}

export type MutationBridgeHandler = (
  context: WorkspacePathContext,
  workspace: WorkspaceRouteIdentity,
  request: MutationBridgeRequest,
  signal: AbortSignal,
) => Promise<JsonValue | undefined>;

interface PreparedTarget {
  readonly change: NormalizedTextChange;
  readonly document: TextDocument;
  readonly file: string;
  readonly snapshot: TextDocumentSnapshot;
  readonly text: string;
  readonly uri: unknown;
}

interface PreparedTargets {
  readonly prepared: true;
  readonly targets: readonly PreparedTarget[];
}

interface AttemptTombstone {
  readonly applyAttemptId: string;
  readonly expiresAtMonotonic: number;
  readonly response: MutationApplyBridgeResponse;
  readonly sequence: number;
}

export interface MutationApplyExecutorOptions {
  readonly epochTracker?: DocumentEpochTracker;
  readonly gate?: WorkspaceMutationGate;
  readonly pathAccess?: WorkspacePathAccess;
  readonly primitives?: RuntimePrimitives;
}

const sameWorkspace = (
  left: WorkspaceRouteIdentity,
  right: WorkspaceRouteIdentity,
): boolean => left.workspaceId === right.workspaceId && left.generation === right.generation;

const workspaceKey = (workspace: WorkspaceRouteIdentity): string =>
  `${workspace.workspaceId}\u0000${workspace.generation}`;

const samePoint = (left: ZeroBasedPoint, right: ZeroBasedPoint): boolean =>
  left.line === right.line && left.character === right.character;

const sameRange = (left: ZeroBasedRange, right: VscodeRange): boolean =>
  samePoint(left.start, right.start) && samePoint(left.end, right.end);

const boundedFiles = (files: readonly string[]): {
  readonly files: readonly string[];
  readonly additionalFiles?: number;
} => {
  const unique = [...new Set(files)].sort();
  const visible = Object.freeze(unique.slice(0, 100));
  return Object.freeze({
    files: visible,
    ...(unique.length <= visible.length ? {} : { additionalFiles: unique.length - visible.length }),
  });
};

const documentChanged = (
  reason: 'content' | 'version' | 'existence' | 'workspace',
  files: readonly string[],
): MutationApplyBridgeResponse => Object.freeze({
  status: 'documentChanged',
  reason,
  ...boundedFiles(files),
});

const editConflict = (
  reason: 'overlappingEdits' | 'rangeOutOfBounds' | 'unsupportedEdit' | 'ambiguousOperationOrder',
  files: readonly string[],
): MutationApplyBridgeResponse => Object.freeze({
  status: 'editConflict',
  reason,
  ...boundedFiles(files),
});

const applyFailed = (
  stage: 'apply' | 'readback',
  outcome: 'notApplied' | 'unknown' | 'postconditionFailed',
): MutationApplyBridgeResponse => Object.freeze({ status: 'applyFailed', stage, outcome });

const diskMatches = (
  snapshot: TextDocumentSnapshot,
  disk: DiskFileSnapshot,
  primitives: RuntimePrimitives,
): 'match' | 'existence' | 'content' => {
  if (snapshot.diskExists !== disk.exists) return 'existence';
  if (!snapshot.diskExists || !disk.exists) return 'match';
  return snapshot.diskByteSha256 === primitives.sha256Hex(new Uint8Array(disk.bytes))
    ? 'match'
    : 'content';
};

export class MutationApplyExecutor {
  readonly #host: MutationApplyHost;
  readonly #epochTracker: DocumentEpochTracker;
  readonly #gate: WorkspaceMutationGate;
  readonly #pathAccess: WorkspacePathAccess;
  readonly #primitives: RuntimePrimitives;
  readonly #attempts = new Map<string, Map<string, AttemptTombstone>>();
  #lastNow = -1;
  #nextSequence = 1;

  constructor(host: MutationApplyHost, options: MutationApplyExecutorOptions = {}) {
    this.#host = host;
    this.#epochTracker = options.epochTracker ?? new DocumentEpochTracker();
    this.#gate = options.gate ?? new WorkspaceExclusiveMutationGate();
    this.#pathAccess = options.pathAccess ?? systemWorkspacePathAccess;
    this.#primitives = options.primitives ?? systemRuntimePrimitives;
  }

  #now(): number {
    const now = this.#primitives.monotonicNowMs();
    if (!Number.isFinite(now) || now < 0 || now > Number.MAX_SAFE_INTEGER || now < this.#lastNow) {
      throw new RangeError('Mutation apply monotonic clock is invalid.');
    }
    this.#lastNow = now;
    return now;
  }

  #sequence(): number {
    if (!Number.isSafeInteger(this.#nextSequence) || this.#nextSequence < 1) {
      throw new RangeError('Mutation apply attempt sequence was exhausted.');
    }
    const sequence = this.#nextSequence;
    this.#nextSequence += 1;
    return sequence;
  }

  #cleanup(now: number): void {
    for (const [key, attempts] of this.#attempts) {
      for (const [attemptId, tombstone] of attempts) {
        if (tombstone.expiresAtMonotonic <= now) attempts.delete(attemptId);
      }
      if (attempts.size === 0) this.#attempts.delete(key);
    }
  }

  #remember(
    workspace: WorkspaceRouteIdentity,
    applyAttemptId: string,
    response: MutationApplyBridgeResponse,
    now: number,
  ): void {
    const key = workspaceKey(workspace);
    let attempts = this.#attempts.get(key);
    if (attempts === undefined) {
      attempts = new Map();
      this.#attempts.set(key, attempts);
    }
    attempts.set(applyAttemptId, Object.freeze({
      applyAttemptId,
      response,
      expiresAtMonotonic: now + APPLY_ATTEMPT_TTL_MS,
      sequence: this.#sequence(),
    }));
    const ordered = [...attempts.values()].sort((left, right) => left.sequence - right.sequence);
    while (ordered.length > APPLY_ATTEMPTS_PER_WORKSPACE) {
      const oldest = ordered.shift();
      if (oldest !== undefined) attempts.delete(oldest.applyAttemptId);
    }
  }

  #existing(
    workspace: WorkspaceRouteIdentity,
    applyAttemptId: string,
  ): MutationApplyBridgeResponse | undefined {
    return this.#attempts.get(workspaceKey(workspace))?.get(applyAttemptId)?.response;
  }

  async #prepareTargets(
    context: WorkspacePathContext,
    normalizedEdit: NormalizedWorkspaceEdit,
  ): Promise<PreparedTargets | MutationApplyBridgeResponse> {
    const pathWorkspaceFiles: string[] = [];
    const existenceFiles: string[] = [];
    const resolved: Array<{
      readonly change: NormalizedTextChange;
      readonly file: string;
      readonly snapshot: TextDocumentSnapshot;
      readonly uri: unknown;
    }> = [];

    for (let index = 0; index < normalizedEdit.textChanges.length; index += 1) {
      const change = normalizedEdit.textChanges[index]!;
      const snapshot = normalizedEdit.targets[index]!;
      try {
        const target = await resolveLogicalPath(
          context,
          change.file,
          this.#pathAccess,
          { allowMissing: true },
        );
        const uri = this.#host.fileUri(target.lexicalAbsolutePath);
        let currentBoundaryFingerprint: string | undefined;
        try {
          currentBoundaryFingerprint = workspaceBoundaryFingerprint(
            context,
            snapshot.rootAlias,
            this.#primitives,
          );
        } catch {
          currentBoundaryFingerprint = undefined;
        }
        if (target.root.alias !== snapshot.rootAlias || currentBoundaryFingerprint === undefined ||
            currentBoundaryFingerprint !== snapshot.boundaryFingerprint ||
            this.#host.uriString(uri) !== snapshot.internalUri) {
          pathWorkspaceFiles.push(change.file);
        }
        resolved.push({ change, snapshot, file: change.file, uri });
      } catch (error) {
        if (error instanceof WorkspaceBoundaryError && error.code === 'PATH_OUTSIDE_WORKSPACE') {
          return Object.freeze({ status: 'pathOutsideWorkspace' });
        }
        if (error instanceof WorkspaceBoundaryError && error.code === 'DOCUMENT_NOT_FOUND') {
          existenceFiles.push(change.file);
          continue;
        }
        if (error instanceof WorkspaceBoundaryError &&
            (error.code === 'ROOT_NOT_FOUND' || error.code === 'WORKSPACE_UNAVAILABLE')) {
          pathWorkspaceFiles.push(change.file);
          continue;
        }
        if (error instanceof WorkspaceBoundaryError && error.code === 'INVALID_ARGUMENT') {
          return editConflict('unsupportedEdit', [change.file]);
        }
        throw error;
      }
    }
    if (pathWorkspaceFiles.length > 0) return documentChanged('workspace', pathWorkspaceFiles);
    if (existenceFiles.length > 0) return documentChanged('existence', existenceFiles);

    const issues: Record<'existence' | 'version' | 'content' | 'workspace', string[]> = {
      existence: [],
      version: [],
      content: [],
      workspace: [],
    };
    const prepared: PreparedTarget[] = [];
    for (const target of resolved) {
      let document: TextDocument;
      try {
        document = await this.#host.openTextDocument(target.uri);
      } catch {
        issues.existence.push(target.file);
        continue;
      }
      if (this.#host.uriString(document.uri) !== target.snapshot.internalUri) {
        issues.workspace.push(target.file);
        continue;
      }
      const beforeVersion = document.version;
      const beforeText = document.getText();
      let beforeEol: 'lf' | 'crlf';
      try {
        beforeEol = eolFromDocument(document);
      } catch {
        issues.content.push(target.file);
        continue;
      }
      const epoch = this.#epochTracker.epochFor(document);
      if (epoch === target.snapshot.documentEpoch && beforeVersion !== target.snapshot.documentVersion) {
        issues.version.push(target.file);
      }
      if (sha256Utf16Text(beforeText, this.#primitives) !== target.snapshot.memoryContentSha256 ||
          beforeEol !== target.snapshot.eol) {
        issues.content.push(target.file);
      }
      let disk: DiskFileSnapshot;
      try {
        disk = await this.#host.readDiskFile(target.uri);
      } catch {
        issues.content.push(target.file);
        continue;
      }
      const diskState = diskMatches(target.snapshot, disk, this.#primitives);
      if (diskState !== 'match') issues[diskState].push(target.file);
      if (document.version !== beforeVersion) issues.version.push(target.file);
      if (document.getText() !== beforeText) issues.content.push(target.file);
      try {
        if (eolFromDocument(document) !== beforeEol) issues.content.push(target.file);
      } catch {
        issues.content.push(target.file);
      }
      prepared.push(Object.freeze({
        change: target.change,
        snapshot: target.snapshot,
        file: target.file,
        uri: target.uri,
        document,
        text: beforeText,
      }));
    }
    for (const reason of ['workspace', 'existence', 'version', 'content'] as const) {
      if (issues[reason].length > 0) return documentChanged(reason, issues[reason]);
    }
    return Object.freeze({ prepared: true, targets: Object.freeze(prepared) });
  }

  #validateRanges(
    prepared: readonly PreparedTarget[],
  ): MutationApplyBridgeResponse | { readonly changedFiles: readonly string[] } {
    const changedFiles: string[] = [];
    for (const target of prepared) {
      for (const edit of target.change.edits) {
        const range: ZeroBasedRange = {
          start: { line: edit.range.startLine - 1, character: edit.range.startColumn - 1 },
          end: { line: edit.range.endLine - 1, character: edit.range.endColumn - 1 },
        };
        let validated: VscodeRange;
        try {
          validated = target.document.validateRange(this.#host.createRange(range));
        } catch {
          return editConflict('rangeOutOfBounds', [target.file]);
        }
        if (!sameRange(range, validated)) return editConflict('rangeOutOfBounds', [target.file]);
        const startOffset = target.document.offsetAt(validated.start);
        const endOffset = target.document.offsetAt(validated.end);
        if (startOffset !== edit.startOffset || endOffset !== edit.endOffset ||
            !samePoint(range.start, target.document.positionAt(startOffset)) ||
            !samePoint(range.end, target.document.positionAt(endOffset))) {
          return editConflict('rangeOutOfBounds', [target.file]);
        }
      }
      try {
        const sorted = sortAndValidateNormalizedTextEdits(target.text, target.change.edits);
        if (sorted.some((edit, index) => edit !== target.change.edits[index])) {
          return editConflict('ambiguousOperationOrder', [target.file]);
        }
        const expected = simulateNormalizedTextEdits(target.text, sorted);
        if (sha256Utf16Text(expected, this.#primitives) !==
            target.snapshot.expectedPostContentSha256) {
          return editConflict('ambiguousOperationOrder', [target.file]);
        }
      } catch (error) {
        if (error instanceof TextEditInvariantError) {
          const reason = error.reason === 'overlappingEdits'
            ? 'overlappingEdits'
            : error.reason === 'invalidRange'
              ? 'rangeOutOfBounds'
              : 'unsupportedEdit';
          return editConflict(reason, [target.file]);
        }
        throw error;
      }
      if (target.snapshot.memoryContentSha256 !== target.snapshot.expectedPostContentSha256) {
        changedFiles.push(target.file);
      }
    }
    if (changedFiles.length === 0) return editConflict('unsupportedEdit', prepared.map(({ file }) => file));
    return Object.freeze({ changedFiles: Object.freeze([...new Set(changedFiles)].sort()) });
  }

  async #execute(
    context: WorkspacePathContext,
    request: MutationApplyBridgeRequest,
    signal: AbortSignal,
  ): Promise<MutationApplyBridgeResponse> {
    const prepared = await this.#prepareTargets(context, request.normalizedEdit);
    if (!('prepared' in prepared)) return prepared;
    const targets = prepared.targets;
    const validated = this.#validateRanges(targets);
    if ('status' in validated) return validated;
    if (signal.aborted) return applyFailed('apply', 'notApplied');

    let rebuilt: unknown;
    try {
      rebuilt = await rebuildTextOnlyWorkspaceEdit(
        context,
        request.normalizedEdit,
        {
          createTextEdit: (range, newText) => this.#host.createTextEdit(range, newText),
          createWorkspaceEdit: () => this.#host.createWorkspaceEdit(),
          fileUri: (absolutePath) => this.#host.fileUri(absolutePath),
          setTextEdits: (workspaceEdit, uri, edits) =>
            this.#host.setTextEdits(workspaceEdit, uri, edits),
        },
        this.#pathAccess,
      );
    } catch (error) {
      if (error instanceof WorkspaceBoundaryError && error.code === 'PATH_OUTSIDE_WORKSPACE') {
        return Object.freeze({ status: 'pathOutsideWorkspace' });
      }
      if (error instanceof WorkspaceBoundaryError) {
        return documentChanged(
          error.code === 'DOCUMENT_NOT_FOUND' ? 'existence' : 'workspace',
          targets.map(({ file }) => file),
        );
      }
      return applyFailed('apply', 'notApplied');
    }

    let applied: boolean;
    try {
      applied = await this.#host.applyEdit(rebuilt);
    } catch {
      return applyFailed('apply', 'unknown');
    }
    if (!applied) return applyFailed('apply', 'notApplied');

    try {
      for (const target of targets) {
        const document = await this.#host.openTextDocument(target.uri);
        if (sha256Utf16Text(document.getText(), this.#primitives) !==
            target.snapshot.expectedPostContentSha256) {
          return applyFailed('readback', 'postconditionFailed');
        }
      }
    } catch {
      return applyFailed('readback', 'postconditionFailed');
    }
    return Object.freeze({ status: 'applied', changedFiles: validated.changedFiles });
  }

  async validateNormalizedEdit(
    context: WorkspacePathContext,
    activeWorkspace: WorkspaceRouteIdentity,
    expectedWorkspace: WorkspaceRouteIdentity,
    normalizedEdit: NormalizedWorkspaceEdit,
  ): Promise<MutationApplyBridgeResponse | { readonly status: 'ready' }> {
    if (!sameWorkspace(activeWorkspace, expectedWorkspace)) {
      return Object.freeze({ status: 'workspaceChanged' });
    }
    const prepared = await this.#prepareTargets(context, normalizedEdit);
    if (!('prepared' in prepared)) return prepared;
    const validated = this.#validateRanges(prepared.targets);
    return 'status' in validated ? validated : Object.freeze({ status: 'ready' });
  }

  async apply(
    context: WorkspacePathContext,
    activeWorkspace: WorkspaceRouteIdentity,
    request: MutationApplyBridgeRequest,
    signal: AbortSignal,
  ): Promise<MutationApplyBridgeResponse> {
    if (!sameWorkspace(activeWorkspace, request.workspace)) {
      return Object.freeze({ status: 'workspaceChanged' });
    }
    return this.#gate.runExclusive(activeWorkspace, 'apply', async () => {
      const now = this.#now();
      this.#cleanup(now);
      const existing = this.#existing(activeWorkspace, request.applyAttemptId);
      if (existing !== undefined) return existing;
      let response: MutationApplyBridgeResponse;
      try {
        response = await this.#execute(context, request, signal);
      } catch {
        response = applyFailed('apply', 'notApplied');
      }
      this.#remember(activeWorkspace, request.applyAttemptId, response, this.#now());
      return response;
    });
  }

  attemptTombstoneCount(): number {
    const now = this.#now();
    this.#cleanup(now);
    let count = 0;
    for (const attempts of this.#attempts.values()) count += attempts.size;
    return count;
  }
}

export const createMutationApplyBridgeHandler = (
  executor: MutationApplyExecutor,
): MutationBridgeHandler => async (context, workspace, request, signal) => {
  if (request.method !== MUTATION_APPLY_BRIDGE_METHOD) return undefined;
  const parsed = parseMutationApplyBridgeRequest(request.params);
  return canonicalizeJson(await executor.apply(context, workspace, parsed, signal));
};

export const createVscodeMutationApplyHost = (
  vscode: typeof import('vscode'),
): MutationApplyHost => {
  const normalizer = createVscodeWorkspaceEditNormalizerHost(vscode);
  const rebuild = createVscodeWorkspaceEditRebuildHost(vscode);
  return Object.freeze({
    applyEdit: (workspaceEdit: unknown) => vscode.workspace.applyEdit(workspaceEdit as WorkspaceEdit),
    createRange: (range: ZeroBasedRange) => normalizer.createRange(range),
    createTextEdit: (range: ZeroBasedRange, newText: string): VscodeTextEdit =>
      rebuild.createTextEdit(range, newText),
    createWorkspaceEdit: (): WorkspaceEdit => rebuild.createWorkspaceEdit(),
    fileUri: (absolutePath: string): Uri => rebuild.fileUri(absolutePath),
    openTextDocument: (uri: unknown) => normalizer.openTextDocument(uri),
    readDiskFile: (uri: unknown) => normalizer.readDiskFile(uri),
    setTextEdits: (workspaceEdit: unknown, uri: unknown, edits: readonly unknown[]) =>
      rebuild.setTextEdits(
        workspaceEdit as WorkspaceEdit,
        uri as Uri,
        edits as readonly VscodeTextEdit[],
      ),
    uriString: (uri: unknown) => normalizer.uriString(uri),
  });
};
