import type {
  Position as VscodePosition,
  Range as VscodeRange,
  TextDocument,
} from 'vscode';
import {
  MUTATION_FORMAT_PREVIEW_BRIDGE_METHOD,
  WorkspaceBoundaryError,
  canonicalizeJson,
  parseFormatPreviewBridgeRequest,
  systemWorkspacePathAccess,
  type FormatPreviewBridgeRequest,
  type FormatPreviewBridgeResponse,
  type FormattingOptions,
  type Range,
  type TextDocumentSnapshot,
  type WorkspacePathAccess,
  type WorkspacePathContext,
  type WorkspaceRouteIdentity,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  ProviderRuntime,
  type ProviderCommandAdapter,
  type ProviderInvocationResult,
} from './provider-runtime.js';
import {
  DocumentEpochTracker,
  WorkspaceEditNormalizationError,
  WorkspaceEditNormalizer,
  createVscodeWorkspaceEditNormalizerHost,
  type CapturedDocumentSnapshot,
  type ProviderWorkspaceEdit,
  type WorkspaceEditNormalizerHost,
} from './workspace-edit-normalizer.js';
import type { MutationBridgeHandler } from './mutation-apply-provider.js';

interface ProviderPoint {
  readonly line: number;
  readonly character: number;
}

interface ProviderRange {
  readonly start: ProviderPoint;
  readonly end: ProviderPoint;
}

interface ResolvedFormattingOptions {
  readonly tabSize: number;
  readonly insertSpaces: boolean;
}

export interface FormatPreviewHost extends WorkspaceEditNormalizerHost {
  executeCommand(command: string, ...args: readonly unknown[]): PromiseLike<unknown>;
  readFormattingOptions(document: TextDocument): FormattingOptions;
}

export interface FormatPreviewExecutorOptions {
  readonly defaultTimeoutMs?: number;
  readonly epochTracker: DocumentEpochTracker;
  readonly pathAccess?: WorkspacePathAccess;
}

const sameWorkspace = (
  active: WorkspaceRouteIdentity,
  expected: WorkspaceRouteIdentity,
): boolean => active.workspaceId === expected.workspaceId && active.generation === expected.generation;

const samePoint = (left: ProviderPoint, right: VscodePosition): boolean =>
  left.line === right.line && left.character === right.character;

const sameRange = (left: ProviderRange, right: VscodeRange): boolean =>
  samePoint(left.start, right.start) && samePoint(left.end, right.end);

const snapshotDifference = (
  expected: TextDocumentSnapshot,
  current: TextDocumentSnapshot,
): 'content' | 'version' | 'existence' | 'workspace' | undefined => {
  if (expected.file !== current.file || expected.rootAlias !== current.rootAlias ||
      expected.boundaryFingerprint !== current.boundaryFingerprint ||
      expected.internalUri !== current.internalUri) {
    return 'workspace';
  }
  if (expected.diskExists !== current.diskExists) return 'existence';
  if (expected.diskExists && current.diskExists &&
      expected.diskByteSha256 !== current.diskByteSha256) {
    return 'content';
  }
  if (expected.memoryContentSha256 !== current.memoryContentSha256 ||
      expected.eol !== current.eol || expected.encoding !== current.encoding) {
    return 'content';
  }
  if (expected.documentEpoch === current.documentEpoch &&
      expected.documentVersion !== current.documentVersion) {
    return 'version';
  }
  return undefined;
};

const resolvedOptions = (
  configured: FormattingOptions,
  requested: FormattingOptions | undefined,
): ResolvedFormattingOptions => {
  const configuredTabSize = Number.isSafeInteger(configured.tabSize) &&
      configured.tabSize! >= 1 && configured.tabSize! <= 32
    ? configured.tabSize!
    : 4;
  const configuredInsertSpaces = typeof configured.insertSpaces === 'boolean'
    ? configured.insertSpaces
    : true;
  return Object.freeze({
    tabSize: requested?.tabSize ?? configuredTabSize,
    insertSpaces: requested?.insertSpaces ?? configuredInsertSpaces,
  });
};

