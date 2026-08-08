import type {
  Position as VscodePosition,
  Range as VscodeRange,
  TextEdit as VscodeTextEdit,
} from 'vscode';
import {
  CODE_ACTION_RAW_LIMIT,
  CODE_ACTION_RESOLVE_LIMIT,
  MUTATION_CODE_ACTION_PREVIEW_BRIDGE_METHOD,
  MUTATION_CODE_ACTIONS_BRIDGE_METHOD,
  WorkspaceBoundaryError,
  canonicalizeJson,
  parseCodeActionPreviewBridgeRequest,
  parseCodeActionsBridgeRequest,
  systemWorkspacePathAccess,
  type CodeActionBridgeCandidate,
  type CodeActionPreviewBridgeRequest,
  type CodeActionPreviewBridgeResponse,
  type CodeActionsBridgeRequest,
  type CodeActionsBridgeResponse,
  type NormalizedWorkspaceEdit,
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
  type ProviderWorkspaceEdit,
  type WorkspaceEditNormalizerHost,
} from './workspace-edit-normalizer.js';
import {
  MutationApplyExecutor,
  type MutationBridgeHandler,
} from './mutation-apply-provider.js';

interface ProviderBatch {
  readonly total: number;
  readonly truncated: boolean;
  readonly values: readonly unknown[];
}

interface PreparedCandidate extends CodeActionBridgeCandidate {
  readonly key: string;
  readonly ordinal: number;
}

interface ZeroBasedPoint {
  readonly line: number;
  readonly character: number;
}

interface ZeroBasedRange {
  readonly start: ZeroBasedPoint;
  readonly end: ZeroBasedPoint;
}

type SourceSnapshotIssue =
  | Extract<CodeActionsBridgeResponse, { readonly status: 'pathOutsideWorkspace' }>
  | Extract<CodeActionsBridgeResponse, { readonly status: 'documentChanged' }>;

export interface CodeActionProviderHost extends WorkspaceEditNormalizerHost {
  createRange(range: ZeroBasedRange): VscodeRange;
  executeCommand(command: string, ...args: readonly unknown[]): PromiseLike<unknown>;
}

export interface CodeActionProviderOptions {
  readonly applyExecutor: MutationApplyExecutor;
  readonly defaultTimeoutMs?: number;
  readonly epochTracker: DocumentEpochTracker;
  readonly pathAccess?: WorkspacePathAccess;
}

const asRecord = (value: unknown): Record<string, unknown> | undefined =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;

const sameWorkspace = (
  active: WorkspaceRouteIdentity,
  expected: WorkspaceRouteIdentity,
): boolean => active.workspaceId === expected.workspaceId && active.generation === expected.generation;

const samePoint = (left: ZeroBasedPoint, right: VscodePosition): boolean =>
  left.line === right.line && left.character === right.character;

const sameRange = (left: ZeroBasedRange, right: VscodeRange): boolean =>
  samePoint(left.start, right.start) && samePoint(left.end, right.end);

const compareText = (left: string, right: string): number =>
  left < right ? -1 : left > right ? 1 : 0;

const boundedTitle = (value: unknown): string | undefined => {
  if (typeof value !== 'string') return undefined;
  const normalized = value.replaceAll('\r', ' ').replaceAll('\n', ' ').trim();
  return normalized.length === 0 || normalized.length > 4_096 ? undefined : normalized;
};

const actionKind = (value: unknown): string | undefined => {
  const raw = typeof value === 'string' ? value : asRecord(value)?.value;
  return typeof raw === 'string' && raw.length > 0 && raw.length <= 1_024 ? raw : undefined;
};

const matchesOnlyKinds = (
  kind: string | undefined,
  onlyKinds: readonly string[] | undefined,
): boolean => onlyKinds === undefined || (kind !== undefined && onlyKinds.some((only) =>
  kind === only || kind.startsWith(`${only}.`)));

const isProviderWorkspaceEdit = (value: unknown): value is ProviderWorkspaceEdit => {
  const record = asRecord(value);
  return record !== undefined && Number.isSafeInteger(record.size) &&
    (record.size as number) >= 0 && typeof record.entries === 'function';
};

const codeActionAdapter = (
  providerRange: VscodeRange,
): ProviderCommandAdapter<null, ProviderBatch> => ({
  command: 'vscode.executeCodeActionProvider',
  requiresDocument: true,
  buildArguments: (_input, document) => {
    if (document === undefined) throw new RangeError('Code Action document was not activated.');
    return [document.uri, providerRange, undefined, CODE_ACTION_RESOLVE_LIMIT];
  },
  classifyResult: (value) => {
    if (value === undefined) return { status: 'notReady' };
    if (!Array.isArray(value)) return { status: 'invalid' };
    return {
      status: 'ready',
      value: Object.freeze({
        total: value.length,
        truncated: value.length > CODE_ACTION_RAW_LIMIT,
        values: Object.freeze(value.slice(0, CODE_ACTION_RAW_LIMIT)),
      }),
    };
  },
});

