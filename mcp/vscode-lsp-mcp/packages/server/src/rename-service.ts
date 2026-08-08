import { Buffer } from 'node:buffer';
import {
  BridgeTransportError,
  MUTATION_CODE_ACTION_PREVIEW_BRIDGE_METHOD,
  MUTATION_CODE_ACTIONS_BRIDGE_METHOD,
  MUTATION_FORMAT_PREVIEW_BRIDGE_METHOD,
  MUTATION_RENAME_PREVIEW_BRIDGE_METHOD,
  canonicalizeJson,
  encodeToolResponse,
  matchesLogicalGlobs,
  normalizeToolInput,
  parseCodeActionPreviewBridgeResponse,
  parseCodeActionsBridgeResponse,
  parseFormatPreviewBridgeResponse,
  parseRenamePreviewBridgeResponse,
  publicTextChangesFromNormalized,
  systemRuntimePrimitives,
  type ActionNotPreviewableDetails,
  type CodeActionPreviewInput,
  type CodeActionsInput,
  type CodeActionSet,
  type DocumentChangedDetails,
  type FormatPreviewInput,
  type JsonObject,
  type Preview,
  type RenamePreviewInput,
  type RuntimePrimitives,
  type ToolError,
  type ToolResponseMap,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  type ActionClaim,
  type MutationCache,
} from './mutation-cache.js';
import {
  MutationApplyService,
  type MutationWorkspaceConnector,
} from './mutation-apply-service.js';
import {
  WorkspaceRoutingError,
  type ConnectedWorkspaceRoute,
} from './workspace-router.js';

const PROVIDER_BRIDGE_TIMEOUT_MS = 95_000;
const RENAME_PREVIEW_BRIDGE_TIMEOUT_MS = 125_000;
const CODE_ACTION_BRIDGE_TIMEOUT_MS = PROVIDER_BRIDGE_TIMEOUT_MS;
const FORMAT_PREVIEW_BRIDGE_TIMEOUT_MS = PROVIDER_BRIDGE_TIMEOUT_MS;

export const RENAME_PREVIEW_LIMITS = Object.freeze({
  changedFiles: 50,
  edits: 100,
  textCharacters: 50_000,
  serializedBytes: 65_536,
});

const RENAME_SCOPE_ERROR_FILE_LIMIT = 10;

export interface RenameWorkspaceConnector extends MutationWorkspaceConnector {
  connectWorkspaceBinding(
    workspaceId: string,
    signal?: AbortSignal,
  ): Promise<ConnectedWorkspaceRoute>;
}

export interface MutationServiceOptions {
  readonly cache: MutationCache;
  readonly clientSessionId: string;
  readonly connector: RenameWorkspaceConnector;
}

const failure = (error: ToolError): { readonly ok: false; readonly error: ToolError } =>
  Object.freeze({ ok: false, error: Object.freeze(error) });

const providerUnavailable = (message: string): ToolResponseMap['rename_preview'] => failure({
  code: 'PROVIDER_UNAVAILABLE',
  message,
  retryable: false,
});

const renameSourceOutsideScope = (): ToolResponseMap['rename_preview'] => failure({
  code: 'INVALID_ARGUMENT',
  message: 'The rename source file is outside includeGlobs or is excluded by excludeGlobs.',
  retryable: false,
  action: 'Choose an explicit scope that includes the source file before requesting a rename preview.',
});

const renameScopeViolation = (
  files: readonly string[],
  totalFiles: number,
  reportedAdditionalFiles = 0,
): ToolResponseMap['rename_preview'] => {
  const visibleFiles = Object.freeze(files.slice(0, RENAME_SCOPE_ERROR_FILE_LIMIT));
  const additionalFiles = reportedAdditionalFiles + files.length - visibleFiles.length;
  const outOfScopeFiles = visibleFiles.length + additionalFiles;
  return failure({
    code: 'RENAME_SCOPE_VIOLATION',
    message: `The rename provider returned ${outOfScopeFiles} file(s) outside the declared path scope; no preview was cached.`,
    retryable: false,
    action: 'Review the listed paths and broaden the glob scope only when every provider target is intentional.',
    details: Object.freeze({
      files: visibleFiles,
      ...(additionalFiles === 0 ? {} : { additionalFiles }),
      totalFiles,
    }),
  });
};

