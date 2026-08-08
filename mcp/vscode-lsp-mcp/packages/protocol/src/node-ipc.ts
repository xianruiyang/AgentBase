import net from 'node:net';
import { secureUnixSocketAfterBind } from './runtime-directory.js';
import { BridgeTransportError, type RawByteConnection, type RawByteServer } from './ipc-session.js';

interface ReadWaiter {
  readonly resolve: (value: Uint8Array | null) => void;
  readonly reject: (error: Error) => void;
}

class NodeSocketRawConnection implements RawByteConnection {
  readonly #socket: net.Socket;
  readonly #chunks: Buffer[] = [];
  readonly #waiters: ReadWaiter[] = [];
  #closed = false;
  #failure: Error | undefined;

  constructor(socket: net.Socket) {
    this.#socket = socket;
    socket.on('data', (chunk: Buffer) => this.#onData(chunk));
    socket.once('error', () => this.#onClose(new BridgeTransportError(
      'disconnected',
      'IPC socket failed.',
      'unknown',
    )));
    socket.once('end', () => this.#onClose());
    socket.once('close', () => this.#onClose());
  }

  #onData(chunk: Buffer): void {
    if (this.#closed || chunk.byteLength === 0) {
      return;
    }
    const waiter = this.#waiters.shift();
    if (waiter === undefined) {
      this.#chunks.push(Buffer.from(chunk));
    } else {
      waiter.resolve(Buffer.from(chunk));
    }
  }

  #onClose(error?: Error): void {
    if (this.#closed) {
      return;
    }
    this.#closed = true;
    this.#failure = error;
    for (const waiter of this.#waiters.splice(0)) {
      if (error === undefined) {
        waiter.resolve(null);
      } else {
        waiter.reject(error);
      }
    }
  }

  read(): Promise<Uint8Array | null> {
    const chunk = this.#chunks.shift();
    if (chunk !== undefined) {
      return Promise.resolve(chunk);
    }
    if (this.#closed) {
      return this.#failure === undefined
        ? Promise.resolve(null)
        : Promise.reject(this.#failure);
    }
    return new Promise((resolve, reject) => this.#waiters.push({ resolve, reject }));
  }

  write(bytes: Uint8Array): Promise<void> {
    if (this.#closed) {
      return Promise.reject(new BridgeTransportError(
        'disconnected',
        'IPC socket is closed.',
        'notStarted',
      ));
    }
    return new Promise((resolve, reject) => {
      this.#socket.write(bytes, (error) => {
        if (error == null) {
          resolve();
        } else {
          reject(new BridgeTransportError(
            'disconnected',
            'IPC socket write failed.',
            'unknown',
          ));
        }
      });
    });
  }

  async close(): Promise<void> {
    if (this.#closed) {
      return;
    }
    await new Promise<void>((resolve) => {
      this.#socket.once('close', resolve);
      this.#socket.destroy();
    });
  }
}

class NodeSocketRawServer implements RawByteServer {
  readonly #server: net.Server;
  readonly #connections: RawByteConnection[] = [];
  readonly #waiters: Array<{
    readonly resolve: (connection: RawByteConnection) => void;
    readonly reject: (error: Error) => void;
  }> = [];
  #closed = false;

  constructor(server: net.Server) {
    this.#server = server;
    server.on('connection', (socket) => {
      const connection = new NodeSocketRawConnection(socket);
      const waiter = this.#waiters.shift();
      if (waiter === undefined) {
        this.#connections.push(connection);
      } else {
        waiter.resolve(connection);
      }
    });
    server.once('error', () => {
      const error = new BridgeTransportError(
        'disconnected',
        'IPC server failed.',
        'notStarted',
      );
      for (const waiter of this.#waiters.splice(0)) {
        waiter.reject(error);
      }
    });
  }

  accept(): Promise<RawByteConnection> {
    const connection = this.#connections.shift();
    if (connection !== undefined) {
      return Promise.resolve(connection);
    }
    if (this.#closed) {
      return Promise.reject(new BridgeTransportError(
        'disconnected',
        'IPC server is closed.',
        'notStarted',
      ));
    }
    return new Promise((resolve, reject) => this.#waiters.push({ resolve, reject }));
  }

  async close(): Promise<void> {
    if (this.#closed) {
      return;
    }
    this.#closed = true;
    const error = new BridgeTransportError(
      'disconnected',
      'IPC server is closed.',
      'notStarted',
    );
    for (const waiter of this.#waiters.splice(0)) {
      waiter.reject(error);
    }
    for (const connection of this.#connections.splice(0)) {
      await connection.close().catch(() => undefined);
    }
    await new Promise<void>((resolve) => this.#server.close(() => resolve()));
  }
}

const listen = (server: net.Server, address: string): Promise<void> =>
  new Promise((resolve, reject) => {
    const onError = (): void => reject(new BridgeTransportError(
      'disconnected',
      'IPC endpoint bind failed.',
      'notStarted',
    ));
    server.once('error', onError);
    server.listen({ path: address, exclusive: true }, () => {
      server.off('error', onError);
      resolve();
    });
  });

export const createUnixRawByteServer = async (
  address: string,
  expectedUid: number,
): Promise<RawByteServer> => {
  if (process.platform === 'win32') {
    throw new Error('Unix socket servers are not available on Windows.');
  }
  const server = net.createServer({ allowHalfOpen: false, pauseOnConnect: false });
  try {
    await listen(server, address);
    await secureUnixSocketAfterBind(address, expectedUid);
    return new NodeSocketRawServer(server);
  } catch (error) {
    await new Promise<void>((resolve) => server.close(() => resolve())).catch(() => undefined);
    throw error;
  }
};

export const connectNodeRawByte = (
  address: string,
  timeoutMs: number,
): Promise<RawByteConnection> =>
  new Promise((resolve, reject) => {
    const socket = net.createConnection({ path: address });
    const timeout = setTimeout(() => {
      socket.destroy();
      reject(new BridgeTransportError(
        'timeout',
        'IPC connect timed out.',
        'notStarted',
      ));
    }, timeoutMs);
    socket.once('connect', () => {
      clearTimeout(timeout);
      resolve(new NodeSocketRawConnection(socket));
    });
    socket.once('error', () => {
      clearTimeout(timeout);
      reject(new BridgeTransportError(
        'disconnected',
        'IPC connect failed.',
        'notStarted',
      ));
    });
  });
