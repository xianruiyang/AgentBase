import {
  MUTATION_APPLY_BRIDGE_METHOD,
  canonicalizeJson,
  parseMutationApplyBridgeResponse,
  type ApplyResult,
  type JsonObject,
  type ToolEnvelope,
  type ToolError,
  type WorkspaceRouteIdentity,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  type MutationCache,
  type MutationOperationKind,
  type PreviewClaim,
  type PreviewPeekResult,
} from './mutation-cache.js';
import {
  WorkspaceRoutingError,
  type BridgeProbeSession,
} from './workspace-router.js';

export interface MutationWorkspaceConnector {
  connectWorkspaceRoute(
    workspace: WorkspaceRouteIdentity,
    signal?: AbortSignal,
  ): Promise<BridgeProbeSession>;
}

export interface MutationApplyServiceOptions {
  readonly cache: MutationCache;
  readonly connector: MutationWorkspaceConnector;
}

export interface MutationApplyCallOptions {
  readonly signal?: AbortSignal;
}

const success = (changedFiles: readonly string[]): ToolEnvelope<ApplyResult> => Object.freeze({
  ok: true,
  data: Object.freeze({ changedFiles: Object.freeze([...changedFiles]) }),
});

const failure = (error: ToolError): ToolEnvelope<ApplyResult> => Object.freeze({
  ok: false,
  error: Object.freeze(error),
});

const previewNotFound = (): ToolEnvelope<ApplyResult> => failure({
  code: 'PREVIEW_NOT_FOUND',
  message: 'The preview is unavailable or has already been consumed.',
  retryable: false,
});

const previewExpired = (): ToolEnvelope<ApplyResult> => failure({
  code: 'PREVIEW_EXPIRED',
  message: 'The preview has expired.',
  retryable: false,
});

const preflightDisconnected = (): ToolEnvelope<ApplyResult> => failure({
  code: 'WORKSPACE_DISCONNECTED',
  message: 'The workspace route is not currently connected.',
  retryable: true,
  details: Object.freeze({ phase: 'preflight', outcome: 'notStarted' }),
});

const applyOutcomeUnknown = (): ToolEnvelope<ApplyResult> => failure({
  code: 'WORKSPACE_DISCONNECTED',
  message: 'The mutation outcome could not be verified.',
  retryable: false,
  details: Object.freeze({ phase: 'apply', outcome: 'unknown' }),
});

const fromLookup = (result: PreviewPeekResult): ToolEnvelope<ApplyResult> | undefined =>
  result.status === 'notFound'
    ? previewNotFound()
    : result.status === 'expired'
      ? previewExpired()
      : undefined;

export class MutationApplyService {
  readonly #cache: MutationCache;
  readonly #connector: MutationWorkspaceConnector;

  constructor(options: MutationApplyServiceOptions) {
    this.#cache = options.cache;
    this.#connector = options.connector;
  }

  #complete(claim: PreviewClaim): void {
    if (!this.#cache.completePreviewClaim(claim)) {
      throw new Error('Mutation preview claim completion failed.');
    }
  }

  #mapBridgeResponse(value: unknown): ToolEnvelope<ApplyResult> {
    const response = parseMutationApplyBridgeResponse(value);
    if (response.status === 'applied') return success(response.changedFiles);
    if (response.status === 'workspaceChanged') return previewNotFound();
    if (response.status === 'pathOutsideWorkspace') {
      return failure({
        code: 'PATH_OUTSIDE_WORKSPACE',
        message: 'A mutation target is outside the selected workspace.',
        retryable: false,
      });
    }
    if (response.status === 'documentChanged') {
      return failure({
        code: 'DOCUMENT_CHANGED',
        message: 'A mutation target changed after the preview was created.',
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
        message: 'The cached text edits are no longer safe to apply.',
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
    return failure({
      code: 'APPLY_FAILED',
      message: 'VS Code could not confirm the complete mutation.',
      retryable: false,
      details: Object.freeze({ stage: response.stage, outcome: response.outcome }),
    });
  }

  async applyPreview(
    clientSessionId: string,
    previewId: string,
    operationKind: MutationOperationKind,
    options: MutationApplyCallOptions = {},
  ): Promise<ToolEnvelope<ApplyResult>> {
    const lookup = this.#cache.peekPreviewForClient(clientSessionId, previewId);
    const lookupFailure = fromLookup(lookup);
    if (lookupFailure !== undefined) return lookupFailure;
    if (lookup.status !== 'active') return previewNotFound();
    if (lookup.preview.operationKind !== operationKind) return previewNotFound();

    let session: BridgeProbeSession;
    try {
      session = await this.#connector.connectWorkspaceRoute(
        lookup.preview.identity.workspace,
        options.signal,
      );
    } catch (error) {
      const current = this.#cache.peekPreviewForClient(clientSessionId, previewId);
      const currentFailure = fromLookup(current);
      if (currentFailure !== undefined) return currentFailure;
      if (error instanceof WorkspaceRoutingError && error.reason === 'notFound') {
        const stale = this.#cache.claimPreviewForClient(clientSessionId, previewId);
        if (stale.status === 'claimed') this.#complete(stale.claim);
        return stale.status === 'expired' ? previewExpired() : previewNotFound();
      }
      return preflightDisconnected();
    }

    const claimed = this.#cache.claimPreviewForClient(clientSessionId, previewId);
    if (claimed.status !== 'claimed') {
      await session.close().catch(() => undefined);
      return claimed.status === 'expired' ? previewExpired() : previewNotFound();
    }
    try {
      const json = canonicalizeJson({
        workspace: claimed.claim.preview.identity.workspace,
        applyAttemptId: claimed.claim.preview.applyAttemptId,
        normalizedEdit: claimed.claim.preview.normalizedEdit,
      });
      if (json === null || Array.isArray(json) || typeof json !== 'object') {
        return applyOutcomeUnknown();
      }
      let response: unknown;
      try {
        response = await session.call(
          MUTATION_APPLY_BRIDGE_METHOD,
          json as JsonObject,
          options.signal === undefined ? undefined : { signal: options.signal },
        );
      } catch {
        return applyOutcomeUnknown();
      }
      try {
        return this.#mapBridgeResponse(response);
      } catch {
        return applyOutcomeUnknown();
      }
    } finally {
      try {
        this.#complete(claimed.claim);
      } finally {
        await session.close().catch(() => undefined);
      }
    }
  }
}
