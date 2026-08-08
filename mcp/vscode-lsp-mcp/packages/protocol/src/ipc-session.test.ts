import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import {
  BridgeClientSession,
  BridgeServerSession,
  BridgeTransportError,
  IPC_MAX_PAYLOAD_BYTES,
  IPC_MAX_REQUEST_TIMEOUT_MS,
  authenticateIpcClientConnection,
  authenticateIpcServerConnection,
  createAuthToken,
  createInstanceId,
  createWorkspaceId,
  type IpcExpectedIdentity,
  type RawByteConnection,
  type RuntimePrimitives,
} from './index.js';

class MemoryConnection implements RawByteConnection {
  peer?: MemoryConnection;
  readonly #chunks: Uint8Array[] = [];
  readonly #waiters: Array<(value: Uint8Array | null) => void> = [];
  #ended = false;

  read(): Promise<Uint8Array | null> {
    const chunk = this.#chunks.shift();
    if (chunk !== undefined) return Promise.resolve(chunk);
    if (this.#ended) return Promise.resolve(null);
    return new Promise((resolve) => this.#waiters.push(resolve));
  }

  async write(bytes: Uint8Array): Promise<void> {
    const peer = this.peer;
    if (peer === undefined || peer.#ended) throw new Error('closed');
    for (const byte of bytes) peer.#deliver(Uint8Array.of(byte));
  }

  #deliver(bytes: Uint8Array): void {
    const waiter = this.#waiters.shift();
    if (waiter === undefined) this.#chunks.push(bytes);
    else waiter(bytes);
  }

  async close(): Promise<void> {
    this.#ended = true;
    this.#finish();
    if (this.peer !== undefined) {
      this.peer.#ended = true;
      this.peer.#finish();
    }
  }

  #finish(): void {
    for (const waiter of this.#waiters.splice(0)) waiter(null);
  }
}

const pair = (): readonly [MemoryConnection, MemoryConnection] => {
  const left = new MemoryConnection();
  const right = new MemoryConnection();
  left.peer = right;
  right.peer = left;
  return [left, right];
};

const primitives = (): RuntimePrimitives => {
  let call = 0;
  return {
    monotonicNowMs: () => 0,
    secureRandomBytes: (length) => new Uint8Array(length).fill(++call),
    sha256Hex: (input) => createHash('sha256').update(input).digest('hex'),
  };
};

const identity = (): { readonly expected: IpcExpectedIdentity; readonly source: RuntimePrimitives } => {
  const source = primitives();
  return {
    source,
    expected: {
      instanceId: createInstanceId(source),
      workspaceId: createWorkspaceId(source),
      workspaceGeneration: 1,
      token: createAuthToken(source),
    },
  };
};

test('client and server authenticate over fragmented raw bytes', async () => {
  const [clientRaw, serverRaw] = pair();
  const { expected, source } = identity();
  const [client, server] = await Promise.all([
    authenticateIpcClientConnection(clientRaw, expected, source, 100),
    authenticateIpcServerConnection(serverRaw, expected, 100),
  ]);
  await Promise.all([client.close(), server.close()]);
});

test('wrong token and silent peers fail closed without exposing identity detail', async () => {
  const [clientRaw, serverRaw] = pair();
  const { expected, source } = identity();
  const wrong = { ...expected, token: createAuthToken(source) };
  const results = await Promise.allSettled([
    authenticateIpcClientConnection(clientRaw, wrong, source, 100),
    authenticateIpcServerConnection(serverRaw, expected, 100),
  ]);
  for (const result of results) {
    assert.equal(result.status, 'rejected');
    if (result.status === 'rejected') {
      assert.equal(result.reason instanceof BridgeTransportError, true);
      assert.match(String(result.reason), /authentication failed/i);
    }
  }

  const [silent] = pair();
  await assert.rejects(authenticateIpcServerConnection(silent, expected, 5), (error: unknown) =>
    error instanceof BridgeTransportError && error.reason === 'timeout');
});

test('request results, cancellation, and disconnect outcomes are observable without replay', async () => {
  const [clientRaw, serverRaw] = pair();
  const { expected, source } = identity();
  const [clientConnection, serverConnection] = await Promise.all([
    authenticateIpcClientConnection(clientRaw, expected, source, 100),
    authenticateIpcServerConnection(serverRaw, expected, 100),
  ]);
  let calls = 0;
  let cancellationObserved = false;
  const server = new BridgeServerSession(serverConnection, async (request, signal) => {
    calls += 1;
    if (request.method === 'echo') return request.params;
    await new Promise<void>((resolve) => signal.addEventListener('abort', () => {
      cancellationObserved = true;
      resolve();
    }, { once: true }));
    throw new Error('cancelled');
  });
  const running = server.run();
  const client = new BridgeClientSession(clientConnection, source);
  assert.deepEqual(await client.call('echo', { value: '中文\nline' }), { value: '中文\nline' });

  const controller = new AbortController();
  const cancelled = client.call('wait', {}, { signal: controller.signal });
  await new Promise((resolve) => setTimeout(resolve, 10));
  controller.abort();
  await assert.rejects(cancelled, (error: unknown) =>
    error instanceof BridgeTransportError && error.reason === 'cancelled' && error.dispatchOutcome === 'unknown');
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(cancellationObserved, true);

  const disconnected = client.call('wait', {});
  await new Promise((resolve) => setTimeout(resolve, 10));
  await server.close();
  await assert.rejects(disconnected, (error: unknown) =>
    error instanceof BridgeTransportError && error.reason === 'disconnected' && error.dispatchOutcome === 'unknown');
  assert.equal(calls, 3);
  await client.close();
  await running;
});

test('an oversized bridge result becomes a bounded remote error without breaking the session', async () => {
  const [clientRaw, serverRaw] = pair();
  const { expected, source } = identity();
  const [clientConnection, serverConnection] = await Promise.all([
    authenticateIpcClientConnection(clientRaw, expected, source, 100),
    authenticateIpcServerConnection(serverRaw, expected, 100),
  ]);
  const server = new BridgeServerSession(serverConnection, (request) => Promise.resolve(
    request.method === 'large'
      ? 'x'.repeat(IPC_MAX_PAYLOAD_BYTES)
      : { status: 'healthy' },
  ));
  const running = server.run();
  const client = new BridgeClientSession(clientConnection, source);
  await assert.rejects(client.call('large', {}), (error: unknown) =>
    error instanceof BridgeTransportError &&
    error.reason === 'remote' &&
    error.remoteCode === 'BRIDGE_RESPONSE_TOO_LARGE');
  assert.deepEqual(await client.call('small', {}), { status: 'healthy' });
  await client.close();
  await running;
});

test('elapsed deadlines and pre-dispatch cancellation are not started', async () => {
  const [clientRaw, serverRaw] = pair();
  const { expected, source } = identity();
  const [clientConnection, serverConnection] = await Promise.all([
    authenticateIpcClientConnection(clientRaw, expected, source, 100),
    authenticateIpcServerConnection(serverRaw, expected, 100),
  ]);
  const client = new BridgeClientSession(clientConnection, source);
  await assert.rejects(client.call('late', {}, { deadlineAt: Date.now() - 1 }), (error: unknown) =>
    error instanceof BridgeTransportError && error.reason === 'timeout' && error.dispatchOutcome === 'notStarted');
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(client.call('cancel', {}, { signal: controller.signal }), (error: unknown) =>
    error instanceof BridgeTransportError && error.reason === 'cancelled' && error.dispatchOutcome === 'notStarted');
  await Promise.all([client.close(), serverConnection.close()]);
});

test('explicit long request windows are bounded by the global IPC maximum', async () => {
  const [clientRaw, serverRaw] = pair();
  const { expected, source } = identity();
  const [clientConnection, serverConnection] = await Promise.all([
    authenticateIpcClientConnection(clientRaw, expected, source, 100),
    authenticateIpcServerConnection(serverRaw, expected, 100),
  ]);
  let observedDeadlineAt = 0;
  const server = new BridgeServerSession(serverConnection, (request) => {
    observedDeadlineAt = request.deadlineAt;
    return Promise.resolve({ accepted: true });
  });
  const running = server.run();
  const client = new BridgeClientSession(clientConnection, source);
  const startedAt = Date.now();
  assert.deepEqual(await client.call('long', {}, {
    deadlineAt: startedAt + 120_000,
    maximumTimeoutMs: IPC_MAX_REQUEST_TIMEOUT_MS,
  }), { accepted: true });
  assert.equal(observedDeadlineAt >= startedAt + 119_000, true);
  await assert.rejects(client.call('invalid', {}, {
    maximumTimeoutMs: IPC_MAX_REQUEST_TIMEOUT_MS + 1,
  }), RangeError);
  await Promise.all([client.close(), server.close()]);
  await running;
});
