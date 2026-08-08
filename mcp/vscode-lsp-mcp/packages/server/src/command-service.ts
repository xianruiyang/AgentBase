import {
  BridgeTransportError,
  COMMAND_EXECUTE_BRIDGE_METHOD,
  IPC_MAX_REQUEST_TIMEOUT_MS,
  canonicalizeJson,
  normalizeToolInput,
  parseCommandExecuteBridgeResponse,
  type ExecuteCommandInput,
  type JsonObject,
  type ToolResponseMap,
} from '@simplechat/vscode-lsp-mcp-protocol';
import { serverCommandSafetyPreflight } from './command-policy.js';
import {
  WorkspaceRoutingError,
  type ConnectedWorkspaceRoute,
} from './workspace-router.js';

export const COMMAND_BRIDGE_TRANSPORT_GRACE_MS = 10_000;

export interface CommandWorkspaceConnector {
  connectWorkspaceBinding(
    workspaceId: string,
    signal?: AbortSignal,
  ): Promise<ConnectedWorkspaceRoute>;
}

export interface CommandServiceOptions {
  readonly connector: CommandWorkspaceConnector;
  readonly now?: () => number;
}

const disconnected = (
  phase: 'preflight' | 'command',
): ToolResponseMap['execute_command'] => phase === 'preflight'
  ? Object.freeze({
      ok: false,
      error: Object.freeze({
        code: 'WORKSPACE_DISCONNECTED',
        message: 'The requested workspace disconnected before command dispatch.',
        retryable: true,
        details: Object.freeze({ phase: 'preflight', outcome: 'notStarted' }),
      }),
    })
  : Object.freeze({
      ok: false,
      error: Object.freeze({
        code: 'WORKSPACE_DISCONNECTED',
        message: 'The requested workspace disconnected after command dispatch; the outcome is unknown.',
        retryable: false,
        details: Object.freeze({ phase: 'command', outcome: 'unknown' }),
      }),
    });

const isAborted = (signal: AbortSignal | undefined): boolean => signal?.aborted === true;

const cancelled = (
  targetKind: ExecuteCommandInput['target']['kind'],
  outcome: 'notStarted' | 'unknown',
): ToolResponseMap['execute_command'] => Object.freeze({
  ok: false,
  error: Object.freeze({
    code: 'COMMAND_FAILED',
    message: outcome === 'notStarted'
      ? 'The command request was cancelled before dispatch.'
      : 'The command request was cancelled after dispatch; the outcome is unknown.',
    retryable: false,
    details: Object.freeze({ targetKind, reason: 'cancelled', outcome }),
  }),
});

const routeFailure = (
  error: unknown,
  targetKind: ExecuteCommandInput['target']['kind'],
): ToolResponseMap['execute_command'] => {
  if (error instanceof WorkspaceRoutingError && error.reason === 'notFound') {
    return Object.freeze({
      ok: false,
      error: Object.freeze({
        code: 'WORKSPACE_NOT_FOUND',
        message: 'The requested workspace route was not found.',
        retryable: true,
      }),
    });
  }
  if (error instanceof BridgeTransportError && error.reason === 'cancelled') {
    return cancelled(targetKind, error.dispatchOutcome);
  }
  return disconnected('preflight');
};

export class CommandService {
  readonly #connector: CommandWorkspaceConnector;
  readonly #now: () => number;

  constructor(options: CommandServiceOptions) {
    this.#connector = options.connector;
    this.#now = options.now ?? Date.now;
  }

  async executeCommand(
    inputValue: unknown,
    signal?: AbortSignal,
  ): Promise<ToolResponseMap['execute_command']> {
    const input = normalizeToolInput('execute_command', inputValue);
    const safetyFailure = serverCommandSafetyPreflight(input);
    if (safetyFailure !== undefined) return safetyFailure;
    if (isAborted(signal)) return cancelled(input.target.kind, 'notStarted');

    let route: ConnectedWorkspaceRoute;
    try {
      route = await this.#connector.connectWorkspaceBinding(input.workspaceId, signal);
    } catch (error) {
      return routeFailure(error, input.target.kind);
    }

    try {
      if (isAborted(signal)) return cancelled(input.target.kind, 'notStarted');
      const timeoutMs = input.timeoutMs ?? 120_000;
      const deadlineAt = this.#now() + Math.min(
        IPC_MAX_REQUEST_TIMEOUT_MS,
        timeoutMs + COMMAND_BRIDGE_TRANSPORT_GRACE_MS,
      );
      const params = canonicalizeJson({
        workspace: route.workspace,
        target: input.target,
        saveBeforeRun: input.saveBeforeRun ?? 'none',
        timeoutMs,
        maxOutputChars: input.maxOutputChars ?? 20_000,
        retainOutputLog: input.retainOutputLog ?? false,
      }) as JsonObject;
      const response = await route.session.call(
        COMMAND_EXECUTE_BRIDGE_METHOD,
        params,
        {
          deadlineAt,
          maximumTimeoutMs: IPC_MAX_REQUEST_TIMEOUT_MS,
          ...(signal === undefined ? {} : { signal }),
        },
      );
      return parseCommandExecuteBridgeResponse(response);
    } catch (error) {
      if (error instanceof BridgeTransportError && error.reason === 'cancelled') {
        return cancelled(input.target.kind, error.dispatchOutcome);
      }
      if (error instanceof BridgeTransportError && error.dispatchOutcome === 'notStarted') {
        return disconnected('preflight');
      }
      return disconnected('command');
    } finally {
      await route.session.close().catch(() => undefined);
    }
  }
}
