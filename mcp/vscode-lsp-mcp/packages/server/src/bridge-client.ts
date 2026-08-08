import {
  BridgeClientSession,
  authenticateIpcClientConnection,
  connectNodeRawByte,
  connectWithFiniteBackoff,
  IPC_HELLO_TIMEOUT_MS,
  type RuntimePrimitives,
  type UsableRegistrationRecord,
} from '@simplechat/vscode-lsp-mcp-protocol';

export interface BridgeClientConnectOptions {
  readonly record: UsableRegistrationRecord;
  readonly primitives: RuntimePrimitives;
  readonly signal?: AbortSignal;
}

export const connectRegisteredBridgeOnce = async (
  options: BridgeClientConnectOptions,
): Promise<BridgeClientSession> => {
  if (options.signal?.aborted === true) {
    throw new Error('Bridge connection was cancelled before dispatch.');
  }
  const raw = await connectNodeRawByte(options.record.endpoint.address, IPC_HELLO_TIMEOUT_MS);
  const framed = await authenticateIpcClientConnection(
    raw,
    {
      instanceId: options.record.instanceId,
      workspaceId: options.record.workspaceId,
      workspaceGeneration: options.record.workspaceGeneration,
      token: options.record.authToken,
    },
    options.primitives,
  );
  return new BridgeClientSession(framed, options.primitives);
};

export const connectRegisteredBridge = (
  options: BridgeClientConnectOptions,
): Promise<BridgeClientSession> => connectWithFiniteBackoff(
  () => connectRegisteredBridgeOnce(options),
  options.signal,
);
