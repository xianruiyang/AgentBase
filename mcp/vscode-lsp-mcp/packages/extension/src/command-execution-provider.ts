import {
  COMMAND_EXECUTE_BRIDGE_METHOD,
  canonicalizeJson,
  parseCommandExecuteBridgeRequest,
  type ExecuteCommandInput,
  type JsonObject,
  type JsonValue,
  type ToolResponseMap,
  type WorkspacePathContext,
  type WorkspaceRouteIdentity,
} from '@simplechat/vscode-lsp-mcp-protocol';

export interface CommandBridgeExecutor {
  execute(
    context: WorkspacePathContext,
    workspace: WorkspaceRouteIdentity,
    input: ExecuteCommandInput,
    signal?: AbortSignal,
  ): Promise<ToolResponseMap['execute_command']>;
}

export type CommandExecuteBridgeHandler = (
  context: WorkspacePathContext,
  workspace: WorkspaceRouteIdentity,
  request: { readonly method: string; readonly params: JsonObject },
  signal: AbortSignal,
) => Promise<JsonValue | undefined>;

export const createCommandExecuteBridgeHandler = (
  executor: CommandBridgeExecutor,
): CommandExecuteBridgeHandler => async (context, workspace, request, signal) => {
  if (request.method !== COMMAND_EXECUTE_BRIDGE_METHOD) return undefined;
  const bridgeRequest = parseCommandExecuteBridgeRequest(request.params);
  if (bridgeRequest.workspace.workspaceId !== workspace.workspaceId ||
      bridgeRequest.workspace.generation !== workspace.generation) {
    return canonicalizeJson({
      ok: false,
      error: {
        code: 'WORKSPACE_NOT_FOUND',
        message: 'The command bridge request does not match the active workspace route.',
        retryable: true,
      },
    });
  }
  return canonicalizeJson(await executor.execute(
    context,
    workspace,
    {
      workspaceId: workspace.workspaceId,
      target: bridgeRequest.target,
      saveBeforeRun: bridgeRequest.saveBeforeRun,
      timeoutMs: bridgeRequest.timeoutMs,
      maxOutputChars: bridgeRequest.maxOutputChars,
      retainOutputLog: bridgeRequest.retainOutputLog,
    },
    signal,
  ));
};