const renameIdentityUnverified = (
  response: Extract<
    ReturnType<typeof parseRenamePreviewBridgeResponse>,
    { readonly status: 'identityRejected' }
  >,
): ToolResponseMap['rename_preview'] => failure({
  code: 'RENAME_IDENTITY_UNVERIFIED',
  message: response.reason === 'mismatchedSymbol' || response.reason === 'textMismatch'
    ? 'The rename provider mixed edits that do not belong to the selected symbol; no preview was cached.'
    : response.reason === 'providerTimedOut'
      ? 'Rename identity verification timed out before every edit could be proven; no preview was cached.'
      : 'The rename provider edit could not be proven to belong to one symbol; no preview was cached.',
  retryable: false,
  action: response.reason === 'budgetExceeded'
    ? 'Choose a symbol with a smaller edit set or use a refactoring workflow that can validate the full change outside MCP.'
    : response.reason === 'providerTimedOut'
      ? 'Wait for language indexing to settle or narrow the declared scope, then retry the preview; do not apply an unverified rename.'
      : 'Use definition and references at the exact source position, then retry only after the language service resolves every edit to the same symbol.',
  details: Object.freeze({
    reason: response.reason,
    checkedEdits: response.checkedEdits,
    totalEdits: response.totalEdits,
    ...(response.files === undefined ? {} : { files: response.files }),
    ...(response.additionalFiles === undefined
      ? {}
      : { additionalFiles: response.additionalFiles }),
  }),
});

const renameNoEdits = (): ToolResponseMap['rename_preview'] => failure({
  code: 'RENAME_NO_EDITS',
  message: 'The rename provider returned no effective text edits; no preview was cached.',
  retryable: false,
  action: 'Confirm the exact symbol position with definition or references and choose a different target when the provider still reports no edits.',
});

const renamePreviewTooLarge = (
  changedFiles: number,
  edits: number,
  textCharacters: number,
  serializedBytes: number,
): ToolResponseMap['rename_preview'] => failure({
  code: 'PREVIEW_TOO_LARGE',
  message: 'The complete rename preview exceeds the safe MCP output budget; no preview was cached.',
  retryable: false,
  action: 'Choose a more specific symbol or use a refactoring workflow that can review a larger complete edit outside MCP context.',
  details: Object.freeze({
    changedFiles,
    edits,
    textCharacters,
    serializedBytes,
    limits: RENAME_PREVIEW_LIMITS,
  }),
});

const routeFailure = (error: unknown): ToolResponseMap['rename_preview'] => {
  if (error instanceof WorkspaceRoutingError) {
    if (error.reason === 'notFound') {
      return failure({
        code: 'WORKSPACE_NOT_FOUND',
        message: 'The requested workspace route was not found.',
        retryable: true,
      });
    }
    if (error.reason === 'timedOut') {
      return failure({
        code: 'PROVIDER_TIMEOUT',
        message: 'The rename provider route timed out before a preview was cached.',
        retryable: true,
      });
    }
    return failure({
      code: 'WORKSPACE_DISCONNECTED',
      message: 'The requested workspace is disconnected.',
      retryable: true,
    });
  }
  if (error instanceof BridgeTransportError) {
    return error.reason === 'timeout'
      ? failure({
          code: 'PROVIDER_TIMEOUT',
          message: 'The rename provider timed out before a preview was cached.',
          retryable: true,
        })
      : failure({
          code: 'WORKSPACE_DISCONNECTED',
          message: 'The requested workspace disconnected before a preview was cached.',
          retryable: true,
        });
  }
  return failure({
    code: 'INTERNAL_ERROR',
    message: 'The rename preview could not be completed.',
    retryable: true,
  });
};

const codeActionListRouteFailure = (error: unknown): ToolResponseMap['code_actions'] => {
  if (error instanceof WorkspaceRoutingError) {
    if (error.reason === 'notFound') {
      return failure({
        code: 'WORKSPACE_NOT_FOUND',
        message: 'The requested workspace route was not found.',
        retryable: true,
      });
    }
    if (error.reason === 'timedOut') {
      return failure({
        code: 'PROVIDER_TIMEOUT',
        message: 'The Code Action provider route timed out.',
        retryable: true,
      });
    }
    return failure({
      code: 'WORKSPACE_DISCONNECTED',
      message: 'The requested workspace is disconnected.',
      retryable: true,
    });
  }
  if (error instanceof BridgeTransportError) {
    return error.reason === 'timeout'
      ? failure({
          code: 'PROVIDER_TIMEOUT',
          message: 'The Code Action provider timed out.',
          retryable: true,
        })
      : failure({
          code: 'WORKSPACE_DISCONNECTED',
          message: 'The requested workspace disconnected while listing Code Actions.',
          retryable: true,
        });
  }
  return failure({
    code: 'INTERNAL_ERROR',
    message: 'Code Actions could not be listed.',
    retryable: true,
  });
};

