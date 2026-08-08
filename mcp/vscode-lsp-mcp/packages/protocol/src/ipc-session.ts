import type { JsonObject, JsonValue } from './dto.js';
import {
  IPC_DEFAULT_REQUEST_TIMEOUT_MS,
  IPC_HELLO_TIMEOUT_MS,
  IPC_MAX_REQUEST_TIMEOUT_MS,
  IPC_PROTOCOL_VERSION,
  IPC_RECONNECT_DELAYS_MS,
  IpcFrameDecoder,
  IpcProtocolError,
  constantTimeAuthTokenEquals,
  createIpcNonce,
  encodeIpcMessage,
  type IpcHello,
  type IpcHelloAck,
  type IpcMessage,
  type IpcRequest,
  type IpcResponse,
} from './ipc-protocol.js';
import type { RuntimePrimitives } from './runtime.js';
import type { InstanceId, WorkspaceId } from './workspace-identity.js';

export interface RawByteConnection {
  read(): Promise<Uint8Array | null>;
  write(bytes: Uint8Array): Promise<void>;
  close(): Promise<void>;
}

export interface RawByteServer {
  accept(): Promise<RawByteConnection>;
  close(): Promise<void>;
}

export class BridgeTransportError extends Error {
  readonly reason:
    | 'authentication'
    | 'cancelled'
    | 'disconnected'
    | 'protocol'
    | 'remote'
    | 'timeout';
  readonly dispatchOutcome: 'notStarted' | 'unknown';
  readonly remoteCode?: string;

  constructor(
    reason: BridgeTransportError['reason'],
    message: string,
    dispatchOutcome: BridgeTransportError['dispatchOutcome'],
    remoteCode?: string,
  ) {
    super(message);
    this.name = 'BridgeTransportError';
    this.reason = reason;
    this.dispatchOutcome = dispatchOutcome;
    if (remoteCode !== undefined) {
      this.remoteCode = remoteCode;
    }
  }
}

export class FramedIpcConnection {
  readonly #raw: RawByteConnection;
  readonly #decoder = new IpcFrameDecoder();
  readonly #queue: IpcMessage[] = [];
  #reading = false;
  #closed = false;
  #writeChain = Promise.resolve();

  constructor(raw: RawByteConnection) {
    this.#raw = raw;
  }

  async readMessage(): Promise<IpcMessage | null> {
    if (this.#reading) {
      throw new Error('Only one IPC reader is allowed per connection.');
    }
    const queued = this.#queue.shift();
    if (queued !== undefined) {
      return queued;
    }
    if (this.#closed) {
      return null;
    }
    this.#reading = true;
    try {
      while (!this.#closed) {
        const chunk = await this.#raw.read();
        if (chunk === null) {
          this.#decoder.finish();
          this.#closed = true;
          return null;
        }
        this.#queue.push(...this.#decoder.push(chunk));
        const message = this.#queue.shift();
        if (message !== undefined) {
          return message;
        }
      }
      return null;
    } finally {
      this.#reading = false;
    }
  }

  writeMessage(message: IpcMessage): Promise<void> {
    if (this.#closed) {
      return Promise.reject(new BridgeTransportError(
        'disconnected',
        'IPC connection is closed.',
        'notStarted',
      ));
    }
    const frame = encodeIpcMessage(message);
    const write = this.#writeChain.then(() => this.#raw.write(frame));
    this.#writeChain = write.catch(() => undefined);
    return write;
  }

  async close(): Promise<void> {
    if (this.#closed) {
      return;
    }
    this.#closed = true;
    await this.#raw.close();
  }
}

const readWithTimeout = async (
  connection: FramedIpcConnection,
  timeoutMs: number,
): Promise<IpcMessage | null> => {
  let timeout: NodeJS.Timeout | undefined;
  try {
    return await Promise.race([
      connection.readMessage(),
      new Promise<never>((_resolve, reject) => {
        timeout = setTimeout(
          () => reject(new BridgeTransportError(
            'timeout',
            'IPC handshake timed out.',
            'notStarted',
          )),
          timeoutMs,
        );
      }),
    ]);
  } finally {
    if (timeout !== undefined) {
      clearTimeout(timeout);
    }
  }
};

export interface IpcExpectedIdentity {
  readonly instanceId: InstanceId;
  readonly workspaceId: WorkspaceId;
  readonly workspaceGeneration: number;
  readonly token: string;
}

