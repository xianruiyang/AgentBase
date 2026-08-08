import type {
  Position as VscodePosition,
  Range as VscodeRange,
  TextDocument,
} from 'vscode';
import {
  MUTATION_RENAME_PREVIEW_BRIDGE_METHOD,
  WorkspaceBoundaryError,
  canonicalizeJson,
  logicalPathFromProviderLocation,
  matchesLogicalGlobs,
  parseRenamePreviewBridgeRequest,
  resolveLogicalPath,
  systemWorkspacePathAccess,
  type RenamePreviewBridgeRequest,
  type RenamePreviewBridgeResponse,
  type RenameIdentityRejectionReason,
  type WorkspacePathAccess,
  type WorkspacePathContext,
  type WorkspaceRouteIdentity,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  ProviderRuntime,
  classifyArrayProviderResult,
  createVscodeProviderCallInterrupter,
  type ProviderCommandAdapter,
  type ProviderInvocationResult,
} from './provider-runtime.js';
import {
  DocumentEpochTracker,
  WorkspaceEditNormalizationError,
  WorkspaceEditNormalizer,
  createVscodeWorkspaceEditNormalizerHost,
  type ProviderWorkspaceEdit,
  type WorkspaceEditNormalizerHost,
} from './workspace-edit-normalizer.js';
import type { MutationBridgeHandler } from './mutation-apply-provider.js';
import {
  SymbolIdentityResolver,
  type SymbolIdentityFailureStatus,
} from './symbol-identity-resolver.js';

interface ProviderPoint {
  readonly line: number;
  readonly character: number;
}

interface ProviderRange {
  readonly start: ProviderPoint;
  readonly end: ProviderPoint;
}

interface SourceDocumentState {
  readonly document: TextDocument;
  readonly text: string;
  readonly version: number;
}

export interface RenamePreviewHost extends WorkspaceEditNormalizerHost {
  createPosition(line: number, character: number): VscodePosition;
  executeCommand(command: string, ...args: readonly unknown[]): PromiseLike<unknown>;
}

export interface RenamePreviewExecutorOptions {
  readonly defaultTimeoutMs?: number;
  readonly epochTracker: DocumentEpochTracker;
  readonly pathAccess?: WorkspacePathAccess;
}

const RENAME_IDENTITY_MAX_EDITS = 100;
const RENAME_IDENTITY_TOTAL_TIMEOUT_MS = 30_000;
const RENAME_IDENTITY_CALL_TIMEOUT_MS = 3_000;
const RENAME_IDENTITY_FILE_LIMIT = 10;
const RENAME_IDENTITY_MAX_REFERENCE_LOCATIONS = 200;
const RENAME_SCOPE_FILE_LIMIT = 10;

const asRecord = (value: unknown): Record<string, unknown> | undefined =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;

const point = (value: unknown): ProviderPoint | undefined => {
  const record = asRecord(value);
  return record !== undefined &&
      Number.isSafeInteger(record.line) && (record.line as number) >= 0 &&
      (record.line as number) < Number.MAX_SAFE_INTEGER &&
      Number.isSafeInteger(record.character) && (record.character as number) >= 0 &&
      (record.character as number) < Number.MAX_SAFE_INTEGER
    ? { line: record.line as number, character: record.character as number }
    : undefined;
};

const range = (value: unknown): ProviderRange | undefined => {
  const record = asRecord(value);
  const start = point(record?.start);
  const end = point(record?.end);
  if (start === undefined || end === undefined || end.line < start.line ||
      (end.line === start.line && end.character < start.character)) {
    return undefined;
  }
  return Object.freeze({ start: Object.freeze(start), end: Object.freeze(end) });
};

const comparePoints = (left: ProviderPoint, right: ProviderPoint): number =>
  left.line - right.line || left.character - right.character;

const containsPoint = (candidate: ProviderRange, target: ProviderPoint): boolean =>
  comparePoints(candidate.start, target) <= 0 && comparePoints(target, candidate.end) <= 0;

const samePoint = (left: ProviderPoint, right: VscodePosition): boolean =>
  left.line === right.line && left.character === right.character;

