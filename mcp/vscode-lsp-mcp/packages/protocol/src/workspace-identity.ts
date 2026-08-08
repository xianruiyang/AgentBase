import { Buffer } from 'node:buffer';
import type { RuntimePrimitives, WorkspaceRouteIdentity } from './runtime.js';

declare const instanceIdBrand: unique symbol;
declare const workspaceIdBrand: unique symbol;

export type InstanceId = string & { readonly [instanceIdBrand]: true };
export type WorkspaceId = string & { readonly [workspaceIdBrand]: true };

export interface WorkspaceRootIdentityView {
  readonly alias: string;
  readonly canonicalComparisonKey: string;
}

export interface WorkspaceIdentitySnapshot extends WorkspaceRouteIdentity {
  readonly instanceId: InstanceId;
  readonly rootsFingerprint: string;
}

export interface WorkspaceIdentityUpdate {
  readonly changed: boolean;
  readonly snapshot: WorkspaceIdentitySnapshot;
}

const uuidV4Pattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;
const workspaceIdPattern = /^ws_[A-Za-z0-9_-]{22}$/u;

const secureBytes = (primitives: RuntimePrimitives, length: number): Uint8Array => {
  const bytes = primitives.secureRandomBytes(length);
  if (bytes.byteLength !== length) {
    throw new Error('Runtime random source returned an unexpected byte length.');
  }
  return Uint8Array.from(bytes);
};

export const createInstanceId = (primitives: RuntimePrimitives): InstanceId => {
  const bytes = secureBytes(primitives, 16);
  bytes[6] = (bytes[6] ?? 0) & 0x0f | 0x40;
  bytes[8] = (bytes[8] ?? 0) & 0x3f | 0x80;
  const hex = Buffer.from(bytes).toString('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}` as InstanceId;
};

export const createWorkspaceId = (primitives: RuntimePrimitives): WorkspaceId =>
  `ws_${Buffer.from(secureBytes(primitives, 16)).toString('base64url')}` as WorkspaceId;

export const isInstanceId = (value: string): value is InstanceId => uuidV4Pattern.test(value);

export const isWorkspaceId = (value: string): value is WorkspaceId =>
  value !== 'server' && workspaceIdPattern.test(value);

const rootsFingerprint = (
  roots: readonly WorkspaceRootIdentityView[],
  primitives: RuntimePrimitives,
): string => {
  if (roots.length === 0) {
    throw new RangeError('A workspace identity requires at least one root.');
  }
  const serialized = JSON.stringify(
    roots.map((root) => [root.alias, root.canonicalComparisonKey] as const),
  );
  return primitives.sha256Hex(new TextEncoder().encode(serialized));
};

export class WorkspaceIdentityController {
  readonly instanceId: InstanceId;
  readonly #primitives: RuntimePrimitives;
  #current: WorkspaceIdentitySnapshot | undefined;

  constructor(primitives: RuntimePrimitives, instanceId = createInstanceId(primitives)) {
    if (!isInstanceId(instanceId)) {
      throw new TypeError('instanceId must be a UUIDv4.');
    }
    this.#primitives = primitives;
    this.instanceId = instanceId;
  }

  #observeFingerprint(fingerprint: string): WorkspaceIdentityUpdate {
    if (!/^[0-9a-f]{64}$/u.test(fingerprint)) {
      throw new Error('Workspace fingerprint must be 64 lowercase hexadecimal characters.');
    }
    if (this.#current?.rootsFingerprint === fingerprint) {
      return Object.freeze({ changed: false, snapshot: this.#current });
    }

    const generation = (this.#current?.generation ?? 0) + 1;
    if (!Number.isSafeInteger(generation)) {
      throw new RangeError('workspaceGeneration exceeded the safe integer range.');
    }
    const snapshot = Object.freeze({
      instanceId: this.instanceId,
      workspaceId: createWorkspaceId(this.#primitives),
      generation,
      rootsFingerprint: fingerprint,
    });
    this.#current = snapshot;
    return Object.freeze({ changed: true, snapshot });
  }

  observeRoots(roots: readonly WorkspaceRootIdentityView[]): WorkspaceIdentityUpdate {
    return this.#observeFingerprint(rootsFingerprint(roots, this.#primitives));
  }

  observeUnavailable(stateKey: string): WorkspaceIdentityUpdate {
    if (stateKey.length === 0 || stateKey.length > 16_384) {
      throw new RangeError('Unavailable workspace state key must be bounded non-empty text.');
    }
    const fingerprint = this.#primitives.sha256Hex(
      new TextEncoder().encode(`unavailable\u0000${stateKey}`),
    );
    return this.#observeFingerprint(fingerprint);
  }

  current(): WorkspaceIdentitySnapshot | undefined {
    return this.#current;
  }
}