const documentChanged = (
  reason: 'content' | 'version' | 'existence' | 'workspace',
  file: string,
): Extract<CodeActionsBridgeResponse, { readonly status: 'documentChanged' }> =>
  Object.freeze({ status: 'documentChanged', reason, files: Object.freeze([file]) });

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

const providerFailure = (
  result: ProviderInvocationResult<ProviderBatch>,
): CodeActionsBridgeResponse => {
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

const warningForNormalization = (error: WorkspaceEditNormalizationError): string =>
  error.reason === 'documentChangedDuringCapture'
    ? 'code_action_document_changed'
    : 'code_action_unsupported_edit_filtered';

const candidateKey = (
  title: string,
  kind: string | undefined,
  normalizedEdit: NormalizedWorkspaceEdit,
): string => JSON.stringify({ title, kind: kind ?? null, normalizedEdit });

const compareCandidates = (left: PreparedCandidate, right: PreparedCandidate): number =>
  Number(right.preferred) - Number(left.preferred) ||
  left.ordinal - right.ordinal;

export class CodeActionProviderBridge {
  readonly #applyExecutor: MutationApplyExecutor;
  readonly #host: CodeActionProviderHost;
  readonly #normalizer: WorkspaceEditNormalizer;
  readonly #pathAccess: WorkspacePathAccess;
  readonly #runtime: ProviderRuntime;

  constructor(host: CodeActionProviderHost, options: CodeActionProviderOptions) {
    this.#host = host;
    this.#applyExecutor = options.applyExecutor;
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

  async #captureInitialSource(
    context: WorkspacePathContext,
    file: string,
  ): Promise<
    | Awaited<ReturnType<WorkspaceEditNormalizer['captureDocument']>>
    | CodeActionsBridgeResponse
  > {
    try {
      return await this.#normalizer.captureDocument(context, file);
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
  }

  #providerRange(
    source: Awaited<ReturnType<WorkspaceEditNormalizer['captureDocument']>>,
    input: CodeActionsBridgeRequest,
  ): VscodeRange | undefined {
    const raw: ZeroBasedRange = {
      start: {
        line: input.range.startLine - 1,
        character: input.range.startColumn - 1,
      },
      end: {
        line: input.range.endLine - 1,
        character: input.range.endColumn - 1,
      },
    };
    try {
      const validated = source.document.validateRange(this.#host.createRange(raw));
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

  async #currentSourceDifference(
    context: WorkspacePathContext,
    sourceSnapshot: TextDocumentSnapshot,
  ): Promise<SourceSnapshotIssue | undefined> {
    try {
      const current = await this.#normalizer.captureDocument(context, sourceSnapshot.file);
      const difference = snapshotDifference(sourceSnapshot, current.snapshot);
      return difference === undefined
        ? undefined
        : documentChanged(difference, sourceSnapshot.file);
    } catch (error) {
      if (error instanceof WorkspaceBoundaryError && error.code === 'PATH_OUTSIDE_WORKSPACE') {
        return Object.freeze({ status: 'pathOutsideWorkspace' });
      }
      return documentChanged(
        error instanceof WorkspaceBoundaryError && error.code === 'DOCUMENT_NOT_FOUND'
          ? 'existence'
          : 'workspace',
        sourceSnapshot.file,
      );
    }
  }

  async #list(
    context: WorkspacePathContext,
    activeWorkspace: WorkspaceRouteIdentity,
    input: CodeActionsBridgeRequest,
    signal: AbortSignal,
  ): Promise<CodeActionsBridgeResponse> {
    if (!sameWorkspace(activeWorkspace, input.workspace)) {
      return Object.freeze({ status: 'workspaceChanged' });
    }
    const source = await this.#captureInitialSource(context, input.file);
    if ('status' in source) return source;
    const providerRange = this.#providerRange(source, input);
    if (providerRange === undefined) return Object.freeze({ status: 'positionOutOfRange' });

    let invocation: ProviderInvocationResult<ProviderBatch>;
    try {
      invocation = await this.#runtime.invoke(
        context,
        codeActionAdapter(providerRange),
        null,
        { logicalFile: input.file, signal },
      );
    } catch (error) {
      return error instanceof WorkspaceBoundaryError
        ? Object.freeze({ status: 'pathOutsideWorkspace' })
        : Object.freeze({ status: 'failed' });
    }
    if (invocation.status !== 'completed') return providerFailure(invocation);

    const warnings = new Set<string>();
    if (invocation.value.truncated || invocation.value.total > CODE_ACTION_RESOLVE_LIMIT) {
      warnings.add('code_action_resolution_limited');
    }
    const candidates: PreparedCandidate[] = [];
    for (const [ordinal, raw] of invocation.value.values.entries()) {
      if (signal.aborted) return Object.freeze({ status: 'cancelled' });
      const record = asRecord(raw);
      const title = boundedTitle(record?.title);
      if (record === undefined || title === undefined) {
        warnings.add('code_action_invalid_candidate_filtered');
        continue;
      }
      if (record.disabled !== undefined) {
        warnings.add('code_action_disabled_filtered');
        continue;
      }
      if (record.command !== undefined) {
        warnings.add('code_action_command_filtered');
        continue;
      }
      const kind = actionKind(record.kind);
      if (!matchesOnlyKinds(kind, input.onlyKinds)) continue;
      if (record.edit === undefined) {
        warnings.add('code_action_missing_edit_filtered');
        continue;
      }
      if (!isProviderWorkspaceEdit(record.edit)) {
        warnings.add('code_action_unsupported_edit_filtered');
        continue;
      }
      let normalizedEdit: NormalizedWorkspaceEdit;
      try {
        normalizedEdit = await this.#normalizer.normalize(context, record.edit);
      } catch (error) {
        if (error instanceof WorkspaceBoundaryError) {
          warnings.add('code_action_outside_workspace_filtered');
          continue;
        }
        if (error instanceof WorkspaceEditNormalizationError) {
          const warning = warningForNormalization(error);
          if (warning === 'code_action_document_changed') {
            return documentChanged('content', input.file);
          }
          warnings.add(warning);
          continue;
        }
        warnings.add('code_action_invalid_candidate_filtered');
        continue;
      }
      if (normalizedEdit.textChanges.length === 0) {
        warnings.add('code_action_missing_edit_filtered');
        continue;
      }
      candidates.push(Object.freeze({
        title,
        ...(kind === undefined ? {} : { kind }),
        preferred: record.isPreferred === true,
        normalizedEdit,
        key: candidateKey(title, kind, normalizedEdit),
        ordinal,
      }));
    }

    const sourceIssue = await this.#currentSourceDifference(context, source.snapshot);
    if (sourceIssue !== undefined) return sourceIssue;
    const seen = new Set<string>();
    const sorted = candidates.sort(compareCandidates).filter((candidate) => {
      if (seen.has(candidate.key)) return false;
      seen.add(candidate.key);
      return true;
    });
    const available = sorted.length;
    const selected = sorted.slice(input.resultStart - 1, input.resultEnd).map((candidate) =>
      Object.freeze({
        title: candidate.title,
        ...(candidate.kind === undefined ? {} : { kind: candidate.kind }),
        preferred: candidate.preferred,
        normalizedEdit: candidate.normalizedEdit,
      }));
    const publicWarnings = warnings.size === 0
      ? undefined
      : Object.freeze([...warnings].sort(compareText));
    return Object.freeze({
      status: 'completed',
      sourceSnapshot: source.snapshot,
      candidates: Object.freeze(selected),
      available,
      ...(publicWarnings === undefined ? {} : { warnings: publicWarnings }),
    });
  }

  async #preview(
    context: WorkspacePathContext,
    activeWorkspace: WorkspaceRouteIdentity,
    input: CodeActionPreviewBridgeRequest,
  ): Promise<CodeActionPreviewBridgeResponse> {
    if (!sameWorkspace(activeWorkspace, input.workspace)) {
      return Object.freeze({ status: 'workspaceChanged' });
    }
    const sourceIssue = await this.#currentSourceDifference(context, input.sourceSnapshot);
    if (sourceIssue !== undefined) return sourceIssue;
    try {
      const validated = await this.#applyExecutor.validateNormalizedEdit(
        context,
        activeWorkspace,
        input.workspace,
        input.normalizedEdit,
      );
      if (validated.status === 'ready') return Object.freeze({ status: 'ready' });
      if (validated.status === 'workspaceChanged' ||
          validated.status === 'pathOutsideWorkspace' ||
          validated.status === 'documentChanged') {
        return validated;
      }
      if (validated.status === 'editConflict') {
        return Object.freeze({ status: 'actionNotPreviewable', reason: 'cachedActionInvalid' });
      }
      return Object.freeze({ status: 'failed' });
    } catch {
      return Object.freeze({ status: 'failed' });
    }
  }

  handle: MutationBridgeHandler = async (context, workspace, request, signal) => {
    if (request.method === MUTATION_CODE_ACTIONS_BRIDGE_METHOD) {
      return canonicalizeJson(await this.#list(
        context,
        workspace,
        parseCodeActionsBridgeRequest(request.params),
        signal,
      ));
    }
    if (request.method === MUTATION_CODE_ACTION_PREVIEW_BRIDGE_METHOD) {
      return canonicalizeJson(await this.#preview(
        context,
        workspace,
        parseCodeActionPreviewBridgeRequest(request.params),
      ));
    }
    return undefined;
  };
}

export const createCodeActionBridgeHandler = (
  host: CodeActionProviderHost,
  options: CodeActionProviderOptions,
): MutationBridgeHandler => new CodeActionProviderBridge(host, options).handle;

export const createVscodeCodeActionProviderHost = (
  vscode: typeof import('vscode'),
): CodeActionProviderHost => {
  const normalizer = createVscodeWorkspaceEditNormalizerHost(vscode);
  return Object.freeze({
    ...normalizer,
    createRange: (range: ZeroBasedRange): VscodeRange => new vscode.Range(
      range.start.line,
      range.start.character,
      range.end.line,
      range.end.character,
    ),
    executeCommand: (command: string, ...args: readonly unknown[]) =>
      vscode.commands.executeCommand(command, ...args),
    isTextEdit: (value: unknown): value is VscodeTextEdit => normalizer.isTextEdit(value),
  });
};