const formatAdapter = (
  range: VscodeRange | undefined,
  options: ResolvedFormattingOptions,
): ProviderCommandAdapter<null, readonly unknown[]> => ({
  command: range === undefined
    ? 'vscode.executeFormatDocumentProvider'
    : 'vscode.executeFormatRangeProvider',
  requiresDocument: true,
  buildArguments: (_input, document) => {
    if (document === undefined) throw new RangeError('Format document was not activated.');
    return range === undefined
      ? [document.uri, options]
      : [document.uri, range, options];
  },
  classifyResult: (value) => value === undefined || value === null
    ? { status: 'notReady' }
    : Array.isArray(value)
      ? { status: 'ready', value: Object.freeze([...value]) }
      : { status: 'invalid' },
});

const asWorkspaceEdit = (
  source: CapturedDocumentSnapshot,
  edits: readonly unknown[],
): ProviderWorkspaceEdit => edits.length === 0
  ? Object.freeze({ size: 0, entries: () => Object.freeze([]) })
  : Object.freeze({
      size: 1,
      entries: () => Object.freeze([
        Object.freeze([source.uri, edits] as const),
      ]),
    });

const providerFailure = (
  result: ProviderInvocationResult<readonly unknown[]>,
): FormatPreviewBridgeResponse => {
  if (result.status === 'unavailable') return Object.freeze({ status: 'unavailable' });
  if (result.status === 'notReady') return Object.freeze({ status: 'notReady' });
  if (result.status === 'cancelled') return Object.freeze({ status: 'cancelled' });
  if (result.status === 'timedOut') return Object.freeze({ status: 'timedOut' });
  if (result.status === 'failed' && result.reason === 'documentActivationFailed') {
    return Object.freeze({ status: 'documentNotFound' });
  }
  if (result.status === 'failed' && result.reason === 'providerArgumentsInvalid') {
    return Object.freeze({ status: 'positionOutOfRange' });
  }
  return Object.freeze({ status: 'failed' });
};