const identityMatches = (
  expected: IpcExpectedIdentity,
  actual: Pick<IpcHello | IpcHelloAck, 'instanceId' | 'workspaceGeneration' | 'workspaceId'>,
): boolean =>
  expected.instanceId === actual.instanceId &&
  expected.workspaceId === actual.workspaceId &&
  expected.workspaceGeneration === actual.workspaceGeneration;

const authenticationFailure = async (connection: FramedIpcConnection): Promise<never> => {
  await connection.close().catch(() => undefined);
  throw new BridgeTransportError(
    'authentication',
    'IPC authentication failed.',
    'notStarted',
  );
};

export const authenticateIpcServerConnection = async (
  raw: RawByteConnection,
  expected: IpcExpectedIdentity,
  timeoutMs = IPC_HELLO_TIMEOUT_MS,
): Promise<FramedIpcConnection> => {
  const connection = new FramedIpcConnection(raw);
  try {
    const message = await readWithTimeout(connection, timeoutMs);
    if (
      message?.kind !== 'hello' ||
      !identityMatches(expected, message) ||
      !constantTimeAuthTokenEquals(expected.token, message.token)
    ) {
      return await authenticationFailure(connection);
    }
    await connection.writeMessage({
      protocolVersion: IPC_PROTOCOL_VERSION,
      kind: 'helloAck',
      instanceId: expected.instanceId,
      workspaceId: expected.workspaceId,
      workspaceGeneration: expected.workspaceGeneration,
      nonce: message.nonce,
    });
    return connection;
  } catch (error) {
    await connection.close().catch(() => undefined);
    if (error instanceof BridgeTransportError && error.reason === 'timeout') {
      throw error;
    }
    throw new BridgeTransportError('authentication', 'IPC authentication failed.', 'notStarted');
  }
};

export const authenticateIpcClientConnection = async (
  raw: RawByteConnection,
  expected: IpcExpectedIdentity,
  primitives: RuntimePrimitives,
  timeoutMs = IPC_HELLO_TIMEOUT_MS,
): Promise<FramedIpcConnection> => {
  const connection = new FramedIpcConnection(raw);
  const nonce = createIpcNonce(primitives);
  try {
    await connection.writeMessage({
      protocolVersion: IPC_PROTOCOL_VERSION,
      kind: 'hello',
      instanceId: expected.instanceId,
      workspaceId: expected.workspaceId,
      workspaceGeneration: expected.workspaceGeneration,
      token: expected.token,
      nonce,
    });
    const message = await readWithTimeout(connection, timeoutMs);
    if (
      message?.kind !== 'helloAck' ||
      !identityMatches(expected, message) ||
      message.nonce !== nonce
    ) {
      return await authenticationFailure(connection);
    }
    return connection;
  } catch (error) {
    await connection.close().catch(() => undefined);
    if (error instanceof BridgeTransportError && error.reason === 'timeout') {
      throw error;
    }
    throw new BridgeTransportError('authentication', 'IPC authentication failed.', 'notStarted');
  }
};

interface PendingCall {
  readonly resolve: (value: JsonValue) => void;
  readonly reject: (error: Error) => void;
  readonly timer: NodeJS.Timeout;
  readonly signal?: AbortSignal;
  readonly abortListener?: () => void;
  dispatched: boolean;
}

export interface BridgeCallOptions {
  readonly deadlineAt?: number;
  readonly maximumTimeoutMs?: number;
  readonly signal?: AbortSignal;
}

export class BridgeClientSession {
  readonly #connection: FramedIpcConnection;
  readonly #primitives: RuntimePrimitives;
  readonly #pending = new Map<string, PendingCall>();
  #closed = false;

  constructor(connection: FramedIpcConnection, primitives: RuntimePrimitives) {
    this.#connection = connection;
    this.#primitives = primitives;
    void this.#pump();
  }