const sameRange = (left: ProviderRange, right: VscodeRange): boolean =>
  samePoint(left.start, right.start) && samePoint(left.end, right.end);

const isProviderWorkspaceEdit = (value: unknown): value is ProviderWorkspaceEdit => {
  const record = asRecord(value);
  return record !== undefined && Number.isSafeInteger(record.size) &&
    (record.size as number) >= 0 && typeof record.entries === 'function';
};

const prepareAdapter = (
  target: VscodePosition,
): ProviderCommandAdapter<null, ProviderRange> => ({
  command: 'vscode.prepareRename',
  requiresDocument: true,
  buildArguments: (_input, document) => {
    if (document === undefined) throw new RangeError('Rename document was not activated.');
    return [document.uri, target];
  },
  classifyResult: (value) => {
    if (value === undefined || value === null) return { status: 'notReady' };
    const record = asRecord(value);
    const preparedRange = range(record?.range ?? value);
    return preparedRange !== undefined && containsPoint(preparedRange, target)
      ? { status: 'ready', value: preparedRange }
      : { status: 'invalid' };
  },
});

const renameAdapter = (
  target: VscodePosition,
): ProviderCommandAdapter<string, ProviderWorkspaceEdit> => ({
  command: 'vscode.executeDocumentRenameProvider',
  requiresDocument: true,
  buildArguments: (newName, document) => {
    if (document === undefined) throw new RangeError('Rename document was not activated.');
    return [document.uri, target, newName];
  },
  classifyResult: (value) => value === undefined || value === null
    ? { status: 'notReady' }
    : isProviderWorkspaceEdit(value)
      ? { status: 'ready', value }
      : { status: 'invalid' },
});

const referencesAdapter = (
  target: VscodePosition,
): ProviderCommandAdapter<null, readonly unknown[]> => ({
  command: 'vscode.executeReferenceProvider',
  requiresDocument: true,
  buildArguments: (_input, document) => {
    if (document === undefined) throw new RangeError('Rename document was not activated.');
    return [document.uri, target];
  },
  classifyResult: classifyArrayProviderResult,
});

const referencePositionKey = async (
  context: WorkspacePathContext,
  value: unknown,
  pathAccess: WorkspacePathAccess,
): Promise<string | undefined> => {
  const record = asRecord(value);
  const rawUri = asRecord(record?.uri);
  const rawRange = range(record?.range);
  if (rawUri === undefined || typeof rawUri.scheme !== 'string' ||
      typeof rawUri.fsPath !== 'string' || rawRange === undefined) {
    return undefined;
  }
  const mapped = await logicalPathFromProviderLocation(context, {
    uriScheme: rawUri.scheme,
    lexicalAbsolutePath: rawUri.fsPath,
  }, pathAccess);
  const file = context.platform === 'win32'
    ? mapped.logicalPath.toLowerCase()
    : mapped.logicalPath;
  return JSON.stringify([file, rawRange.start.line, rawRange.start.character]);
};

const editPositionKey = (
  context: WorkspacePathContext,
  file: string,
  line: number,
  column: number,
): string => JSON.stringify([
  context.platform === 'win32' ? file.toLowerCase() : file,
  line - 1,
  column - 1,
]);

const sameWorkspace = (
  active: WorkspaceRouteIdentity,
  expected: WorkspaceRouteIdentity,
): boolean => active.workspaceId === expected.workspaceId && active.generation === expected.generation;

const providerFailure = <T>(
  result: ProviderInvocationResult<T>,
  prepare: boolean,
): RenamePreviewBridgeResponse => {
  if (result.status === 'unavailable') return Object.freeze({ status: 'unavailable' });
  if (result.status === 'timedOut') return Object.freeze({ status: 'timedOut' });
  if (result.status === 'cancelled') return Object.freeze({ status: 'cancelled' });
  if (result.status === 'notReady') {
    return prepare
      ? Object.freeze({ status: 'prepareRejected', reason: 'notRenameable' })
      : Object.freeze({ status: 'notReady' });
  }
  if (result.status !== 'failed') return Object.freeze({ status: 'failed' });
  if (result.reason === 'documentActivationFailed') {
    return Object.freeze({ status: 'documentNotFound' });
  }
  if (result.reason === 'providerArgumentsInvalid') {
    return Object.freeze({ status: 'positionOutOfRange' });
  }
  if (prepare && result.reason === 'providerResultInvalid') {
    return Object.freeze({ status: 'prepareRejected', reason: 'invalidResult' });
  }
  if (prepare && result.reason === 'providerCallFailed') {
    return Object.freeze({ status: 'prepareRejected', reason: 'notRenameable' });
  }
  return Object.freeze({ status: 'failed' });
};

