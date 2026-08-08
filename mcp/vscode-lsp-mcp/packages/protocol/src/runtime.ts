import { createHash, randomBytes } from 'node:crypto';
import { performance } from 'node:perf_hooks';
import type { WorkspaceId } from './workspace-identity.js';

export const PROTOCOL_PACKAGE_NAME = '@simplechat/vscode-lsp-mcp-protocol';

export interface WorkspaceRouteIdentity {
  readonly workspaceId: WorkspaceId;
  readonly generation: number;
}

export interface RequestIdentity {
  readonly clientSessionId: string;
  readonly requestId: string;
  readonly workspace: WorkspaceRouteIdentity;
  readonly attemptId?: string;
}

export interface PayloadBounds {
  readonly maxCodePoints: number;
  readonly maxArrayItems: number;
  readonly maxBytes: number;
}

export interface RuntimePrimitives {
  monotonicNowMs(): number;
  secureRandomBytes(length: number): Uint8Array;
  sha256Hex(input: Uint8Array): string;
}

export interface WorkspaceMutationGate {
  runExclusive<T>(
    workspace: WorkspaceRouteIdentity,
    operation: 'apply' | 'command',
    action: () => Promise<T>,
  ): Promise<T>;
}

export const systemRuntimePrimitives: RuntimePrimitives = Object.freeze({
  monotonicNowMs: () => performance.now(),
  secureRandomBytes: (length: number) => {
    if (!Number.isSafeInteger(length) || length < 1 || length > 65_536) {
      throw new RangeError('Random byte length must be an integer from 1 through 65536.');
    }
    return randomBytes(length);
  },
  sha256Hex: (input: Uint8Array) => createHash('sha256').update(input).digest('hex'),
});