  call(method: string, params: JsonObject, options: BridgeCallOptions = {}): Promise<JsonValue> {
    if (this.#closed) {
      return Promise.reject(new BridgeTransportError(
        'disconnected',
        'IPC session is closed.',
        'notStarted',
      ));
    }
    const now = Date.now();
    const maximumTimeoutMs = options.maximumTimeoutMs ?? IPC_DEFAULT_REQUEST_TIMEOUT_MS;
    if (!Number.isSafeInteger(maximumTimeoutMs) || maximumTimeoutMs < 1 ||
        maximumTimeoutMs > IPC_MAX_REQUEST_TIMEOUT_MS) {
      return Promise.reject(new RangeError(
        `IPC maximumTimeoutMs must be an integer from 1 to ${IPC_MAX_REQUEST_TIMEOUT_MS}.`,
      ));
    }
    const deadlineAt = Math.min(
      options.deadlineAt ?? now + IPC_DEFAULT_REQUEST_TIMEOUT_MS,
      now + maximumTimeoutMs,
    );
    if (!Number.isSafeInteger(deadlineAt) || deadlineAt <= now) {
      return Promise.reject(new BridgeTransportError(
        'timeout',
        'IPC request deadline has elapsed.',
        'notStarted',
      ));
    }
    if (options.signal?.aborted === true) {
      return Promise.reject(new BridgeTransportError(
        'cancelled',
        'IPC request was cancelled before dispatch.',
        'notStarted',
      ));
    }
    const id = createIpcNonce(this.#primitives);
    return new Promise<JsonValue>((resolve, reject) => {
      const timeout = Math.max(1, deadlineAt - Date.now());
      const timer = setTimeout(() => {
        const pending = this.#takePending(id);
        if (pending !== undefined) {
          if (pending.dispatched) {
            void this.#sendCancel(id);
          }
          pending.reject(new BridgeTransportError(
            'timeout',
            'IPC request timed out.',
            pending.dispatched ? 'unknown' : 'notStarted',
          ));
        }
      }, timeout);
      const abortListener = options.signal === undefined
        ? undefined
        : () => {
            const pending = this.#takePending(id);
            if (pending !== undefined) {
              if (pending.dispatched) {
                void this.#sendCancel(id);
              }
              pending.reject(new BridgeTransportError(
                'cancelled',
                'IPC request was cancelled.',
                pending.dispatched ? 'unknown' : 'notStarted',
              ));
            }
          };
      const pending: PendingCall = {
        resolve,
        reject,
        timer,
        dispatched: false,
        ...(options.signal === undefined ? {} : { signal: options.signal }),
        ...(abortListener === undefined ? {} : { abortListener }),
      };
      this.#pending.set(id, pending);
      options.signal?.addEventListener('abort', abortListener as () => void, { once: true });
      void this.#connection.writeMessage({
        protocolVersion: IPC_PROTOCOL_VERSION,
        kind: 'request',
        id,
        method,
        deadlineAt,
        params,
      }).then(
        () => {
          const current = this.#pending.get(id);
          if (current !== undefined) {
            current.dispatched = true;
          }
        },
        () => {
          const current = this.#takePending(id);
          current?.reject(new BridgeTransportError(
            'disconnected',
            'IPC request could not be dispatched.',
            'notStarted',
          ));
        },
      );
    });
  }

  #takePending(id: string): PendingCall | undefined {
    const pending = this.#pending.get(id);
    if (pending === undefined) {
      return undefined;
    }
    this.#pending.delete(id);
    clearTimeout(pending.timer);
    if (pending.signal !== undefined && pending.abortListener !== undefined) {
      pending.signal.removeEventListener('abort', pending.abortListener);
    }
    return pending;
  }

  async #sendCancel(id: string): Promise<void> {
    await this.#connection.writeMessage({
      protocolVersion: IPC_PROTOCOL_VERSION,
      kind: 'cancel',
      id,
    }).catch(() => undefined);
  }

  async #pump(): Promise<void> {
    try {
      while (!this.#closed) {
        const message = await this.#connection.readMessage();
        if (message === null) {
          break;
        }
        if (message.kind !== 'response') {
          throw new IpcProtocolError('invalidMessage', 'IPC client received an unexpected message.');
        }
        const pending = this.#takePending(message.id);
        if (pending === undefined) {
          continue;
        }
        if (message.ok) {
          pending.resolve(message.result);
        } else {
          pending.reject(new BridgeTransportError(
            'remote',
            message.error.message,
            'unknown',
            message.error.code,
          ));
        }
      }
      this.#failAll('disconnected');
    } catch (error) {
      this.#failAll(error instanceof IpcProtocolError ? 'protocol' : 'disconnected');
      await this.#connection.close().catch(() => undefined);
    }
  }

  #failAll(reason: 'disconnected' | 'protocol'): void {
    this.#closed = true;
    for (const id of [...this.#pending.keys()]) {
      const pending = this.#takePending(id);
      pending?.reject(new BridgeTransportError(
        reason,
        reason === 'protocol' ? 'IPC protocol failed.' : 'IPC connection disconnected.',
        pending.dispatched ? 'unknown' : 'notStarted',
      ));
    }
  }

  async close(): Promise<void> {
    if (!this.#closed) {
      this.#failAll('disconnected');
    }
    await this.#connection.close();
  }
}