const sourceChange = async (
  host: RenamePreviewHost,
  source: SourceDocumentState,
): Promise<Extract<RenamePreviewBridgeResponse, { readonly status: 'documentChanged' }> | undefined> => {
  let current: TextDocument;
  try {
    current = await host.openTextDocument(source.document.uri);
  } catch {
    return Object.freeze({ status: 'documentChanged', reason: 'existence' });
  }
  const text = current.getText();
  if (current !== source.document || text !== source.text) {
    return Object.freeze({ status: 'documentChanged', reason: 'content' });
  }
  return current.version === source.version
    ? undefined
    : Object.freeze({ status: 'documentChanged', reason: 'version' });
};

const normalizationFailure = (error: WorkspaceEditNormalizationError): RenamePreviewBridgeResponse => {
  if (error.reason === 'documentChangedDuringCapture') {
    return Object.freeze({ status: 'documentChanged', reason: 'content' });
  }
  if (error.reason === 'invalidRange') {
    return Object.freeze({ status: 'editConflict', reason: 'rangeOutOfBounds' });
  }
  if (error.reason === 'overlappingEdits') {
    return Object.freeze({ status: 'editConflict', reason: 'overlappingEdits' });
  }
  if (error.reason === 'duplicateTarget') {
    return Object.freeze({ status: 'editConflict', reason: 'ambiguousOperationOrder' });
  }
  return Object.freeze({ status: 'editConflict', reason: 'unsupportedEdit' });
};

const identityRejection = (
  reason: RenameIdentityRejectionReason,
  checkedEdits: number,
  totalEdits: number,
  files: readonly string[] = [],
): RenamePreviewBridgeResponse => {
  const uniqueFiles = Object.freeze([...new Set(files)].sort());
  const visibleFiles = Object.freeze(uniqueFiles.slice(0, RENAME_IDENTITY_FILE_LIMIT));
  const additionalFiles = uniqueFiles.length - visibleFiles.length;
  return Object.freeze({
    status: 'identityRejected',
    reason,
    checkedEdits,
    totalEdits,
    ...(visibleFiles.length === 0 ? {} : { files: visibleFiles }),
    ...(additionalFiles === 0 ? {} : { additionalFiles }),
  });
};

const targetIdentityFailure = (
  status: SymbolIdentityFailureStatus,
  totalEdits: number,
  file: string,
): RenamePreviewBridgeResponse => {
  if (status === 'timedOut') {
    return identityRejection('providerTimedOut', 0, totalEdits, [file]);
  }
  if (status === 'cancelled') return Object.freeze({ status: 'cancelled' });
  if (status === 'budgetExceeded') {
    return identityRejection('budgetExceeded', 0, totalEdits, [file]);
  }
  return identityRejection(
    status === 'failed' || status === 'positionOutOfRange'
      ? 'providerFailed'
      : 'targetUnresolved',
    0,
    totalEdits,
    [file],
  );
};

export class RenamePreviewExecutor {
  readonly #host: RenamePreviewHost;
  readonly #identityCallTimeoutMs: number;
  readonly #normalizer: WorkspaceEditNormalizer;
  readonly #pathAccess: WorkspacePathAccess;
  readonly #runtime: ProviderRuntime;
  readonly #identity: SymbolIdentityResolver;

