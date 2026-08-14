import net from 'node:net';
import { BridgeTransportError, type RawByteConnection } from './ipc-session.js';

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