export type BridgeRequestHandler = (
  request: IpcRequest,
  signal: AbortSignal,
) => Promise<JsonValue>;

export class BridgeServerSession {
  readonly #connection: FramedIpcConnection;
  readonly #handler: BridgeRequestHandler;
  readonly #inFlight = new Map<string, AbortController>();
  #closed = false;

  constructor(connection: FramedIpcConnection, handler: BridgeRequestHandler) {
    this.#connection = connection;
    this.#handler = handler;
  }

  async run(): Promise<void> {
    try {
      while (!this.#closed) {
        const message = await this.#connection.readMessage();
        if (message === null) {
          break;
        }
        if (message.kind === 'cancel') {
          this.#inFlight.get(message.id)?.abort();
          continue;
        }
        if (message.kind !== 'request' || this.#inFlight.has(message.id)) {
          throw new IpcProtocolError('invalidMessage', 'IPC server received an unexpected message.');
        }
        this.#dispatch(message);
      }
    } finally {
      this.#closed = true;
      for (const controller of this.#inFlight.values()) {
        controller.abort();
      }
      this.#inFlight.clear();
      await this.#connection.close().catch(() => undefined);
    }
  }

  #dispatch(request: IpcRequest): void {
    const controller = new AbortController();
    this.#inFlight.set(request.id, controller);
    const localDeadline = Date.now() + IPC_MAX_REQUEST_TIMEOUT_MS;
    const timeoutMs = Math.max(0, Math.min(request.deadlineAt, localDeadline) - Date.now());
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    void this.#handler(request, controller.signal).then(
      (result) => this.#sendResponse({
        protocolVersion: IPC_PROTOCOL_VERSION,
        kind: 'response',
        id: request.id,
        ok: true,
        result,
      }),
      () => this.#sendResponse({
        protocolVersion: IPC_PROTOCOL_VERSION,
        kind: 'response',
        id: request.id,
        ok: false,
        error: {
          code: controller.signal.aborted ? 'CANCELLED_OR_TIMED_OUT' : 'BRIDGE_REQUEST_FAILED',
          message: controller.signal.aborted
            ? 'Bridge request was cancelled or timed out.'
            : 'Bridge request failed.',
        },
      }),
    ).finally(() => {
      clearTimeout(timer);
      this.#inFlight.delete(request.id);
    });
  }

  async #sendResponse(response: IpcResponse): Promise<void> {
    if (this.#closed) return;
    try {
      await this.#connection.writeMessage(response);
    } catch (error) {
      if (!response.ok || !(error instanceof IpcProtocolError) || error.reason !== 'frameLength') return;
      await this.#connection.writeMessage({
        protocolVersion: IPC_PROTOCOL_VERSION,
        kind: 'response',
        id: response.id,
        ok: false,
        error: {
          code: 'BRIDGE_RESPONSE_TOO_LARGE',
          message: 'Bridge response exceeded the IPC payload limit.',
        },
      }).catch(() => undefined);
    }
  }

  async close(): Promise<void> {
    this.#closed = true;
    for (const controller of this.#inFlight.values()) {
      controller.abort();
    }
    await this.#connection.close();
  }
}

const waitForRetry = (milliseconds: number, signal?: AbortSignal): Promise<void> =>
  new Promise((resolve, reject) => {
    if (signal?.aborted === true) {
      reject(new BridgeTransportError('cancelled', 'IPC reconnect was cancelled.', 'notStarted'));
      return;
    }
    const timer = setTimeout(resolve, milliseconds);
    signal?.addEventListener('abort', () => {
      clearTimeout(timer);
      reject(new BridgeTransportError('cancelled', 'IPC reconnect was cancelled.', 'notStarted'));
    }, { once: true });
  });

export const connectWithFiniteBackoff = async <T>(
  connector: () => Promise<T>,
  signal?: AbortSignal,
): Promise<T> => {
  let lastError: unknown;
  for (let attempt = 0; attempt <= IPC_RECONNECT_DELAYS_MS.length; attempt += 1) {
    if (signal?.aborted === true) {
      throw new BridgeTransportError('cancelled', 'IPC reconnect was cancelled.', 'notStarted');
    }
    try {
      return await connector();
    } catch (error) {
      lastError = error;
    }
    const delay = IPC_RECONNECT_DELAYS_MS[attempt];
    if (delay !== undefined) {
      await waitForRetry(delay, signal);
    }
  }
  throw lastError instanceof Error
    ? lastError
    : new BridgeTransportError('disconnected', 'IPC reconnect failed.', 'notStarted');
};