  constructor(host: RenamePreviewHost, options: RenamePreviewExecutorOptions) {
    this.#host = host;
    this.#identityCallTimeoutMs = Math.min(
      RENAME_IDENTITY_CALL_TIMEOUT_MS,
      options.defaultTimeoutMs ?? RENAME_IDENTITY_CALL_TIMEOUT_MS,
    );
    this.#pathAccess = options.pathAccess ?? systemWorkspacePathAccess;
    this.#normalizer = new WorkspaceEditNormalizer(host, {
      epochTracker: options.epochTracker,
      pathAccess: this.#pathAccess,
    });
    this.#runtime = new ProviderRuntime({
      host,
      pathAccess: this.#pathAccess,
      ...(options.defaultTimeoutMs === undefined
        ? {}
        : { defaultTimeoutMs: options.defaultTimeoutMs }),
    });
    this.#identity = new SymbolIdentityResolver(host, {
      pathAccess: this.#pathAccess,
      ...(options.defaultTimeoutMs === undefined
        ? {}
        : { defaultTimeoutMs: options.defaultTimeoutMs }),
    });
  }

  async preview(
    context: WorkspacePathContext,
    activeWorkspace: WorkspaceRouteIdentity,
    request: RenamePreviewBridgeRequest,
    signal: AbortSignal,
  ): Promise<RenamePreviewBridgeResponse> {
    if (!sameWorkspace(activeWorkspace, request.workspace)) {
      return Object.freeze({ status: 'workspaceChanged' });
    }
    const target = Object.freeze({ line: request.line - 1, character: request.column - 1 });
    let sourceDocument: TextDocument;
    try {
      const resolved = await resolveLogicalPath(context, request.file, this.#pathAccess);
      sourceDocument = await this.#host.openTextDocument(resolved.lexicalAbsolutePath);
    } catch (error) {
      return error instanceof WorkspaceBoundaryError
        ? Object.freeze({ status: 'pathOutsideWorkspace' })
        : Object.freeze({ status: 'documentNotFound' });
    }
    if (!Number.isSafeInteger(sourceDocument.version) || sourceDocument.version < 0) {
      return Object.freeze({ status: 'failed' });
    }
    const providerPosition = this.#host.createPosition(target.line, target.character);
    let validatedPosition: VscodePosition;
    try {
      validatedPosition = sourceDocument.validatePosition(providerPosition);
    } catch {
      return Object.freeze({ status: 'positionOutOfRange' });
    }
    if (!samePoint(target, validatedPosition)) {
      return Object.freeze({ status: 'positionOutOfRange' });
    }
    const source = Object.freeze({
      document: sourceDocument,
      text: sourceDocument.getText(),
      version: sourceDocument.version,
    });

    let prepared: ProviderInvocationResult<ProviderRange>;
    try {
      prepared = await this.#runtime.invoke(context, prepareAdapter(providerPosition), null, {
        logicalFile: request.file,
        signal,
        ...(request.timeoutMs === undefined ? {} : { timeoutMs: request.timeoutMs }),
      });
    } catch (error) {
      return error instanceof WorkspaceBoundaryError
        ? Object.freeze({ status: 'pathOutsideWorkspace' })
        : Object.freeze({ status: 'failed' });
    }
    if (prepared.status !== 'completed') return providerFailure(prepared, true);
    const preparedRange = this.#host.createRange(prepared.value);
    if (!sameRange(prepared.value, sourceDocument.validateRange(preparedRange))) {
      return Object.freeze({ status: 'prepareRejected', reason: 'invalidResult' });
    }
    const preparedText = source.text.slice(
      sourceDocument.offsetAt(preparedRange.start),
      sourceDocument.offsetAt(preparedRange.end),
    );
    const afterPrepare = await sourceChange(this.#host, source);
    if (afterPrepare !== undefined) return { ...afterPrepare, files: [request.file] };

    let renamed: ProviderInvocationResult<ProviderWorkspaceEdit>;
    try {
      renamed = await this.#runtime.invoke(context, renameAdapter(providerPosition), request.newName, {
        logicalFile: request.file,
        signal,
        ...(request.timeoutMs === undefined ? {} : { timeoutMs: request.timeoutMs }),
      });
    } catch (error) {
      return error instanceof WorkspaceBoundaryError
        ? Object.freeze({ status: 'pathOutsideWorkspace' })
        : Object.freeze({ status: 'failed' });
    }
    if (renamed.status !== 'completed') return providerFailure(renamed, false);
    const afterRename = await sourceChange(this.#host, source);
    if (afterRename !== undefined) return { ...afterRename, files: [request.file] };
    if (signal.aborted) return Object.freeze({ status: 'cancelled' });

    try {
      const normalizedEdit = await this.#normalizer.normalize(context, renamed.value);
      const afterNormalize = await sourceChange(this.#host, source);
      if (afterNormalize !== undefined) return { ...afterNormalize, files: [request.file] };
      const totalEdits = normalizedEdit.textChanges.reduce(
        (count, change) => count + change.edits.length,
        0,
      );
      if (totalEdits === 0) return Object.freeze({ status: 'noEdits' });
      const outOfScopeFiles = normalizedEdit.textChanges
        .map((change) => change.file)
        .filter((file) => {
          try {
            return !matchesLogicalGlobs(file, request);
          } catch {
            return true;
          }
        })
        .sort();
      if (outOfScopeFiles.length > 0) {
        const files = Object.freeze(outOfScopeFiles.slice(0, RENAME_SCOPE_FILE_LIMIT));
        const additionalFiles = outOfScopeFiles.length - files.length;
        return Object.freeze({
          status: 'scopeRejected',
          files,
          ...(additionalFiles === 0 ? {} : { additionalFiles }),
          totalFiles: normalizedEdit.textChanges.length,
        });
      }
      if (totalEdits > RENAME_IDENTITY_MAX_EDITS) {
        return identityRejection(
          'budgetExceeded',
          0,
          totalEdits,
          normalizedEdit.textChanges.map((change) => change.file),
        );
      }
      const textMismatchFiles = normalizedEdit.textChanges
        .filter((change) => change.edits.some((edit) =>
          preparedText.length === 0 || edit.oldText !== preparedText))
        .map((change) => change.file);
      if (textMismatchFiles.length > 0) {
        return identityRejection('textMismatch', 0, totalEdits, textMismatchFiles);
      }

      const identityDeadline = Date.now() + RENAME_IDENTITY_TOTAL_TIMEOUT_MS;
      const perCallTimeout = (): number | undefined => {
        const remaining = identityDeadline - Date.now();
        return remaining < 1 ? undefined : Math.min(this.#identityCallTimeoutMs, remaining);
      };
      const targetTimeout = perCallTimeout();
      if (targetTimeout === undefined) {
        return identityRejection('budgetExceeded', 0, totalEdits, [request.file]);
      }
      const targetIdentity = await this.#identity.resolveTarget(
        context,
        { file: request.file, line: request.line, column: request.column },
        signal,
        targetTimeout,
      );
      if (targetIdentity.status !== 'resolved') {
        return targetIdentityFailure(targetIdentity.status, totalEdits, request.file);
      }
      const targetAnchors = new Set(targetIdentity.anchors);
      let checkedEdits = 0;
      const unresolvedEdits: Array<{
        readonly file: string;
        readonly line: number;
        readonly column: number;
      }> = [];
      for (const change of normalizedEdit.textChanges) {
        for (const edit of change.edits) {
          const timeoutMs = perCallTimeout();
          if (timeoutMs === undefined) {
            return identityRejection('budgetExceeded', checkedEdits, totalEdits, [change.file]);
          }
          const verification = await this.#identity.verifyCandidate(
            context,
            {
              file: change.file,
              line: edit.range.startLine,
              column: edit.range.startColumn,
            },
            targetAnchors,
            signal,
            timeoutMs,
          );
          if (verification.status === 'verified') {
            checkedEdits += 1;
            continue;
          }
          if (verification.status === 'timedOut') {
            return identityRejection(
              'providerTimedOut',
              checkedEdits,
              totalEdits,
              [change.file],
            );
          }
          if (verification.status === 'cancelled') return Object.freeze({ status: 'cancelled' });
          if (verification.status === 'budgetExceeded') {
            return identityRejection('budgetExceeded', checkedEdits, totalEdits, [change.file]);
          }
          if (verification.status === 'unresolved' || verification.status === 'unavailable' ||
              verification.status === 'notReady') {
            unresolvedEdits.push(Object.freeze({
              file: change.file,
              line: edit.range.startLine,
              column: edit.range.startColumn,
            }));
            continue;
          }
          return identityRejection(
            verification.status === 'mismatched'
              ? 'mismatchedSymbol'
              : verification.status === 'failed' || verification.status === 'positionOutOfRange'
                ? 'providerFailed'
                : 'editUnresolved',
            checkedEdits,
            totalEdits,
            [change.file],
          );
        }
      }
      if (unresolvedEdits.length > 0) {
        const timeoutMs = perCallTimeout();
        if (timeoutMs === undefined) {
          return identityRejection(
            'budgetExceeded',
            checkedEdits,
            totalEdits,
            unresolvedEdits.map((edit) => edit.file),
          );
        }
        const references = await this.#runtime.invoke(
          context,
          referencesAdapter(providerPosition),
          null,
          {
            logicalFile: request.file,
            pollDelaysMs: [0],
            signal,
            timeoutMs,
          },
        );
        if (references.status === 'cancelled') return Object.freeze({ status: 'cancelled' });
        if (references.status !== 'completed') {
          return identityRejection(
            references.status === 'failed' ? 'providerFailed' : 'editUnresolved',
            checkedEdits,
            totalEdits,
            unresolvedEdits.map((edit) => edit.file),
          );
        }
        if (references.value.length > RENAME_IDENTITY_MAX_REFERENCE_LOCATIONS) {
          return identityRejection(
            'budgetExceeded',
            checkedEdits,
            totalEdits,
            unresolvedEdits.map((edit) => edit.file),
          );
        }
        const referenceKeys = new Set<string>();
        for (const raw of references.value) {
          const key = await referencePositionKey(context, raw, this.#pathAccess);
          if (key === undefined) {
            return identityRejection(
              'providerFailed',
              checkedEdits,
              totalEdits,
              unresolvedEdits.map((edit) => edit.file),
            );
          }
          referenceKeys.add(key);
        }
        const unproven = unresolvedEdits.filter((edit) => !referenceKeys.has(
          editPositionKey(context, edit.file, edit.line, edit.column),
        ));
        if (unproven.length > 0) {
          return identityRejection(
            'editUnresolved',
            checkedEdits,
            totalEdits,
            unproven.map((edit) => edit.file),
          );
        }
        checkedEdits += unresolvedEdits.length;
      }
      const afterIdentity = await sourceChange(this.#host, source);
      if (afterIdentity !== undefined) return { ...afterIdentity, files: [request.file] };
      return Object.freeze({ status: 'completed', normalizedEdit });
    } catch (error) {
      if (error instanceof WorkspaceBoundaryError) {
        return Object.freeze({ status: 'pathOutsideWorkspace' });
      }
      return error instanceof WorkspaceEditNormalizationError
        ? normalizationFailure(error)
        : Object.freeze({ status: 'failed' });
    }
  }
}

export const createRenamePreviewBridgeHandler = (
  executor: RenamePreviewExecutor,
): MutationBridgeHandler => async (context, workspace, request, signal) => {
  if (request.method !== MUTATION_RENAME_PREVIEW_BRIDGE_METHOD) return undefined;
  const parsed = parseRenamePreviewBridgeRequest(request.params);
  return canonicalizeJson(await executor.preview(context, workspace, parsed, signal));
};

export const createVscodeRenamePreviewHost = (
  vscode: typeof import('vscode'),
): RenamePreviewHost => {
  const normalizer = createVscodeWorkspaceEditNormalizerHost(vscode);
  return Object.freeze({
    ...normalizer,
    createPosition: (line: number, character: number) => new vscode.Position(line, character),
    executeCommand: (command: string, ...args: readonly unknown[]) =>
      vscode.commands.executeCommand(command, ...args),
    interruptProviderCall: createVscodeProviderCallInterrupter(vscode),
  });
};