const normalizationFailure = (
  error: WorkspaceEditNormalizationError,
): FormatPreviewBridgeResponse => {
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

export class FormatPreviewExecutor {
  readonly #host: FormatPreviewHost;
  readonly #normalizer: WorkspaceEditNormalizer;
  readonly #pathAccess: WorkspacePathAccess;
  readonly #runtime: ProviderRuntime;

  constructor(host: FormatPreviewHost, options: FormatPreviewExecutorOptions) {
    this.#host = host;
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
  }

  #providerRange(
    source: CapturedDocumentSnapshot,
    value: Range,
  ): VscodeRange | undefined {
    const raw: ProviderRange = {
      start: { line: value.startLine - 1, character: value.startColumn - 1 },
      end: { line: value.endLine - 1, character: value.endColumn - 1 },
    };
    try {
      const range = this.#host.createRange(raw);
      const validated = source.document.validateRange(range);
      if (!sameRange(raw, validated)) return undefined;
      const startOffset = source.document.offsetAt(validated.start);
      const endOffset = source.document.offsetAt(validated.end);
      if (!samePoint(raw.start, source.document.positionAt(startOffset)) ||
          !samePoint(raw.end, source.document.positionAt(endOffset))) {
        return undefined;
      }
      return validated;
    } catch {
      return undefined;
    }
  }

  async #sourceDifference(
    context: WorkspacePathContext,
    expected: TextDocumentSnapshot,
  ): Promise<Extract<FormatPreviewBridgeResponse, {
    readonly status: 'documentChanged' | 'pathOutsideWorkspace';
  }> | undefined> {
    try {
      const current = await this.#normalizer.captureDocument(context, expected.file);
      const difference = snapshotDifference(expected, current.snapshot);
      return difference === undefined
        ? undefined
        : Object.freeze({ status: 'documentChanged', reason: difference, files: [expected.file] });
    } catch (error) {
      if (error instanceof WorkspaceBoundaryError && error.code === 'PATH_OUTSIDE_WORKSPACE') {
        return Object.freeze({ status: 'pathOutsideWorkspace' });
      }
      return Object.freeze({
        status: 'documentChanged',
        reason: error instanceof WorkspaceBoundaryError && error.code === 'DOCUMENT_NOT_FOUND'
          ? 'existence'
          : 'workspace',
        files: [expected.file],
      });
    }
  }

  async preview(
    context: WorkspacePathContext,
    activeWorkspace: WorkspaceRouteIdentity,
    request: FormatPreviewBridgeRequest,
    signal: AbortSignal,
  ): Promise<FormatPreviewBridgeResponse> {
    if (!sameWorkspace(activeWorkspace, request.workspace)) {
      return Object.freeze({ status: 'workspaceChanged' });
    }
    let source: CapturedDocumentSnapshot;
    try {
      source = await this.#normalizer.captureDocument(context, request.file);
    } catch (error) {
      if (error instanceof WorkspaceBoundaryError) {
        if (error.code === 'PATH_OUTSIDE_WORKSPACE') {
          return Object.freeze({ status: 'pathOutsideWorkspace' });
        }
        if (error.code === 'DOCUMENT_NOT_FOUND') {
          return Object.freeze({ status: 'documentNotFound' });
        }
      }
      return Object.freeze({ status: 'failed' });
    }
    const providerRange = request.range === undefined
      ? undefined
      : this.#providerRange(source, request.range);
    if (request.range !== undefined && providerRange === undefined) {
      return Object.freeze({ status: 'positionOutOfRange' });
    }
    const options = resolvedOptions(
      this.#host.readFormattingOptions(source.document),
      request.options,
    );
    let formatted: ProviderInvocationResult<readonly unknown[]>;
    try {
      formatted = await this.#runtime.invoke(
        context,
        formatAdapter(providerRange, options),
        null,
        { logicalFile: request.file, signal },
      );
    } catch (error) {
      return error instanceof WorkspaceBoundaryError
        ? Object.freeze({ status: 'pathOutsideWorkspace' })
        : Object.freeze({ status: 'failed' });
    }
    if (formatted.status !== 'completed') return providerFailure(formatted);
    const afterProvider = await this.#sourceDifference(context, source.snapshot);
    if (afterProvider !== undefined) return afterProvider;
    if (signal.aborted) return Object.freeze({ status: 'cancelled' });
    try {
      const normalizedEdit = await this.#normalizer.normalize(
        context,
        asWorkspaceEdit(source, formatted.value),
      );
      const afterNormalize = await this.#sourceDifference(context, source.snapshot);
      if (afterNormalize !== undefined) return afterNormalize;
      return Object.freeze({ status: 'completed', normalizedEdit });
    } catch (error) {
      if (error instanceof WorkspaceBoundaryError) {
        return Object.freeze({ status: 'pathOutsideWorkspace' });
      }
      const response = error instanceof WorkspaceEditNormalizationError
        ? normalizationFailure(error)
        : Object.freeze({ status: 'failed' as const });
      return response.status === 'documentChanged' || response.status === 'editConflict'
        ? Object.freeze({ ...response, files: [request.file] })
        : response;
    }
  }
}

export const createFormatPreviewBridgeHandler = (
  executor: FormatPreviewExecutor,
): MutationBridgeHandler => async (context, workspace, request, signal) => {
  if (request.method !== MUTATION_FORMAT_PREVIEW_BRIDGE_METHOD) return undefined;
  const parsed = parseFormatPreviewBridgeRequest(request.params);
  return canonicalizeJson(await executor.preview(context, workspace, parsed, signal));
};

export const createVscodeFormatPreviewHost = (
  vscode: typeof import('vscode'),
): FormatPreviewHost => {
  const normalizer = createVscodeWorkspaceEditNormalizerHost(vscode);
  return Object.freeze({
    ...normalizer,
    executeCommand: (command: string, ...args: readonly unknown[]) =>
      vscode.commands.executeCommand(command, ...args),
    readFormattingOptions: (document: TextDocument): FormattingOptions => {
      const configuration = vscode.workspace.getConfiguration('editor', document);
      const tabSize = configuration.get<unknown>('tabSize');
      const insertSpaces = configuration.get<unknown>('insertSpaces');
      return Object.freeze({
        ...(typeof tabSize === 'number' ? { tabSize } : {}),
        ...(typeof insertSpaces === 'boolean' ? { insertSpaces } : {}),
      });
    },
  });
};