const codeActionPreviewRouteFailure = (): ToolResponseMap['code_action_preview'] => failure({
  code: 'WORKSPACE_DISCONNECTED',
  message: 'The workspace disconnected before the cached Code Action could be validated.',
  retryable: true,
});

const actionSetNotFound = (): ToolResponseMap['code_action_preview'] => failure({
  code: 'ACTION_SET_NOT_FOUND',
  message: 'The Code Action candidate is unavailable, expired, or has already been consumed.',
  retryable: false,
});

const actionNotPreviewable = (
  reason: ActionNotPreviewableDetails['reason'],
): ToolResponseMap['code_action_preview'] => failure({
  code: 'ACTION_NOT_PREVIEWABLE',
  message: 'The cached Code Action cannot be represented as a safe text-only preview.',
  retryable: false,
  details: Object.freeze({ reason }),
});

const codeActionDocumentChanged = (
  details: DocumentChangedDetails,
): ToolResponseMap['code_action_preview'] => failure({
  code: 'DOCUMENT_CHANGED',
  message: 'A Code Action source or target changed after the candidates were listed.',
  retryable: false,
  details: Object.freeze({
    reason: details.reason,
    ...(details.files === undefined ? {} : { files: details.files }),
    ...(details.additionalFiles === undefined ? {} : { additionalFiles: details.additionalFiles }),
  }),
});

const formatRouteFailure = (error: unknown): ToolResponseMap['format_preview'] => {
  if (error instanceof WorkspaceRoutingError) {
    if (error.reason === 'notFound') {
      return failure({
        code: 'WORKSPACE_NOT_FOUND',
        message: 'The requested workspace route was not found.',
        retryable: true,
      });
    }
    if (error.reason === 'timedOut') {
      return failure({
        code: 'PROVIDER_TIMEOUT',
        message: 'The formatting provider route timed out before a preview was cached.',
        retryable: true,
      });
    }
    return failure({
      code: 'WORKSPACE_DISCONNECTED',
      message: 'The requested workspace is disconnected.',
      retryable: true,
    });
  }
  if (error instanceof BridgeTransportError) {
    return error.reason === 'timeout'
      ? failure({
          code: 'PROVIDER_TIMEOUT',
          message: 'The formatting provider timed out before a preview was cached.',
          retryable: true,
        })
      : failure({
          code: 'WORKSPACE_DISCONNECTED',
          message: 'The requested workspace disconnected before a formatting preview was cached.',
          retryable: true,
        });
  }
  return failure({
    code: 'INTERNAL_ERROR',
    message: 'The formatting preview could not be completed.',
    retryable: true,
  });
};

export const createMutationClientSessionId = (
  primitives: RuntimePrimitives = systemRuntimePrimitives,
): string => {
  const bytes = primitives.secureRandomBytes(16);
  if (!(bytes instanceof Uint8Array) || bytes.byteLength !== 16) {
    throw new Error('Mutation client session CSPRNG returned an invalid byte sequence.');
  }
  return `client_${Buffer.from(bytes).toString('base64url')}`;
};

export class MutationService {
  readonly #applyService: MutationApplyService;
  readonly #cache: MutationCache;
  readonly #clientSessionId: string;
  readonly #connector: RenameWorkspaceConnector;

  constructor(options: MutationServiceOptions) {
    if (options.clientSessionId.length === 0 || options.clientSessionId.length > 512) {
      throw new RangeError('Rename service client session identity is invalid.');
    }
    this.#cache = options.cache;
    this.#clientSessionId = options.clientSessionId;
    this.#connector = options.connector;
    this.#applyService = new MutationApplyService({
      cache: options.cache,
      connector: options.connector,
    });
  }

  #fromBridge(
    input: RenamePreviewInput,
    route: ConnectedWorkspaceRoute,
    value: unknown,
  ): ToolResponseMap['rename_preview'] {
    const response = parseRenamePreviewBridgeResponse(value);
    if (response.status === 'scopeRejected') {
      return renameScopeViolation(
        response.files,
        response.totalFiles,
        response.additionalFiles ?? 0,
      );
    }
    if (response.status === 'completed') {
      const outOfScopeFiles = response.normalizedEdit.textChanges
        .map((change) => change.file)
        .filter((file) => {
          try {
            return !matchesLogicalGlobs(file, input);
          } catch {
            return true;
          }
        })
        .sort();
      if (outOfScopeFiles.length > 0) {
        return renameScopeViolation(outOfScopeFiles, response.normalizedEdit.textChanges.length);
      }

      const changes = publicTextChangesFromNormalized(response.normalizedEdit);
      if (changes.length === 0) return renameNoEdits();
      const changedFiles = changes.length;
      let edits = 0;
      let textCharacters = 0;
      for (const change of changes) {
        edits += change.edits.length;
        for (const edit of change.edits) {
          textCharacters += edit.oldText.length + edit.newText.length;
        }
      }
      const encodedPreview = encodeToolResponse('rename_preview', {
        ok: true,
        data: Object.freeze({
          changes,
          previewId: 'pv_AAAAAAAAAAAAAAAAAAAAAA',
        }),
      });
      const serializedBytes = Buffer.byteLength(encodedPreview.content[0].text, 'utf8');
      if (changedFiles > RENAME_PREVIEW_LIMITS.changedFiles ||
          edits > RENAME_PREVIEW_LIMITS.edits ||
          textCharacters > RENAME_PREVIEW_LIMITS.textCharacters ||
          serializedBytes > RENAME_PREVIEW_LIMITS.serializedBytes) {
        return renamePreviewTooLarge(changedFiles, edits, textCharacters, serializedBytes);
      }

      const committed = this.#cache.commitPreview({
        identity: Object.freeze({
          clientSessionId: this.#clientSessionId,
          workspace: route.workspace,
        }),
        operationKind: 'rename',
        requestSummary: Object.freeze({
          file: input.file,
          line: input.line,
          column: input.column,
          newName: input.newName,
          includeGlobs: input.includeGlobs,
          ...(input.excludeGlobs === undefined ? {} : { excludeGlobs: input.excludeGlobs }),
          ...(input.timeoutMs === undefined ? {} : { timeoutMs: input.timeoutMs }),
        }),
        normalizedEdit: response.normalizedEdit,
      });
      const data: Preview = Object.freeze({
        changes,
        ...(committed.previewId === undefined ? {} : { previewId: committed.previewId }),
      });
      return Object.freeze({ ok: true, data });
    }
    if (response.status === 'workspaceChanged') {
      return failure({
        code: 'WORKSPACE_NOT_FOUND',
        message: 'The workspace identity changed while preparing the rename.',
        retryable: true,
      });
    }
    if (response.status === 'pathOutsideWorkspace') {
      return failure({
        code: 'PATH_OUTSIDE_WORKSPACE',
        message: 'The rename source or one of its targets is outside the selected workspace.',
        retryable: false,
      });
    }
    if (response.status === 'documentNotFound') {
      return failure({
        code: 'DOCUMENT_NOT_FOUND',
        message: 'The rename source document could not be opened.',
        retryable: false,
      });
    }
    if (response.status === 'positionOutOfRange') {
      return failure({
        code: 'POSITION_OUT_OF_RANGE',
        message: 'The rename position is outside the current document snapshot.',
        retryable: false,
      });
    }
    if (response.status === 'timedOut') {
      return failure({
        code: 'PROVIDER_TIMEOUT',
        message: 'The rename provider timed out before a preview was cached.',
        retryable: true,
      });
    }
    if (response.status === 'noEdits') return renameNoEdits();
    if (response.status === 'identityRejected') return renameIdentityUnverified(response);
    if (response.status === 'prepareRejected') {
      return providerUnavailable(response.reason === 'notRenameable'
        ? 'Rename is not available at this position. Move to a renameable symbol and retry.'
        : 'Rename preparation returned an invalid range. Retry after the language service is ready.');
    }
    if (response.status === 'unavailable') {
      return providerUnavailable('No rename provider is available for the source document.');
    }
    if (response.status === 'notReady') {
      return providerUnavailable(
        'The rename provider did not produce a complete edit. Wait for language analysis and retry.',
      );
    }
    if (response.status === 'cancelled') {
      return providerUnavailable('The rename preview was cancelled before an edit was cached.');
    }
    if (response.status === 'documentChanged') {
      return failure({
        code: 'DOCUMENT_CHANGED',
        message: 'A rename document changed while the preview was being created.',
        retryable: false,
        details: Object.freeze({
          reason: response.reason,
          ...(response.files === undefined ? {} : { files: response.files }),
          ...(response.additionalFiles === undefined
            ? {}
            : { additionalFiles: response.additionalFiles }),
        }),
      });
    }
    if (response.status === 'editConflict') {
      return failure({
        code: 'EDIT_CONFLICT',
        message: 'The rename edit cannot be represented as one safe text-only preview.',
        retryable: false,
        details: Object.freeze({
          reason: response.reason,
          ...(response.files === undefined ? {} : { files: response.files }),
          ...(response.additionalFiles === undefined
            ? {}
            : { additionalFiles: response.additionalFiles }),
        }),
      });
    }
    return providerUnavailable('The rename provider could not produce a safe complete preview.');
  }

  #formatFromBridge(
    input: FormatPreviewInput,
    route: ConnectedWorkspaceRoute,
    value: unknown,
  ): ToolResponseMap['format_preview'] {
    const response = parseFormatPreviewBridgeResponse(value);
    if (response.status === 'completed') {
      const requestSummaryValue = canonicalizeJson({
        file: input.file,
        ...(input.range === undefined ? {} : { range: input.range }),
        ...(input.options === undefined ? {} : { options: input.options }),
      });
      if (requestSummaryValue === null || Array.isArray(requestSummaryValue) ||
          typeof requestSummaryValue !== 'object') {
        throw new TypeError('Format preview request summary could not be encoded.');
      }
      const committed = this.#cache.commitPreview({
        identity: Object.freeze({
          clientSessionId: this.#clientSessionId,
          workspace: route.workspace,
        }),
        operationKind: 'format',
        requestSummary: requestSummaryValue as JsonObject,
        normalizedEdit: response.normalizedEdit,
      });
      const data: Preview = Object.freeze({
        changes: publicTextChangesFromNormalized(response.normalizedEdit),
        ...(committed.previewId === undefined ? {} : { previewId: committed.previewId }),
      });
      return Object.freeze({ ok: true, data });
    }
    if (response.status === 'workspaceChanged') {
      return failure({
        code: 'WORKSPACE_NOT_FOUND',
        message: 'The workspace identity changed while preparing the formatting preview.',
        retryable: true,
      });
    }
    if (response.status === 'pathOutsideWorkspace') {
      return failure({
        code: 'PATH_OUTSIDE_WORKSPACE',
        message: 'The formatting source or target is outside the selected workspace.',
        retryable: false,
      });
    }
    if (response.status === 'documentNotFound') {
      return failure({
        code: 'DOCUMENT_NOT_FOUND',
        message: 'The formatting source document could not be opened.',
        retryable: false,
      });
    }
    if (response.status === 'positionOutOfRange') {
      return failure({
        code: 'POSITION_OUT_OF_RANGE',
        message: 'The formatting range is outside the current document snapshot.',
        retryable: false,
      });
    }
    if (response.status === 'timedOut') {
      return failure({
        code: 'PROVIDER_TIMEOUT',
        message: 'The formatting provider timed out before a preview was cached.',
        retryable: true,
      });
    }
    if (response.status === 'documentChanged') {
      return failure({
        code: 'DOCUMENT_CHANGED',
        message: 'The document changed while the formatting preview was being created.',
        retryable: false,
        details: Object.freeze({
          reason: response.reason,
          ...(response.files === undefined ? {} : { files: response.files }),
          ...(response.additionalFiles === undefined
            ? {}
            : { additionalFiles: response.additionalFiles }),
        }),
      });
    }
    if (response.status === 'editConflict') {
      return failure({
        code: 'EDIT_CONFLICT',
        message: 'The formatting edit cannot be represented as one safe text-only preview.',
        retryable: false,
        details: Object.freeze({
          reason: response.reason,
          ...(response.files === undefined ? {} : { files: response.files }),
          ...(response.additionalFiles === undefined
            ? {}
            : { additionalFiles: response.additionalFiles }),
        }),
      });
    }
    if (response.status === 'unavailable') {
      return failure({
        code: 'PROVIDER_UNAVAILABLE',
        message: 'No formatting provider is available for the source document.',
        retryable: false,
      });
    }
    if (response.status === 'notReady') {
      return failure({
        code: 'PROVIDER_UNAVAILABLE',
        message: 'The formatting provider is not ready. Wait for language analysis and retry.',
        retryable: false,
      });
    }
    if (response.status === 'cancelled') {
      return failure({
        code: 'PROVIDER_UNAVAILABLE',
        message: 'The formatting preview was cancelled before an edit was cached.',
        retryable: false,
      });
    }
    return failure({
      code: 'PROVIDER_UNAVAILABLE',
      message: 'The formatting provider could not produce a safe complete preview.',
      retryable: false,
    });
  }

  #codeActionsFromBridge(
    input: CodeActionsInput,
    route: ConnectedWorkspaceRoute,
    value: unknown,
  ): ToolResponseMap['code_actions'] {
    const response = parseCodeActionsBridgeResponse(value);
    if (response.status === 'completed') {
      const requestSummaryValue = canonicalizeJson({
        file: input.file,
        range: input.range,
        ...(input.onlyKinds === undefined ? {} : { onlyKinds: input.onlyKinds }),
        resultStart: input.resultStart,
        resultEnd: input.resultEnd,
      });
      if (requestSummaryValue === null || Array.isArray(requestSummaryValue) ||
          typeof requestSummaryValue !== 'object') {
        throw new TypeError('Code Action request summary could not be encoded.');
      }
      const committed = this.#cache.commitActionSet({
        identity: Object.freeze({
          clientSessionId: this.#clientSessionId,
          workspace: route.workspace,
        }),
        requestSummary: requestSummaryValue as JsonObject,
        sourceSnapshot: response.sourceSnapshot,
        candidates: response.candidates.map((candidate) => Object.freeze({
          title: candidate.title,
          ...(candidate.kind === undefined ? {} : { kind: candidate.kind }),
          normalizedEdit: candidate.normalizedEdit,
        })),
        available: response.available,
      });
      const data: CodeActionSet = Object.freeze({
        ...(committed.actionSetId === undefined ? {} : { actionSetId: committed.actionSetId }),
        results: committed.actions,
        available: committed.available,
        ...(response.warnings === undefined ? {} : { warnings: response.warnings }),
      });
      return Object.freeze({ ok: true, data });
    }
    if (response.status === 'workspaceChanged') {
      return failure({
        code: 'WORKSPACE_NOT_FOUND',
        message: 'The workspace identity changed while listing Code Actions.',
        retryable: true,
      });
    }
    if (response.status === 'pathOutsideWorkspace') {
      return failure({
        code: 'PATH_OUTSIDE_WORKSPACE',
        message: 'The Code Action source is outside the selected workspace.',
        retryable: false,
      });
    }
    if (response.status === 'documentNotFound') {
      return failure({
        code: 'DOCUMENT_NOT_FOUND',
        message: 'The Code Action source document could not be opened.',
        retryable: false,
      });
    }
    if (response.status === 'positionOutOfRange') {
      return failure({
        code: 'POSITION_OUT_OF_RANGE',
        message: 'The Code Action range is outside the current document snapshot.',
        retryable: false,
      });
    }
    if (response.status === 'timedOut') {
      return failure({
        code: 'PROVIDER_TIMEOUT',
        message: 'The Code Action provider timed out.',
        retryable: true,
      });
    }
    if (response.status === 'documentChanged') {
      return failure({
        code: 'DOCUMENT_CHANGED',
        message: 'The Code Action source changed while candidates were being listed.',
        retryable: false,
        details: Object.freeze({
          reason: response.reason,
          ...(response.files === undefined ? {} : { files: response.files }),
          ...(response.additionalFiles === undefined
            ? {}
            : { additionalFiles: response.additionalFiles }),
        }),
      });
    }
    if (response.status === 'unavailable') {
      return failure({
        code: 'PROVIDER_UNAVAILABLE',
        message: 'No Code Action provider is available for the source document.',
        retryable: false,
      });
    }
    if (response.status === 'notReady') {
      return failure({
        code: 'PROVIDER_UNAVAILABLE',
        message: 'The Code Action provider is not ready. Wait for language analysis and retry.',
        retryable: false,
      });
    }
    if (response.status === 'cancelled') {
      return failure({
        code: 'PROVIDER_UNAVAILABLE',
        message: 'The Code Action request was cancelled before candidates were cached.',
        retryable: false,
      });
    }
    return failure({
      code: 'PROVIDER_UNAVAILABLE',
      message: 'The Code Action provider returned an invalid or unsafe result.',
      retryable: false,
    });
  }

  #codeActionPreviewFromBridge(
    claim: ActionClaim,
    value: unknown,
  ): ToolResponseMap['code_action_preview'] {
    const response = parseCodeActionPreviewBridgeResponse(value);
    if (response.status === 'ready') {
      const committed = this.#cache.commitPreview({
        identity: Object.freeze({
          clientSessionId: this.#clientSessionId,
          workspace: claim.identity.workspace,
        }),
        operationKind: 'codeAction',
        requestSummary: Object.freeze({
          actionSetId: claim.actionSetId,
          actionId: claim.action.actionId,
          title: claim.action.title,
          ...(claim.action.kind === undefined ? {} : { kind: claim.action.kind }),
        }),
        normalizedEdit: claim.action.normalizedEdit,
      });
      const data: Preview = Object.freeze({
        changes: publicTextChangesFromNormalized(claim.action.normalizedEdit),
        ...(committed.previewId === undefined ? {} : { previewId: committed.previewId }),
      });
      return Object.freeze({ ok: true, data });
    }
    if (response.status === 'actionNotPreviewable') {
      return actionNotPreviewable(response.reason);
    }
    if (response.status === 'documentChanged') {
      this.#cache.invalidateActionSet(claim);
      return codeActionDocumentChanged(response);
    }
    if (response.status === 'workspaceChanged') {
      this.#cache.invalidateActionSet(claim);
      return failure({
        code: 'WORKSPACE_NOT_FOUND',
        message: 'The workspace identity changed after the Code Actions were listed.',
        retryable: true,
      });
    }
    if (response.status === 'pathOutsideWorkspace') {
      this.#cache.invalidateActionSet(claim);
      return failure({
        code: 'PATH_OUTSIDE_WORKSPACE',
        message: 'A cached Code Action target is outside the selected workspace.',
        retryable: false,
      });
    }
    this.#cache.invalidateActionSet(claim);
    return actionNotPreviewable('cachedActionInvalid');
  }

  async codeActions(
    inputValue: unknown,
    signal?: AbortSignal,
  ): Promise<ToolResponseMap['code_actions']> {
    const input = normalizeToolInput('code_actions', inputValue);
    let route: ConnectedWorkspaceRoute;
    try {
      route = await this.#connector.connectWorkspaceBinding(input.workspaceId, signal);
    } catch (error) {
      return codeActionListRouteFailure(error);
    }
    try {
      const params = canonicalizeJson({
        workspace: route.workspace,
        file: input.file,
        range: input.range,
        ...(input.onlyKinds === undefined ? {} : { onlyKinds: input.onlyKinds }),
        resultStart: input.resultStart,
        resultEnd: input.resultEnd,
      });
      if (params === null || Array.isArray(params) || typeof params !== 'object') {
        return failure({
          code: 'INTERNAL_ERROR',
          message: 'The Code Action request could not be encoded.',
          retryable: true,
        });
      }
      const response = await route.session.call(
        MUTATION_CODE_ACTIONS_BRIDGE_METHOD,
        params as JsonObject,
        {
          deadlineAt: Date.now() + CODE_ACTION_BRIDGE_TIMEOUT_MS,
          maximumTimeoutMs: CODE_ACTION_BRIDGE_TIMEOUT_MS,
          ...(signal === undefined ? {} : { signal }),
        },
      );
      return this.#codeActionsFromBridge(input, route, response);
    } catch (error) {
      return codeActionListRouteFailure(error);
    } finally {
      await route.session.close().catch(() => undefined);
    }
  }

  async codeActionPreview(
    inputValue: unknown,
    signal?: AbortSignal,
  ): Promise<ToolResponseMap['code_action_preview']> {
    const input: CodeActionPreviewInput = normalizeToolInput('code_action_preview', inputValue);
    const claimed = this.#cache.claimActionForClient(
      this.#clientSessionId,
      input.actionSetId,
      input.actionId,
    );
    if (claimed.status !== 'claimed') return actionSetNotFound();

    let session;
    try {
      session = await this.#connector.connectWorkspaceRoute(claimed.claim.identity.workspace, signal);
    } catch {
      return codeActionPreviewRouteFailure();
    }
    try {
      const params = canonicalizeJson({
        workspace: claimed.claim.identity.workspace,
        sourceSnapshot: claimed.claim.sourceSnapshot,
        normalizedEdit: claimed.claim.action.normalizedEdit,
      });
      if (params === null || Array.isArray(params) || typeof params !== 'object') {
        this.#cache.invalidateActionSet(claimed.claim);
        return actionNotPreviewable('cachedActionInvalid');
      }
      const response = await session.call(
        MUTATION_CODE_ACTION_PREVIEW_BRIDGE_METHOD,
        params as JsonObject,
        {
          deadlineAt: Date.now() + CODE_ACTION_BRIDGE_TIMEOUT_MS,
          maximumTimeoutMs: CODE_ACTION_BRIDGE_TIMEOUT_MS,
          ...(signal === undefined ? {} : { signal }),
        },
      );
      try {
        return this.#codeActionPreviewFromBridge(claimed.claim, response);
      } catch {
        this.#cache.invalidateActionSet(claimed.claim);
        return actionNotPreviewable('cachedActionInvalid');
      }
    } catch {
      return codeActionPreviewRouteFailure();
    } finally {
      await session.close().catch(() => undefined);
    }
  }

  codeActionApply(
    inputValue: unknown,
    signal?: AbortSignal,
  ): Promise<ToolResponseMap['code_action_apply']> {
    const input = normalizeToolInput('code_action_apply', inputValue);
    return this.#applyService.applyPreview(
      this.#clientSessionId,
      input.previewId,
      'codeAction',
      signal === undefined ? {} : { signal },
    );
  }

  async formatPreview(
    inputValue: unknown,
    signal?: AbortSignal,
  ): Promise<ToolResponseMap['format_preview']> {
    const input = normalizeToolInput('format_preview', inputValue);
    let route: ConnectedWorkspaceRoute;
    try {
      route = await this.#connector.connectWorkspaceBinding(input.workspaceId, signal);
    } catch (error) {
      return formatRouteFailure(error);
    }
    try {
      const params = canonicalizeJson({
        workspace: route.workspace,
        file: input.file,
        ...(input.range === undefined ? {} : { range: input.range }),
        ...(input.options === undefined ? {} : { options: input.options }),
      });
      if (params === null || Array.isArray(params) || typeof params !== 'object') {
        return failure({
          code: 'INTERNAL_ERROR',
          message: 'The formatting preview request could not be encoded.',
          retryable: true,
        });
      }
      const response = await route.session.call(
        MUTATION_FORMAT_PREVIEW_BRIDGE_METHOD,
        params as JsonObject,
        {
          deadlineAt: Date.now() + FORMAT_PREVIEW_BRIDGE_TIMEOUT_MS,
          maximumTimeoutMs: FORMAT_PREVIEW_BRIDGE_TIMEOUT_MS,
          ...(signal === undefined ? {} : { signal }),
        },
      );
      return this.#formatFromBridge(input, route, response);
    } catch (error) {
      return formatRouteFailure(error);
    } finally {
      await route.session.close().catch(() => undefined);
    }
  }

  formatApply(
    inputValue: unknown,
    signal?: AbortSignal,
  ): Promise<ToolResponseMap['format_apply']> {
    const input = normalizeToolInput('format_apply', inputValue);
    return this.#applyService.applyPreview(
      this.#clientSessionId,
      input.previewId,
      'format',
      signal === undefined ? {} : { signal },
    );
  }

  async renamePreview(
    inputValue: unknown,
    signal?: AbortSignal,
  ): Promise<ToolResponseMap['rename_preview']> {
    const input = normalizeToolInput('rename_preview', inputValue);
    if (!matchesLogicalGlobs(input.file, input)) return renameSourceOutsideScope();
    let route: ConnectedWorkspaceRoute;
    try {
      route = await this.#connector.connectWorkspaceBinding(input.workspaceId, signal);
    } catch (error) {
      return routeFailure(error);
    }
    try {
      const params = canonicalizeJson({
        workspace: route.workspace,
        file: input.file,
        line: input.line,
        column: input.column,
        newName: input.newName,
        includeGlobs: input.includeGlobs,
        ...(input.excludeGlobs === undefined ? {} : { excludeGlobs: input.excludeGlobs }),
        ...(input.timeoutMs === undefined ? {} : { timeoutMs: input.timeoutMs }),
      });
      if (params === null || Array.isArray(params) || typeof params !== 'object') {
        return failure({
          code: 'INTERNAL_ERROR',
          message: 'The rename preview request could not be encoded.',
          retryable: true,
        });
      }
      const response = await route.session.call(
        MUTATION_RENAME_PREVIEW_BRIDGE_METHOD,
        params as JsonObject,
        {
          deadlineAt: Date.now() + RENAME_PREVIEW_BRIDGE_TIMEOUT_MS,
          maximumTimeoutMs: RENAME_PREVIEW_BRIDGE_TIMEOUT_MS,
          ...(signal === undefined ? {} : { signal }),
        },
      );
      return this.#fromBridge(input, route, response);
    } catch (error) {
      return routeFailure(error);
    } finally {
      await route.session.close().catch(() => undefined);
    }
  }

  renameApply(
    inputValue: unknown,
    signal?: AbortSignal,
  ): Promise<ToolResponseMap['rename_apply']> {
    const input = normalizeToolInput('rename_apply', inputValue);
    return this.#applyService.applyPreview(
      this.#clientSessionId,
      input.previewId,
      'rename',
      signal === undefined ? {} : { signal },
    );
  }
}
