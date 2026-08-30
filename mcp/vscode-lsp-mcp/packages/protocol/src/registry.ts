import { Buffer } from 'node:buffer';
import { constants } from 'node:fs';
import { lstat, open, readdir, rename, unlink } from 'node:fs/promises';
import path from 'node:path';
import { toStrictJson } from './codec.js';
import type { JsonObject, JsonValue } from './dto.js';
import { assertAuthToken, createAuthToken, IPC_PROTOCOL_VERSION, parseStrictJson } from './ipc-protocol.js';
import type { RuntimePrimitives } from './runtime.js';
import { RuntimeSecurityError, type RuntimeDirectoryLayout, type WindowsRuntimeSecurityBoundary } from './runtime-directory.js';
import { isInstanceId, isWorkspaceId, type InstanceId, type WorkspaceId } from './workspace-identity.js';

export const REGISTRY_VERSION = 1 as const;
export const REGISTRY_HEARTBEAT_INTERVAL_MS = 10_000;
export const REGISTRY_FRESH_MS = 60_000;
export const REGISTRY_ABANDONED_MS = 300_000;
export const REGISTRY_MAX_RECORD_BYTES = 1_048_576;
export const REGISTRY_MAX_RECORDS = 256;

export const UNAVAILABLE_REASON_CODES = [
  'no_workspace_folders',
  'unsupported_uri_scheme',
  'duplicate_canonical_root',
  'cross_host_unavailable',
  'runtime_security_failed',
  'transport_start_failed',
] as const;

export type UnavailableReasonCode = (typeof UNAVAILABLE_REASON_CODES)[number];

export interface RegistrationEndpoint {
  readonly kind: 'namedPipe';
  readonly address: string;
}

export interface RegistrationRoot {
  readonly alias: string;
  readonly folderName: string;
  readonly folderIndex: number;
  readonly lexicalRoot: string;
  readonly canonicalRoot: string;
  readonly lexicalComparisonKey: string;
  readonly canonicalComparisonKey: string;
}

interface RegistrationCommon {
  readonly registryVersion: typeof REGISTRY_VERSION;
  readonly protocolVersion: typeof IPC_PROTOCOL_VERSION;
  readonly instanceId: InstanceId;
  readonly workspaceId: WorkspaceId;
  readonly workspaceGeneration: number;
  readonly recordNonce: string;
  readonly workspaceName: string;
  readonly extensionHostPid: number;
  readonly activationStartedAt: number;
  readonly publishedAt: number;
  readonly updatedAt: number;
}

export interface UsableRegistrationRecord extends RegistrationCommon {
  readonly kind: 'usable';
  readonly endpoint: RegistrationEndpoint;
  readonly authToken: string;
  readonly rootsFingerprint: string;
  readonly roots: readonly RegistrationRoot[];
  readonly vscodeVersion: string;
  readonly remoteName?: string;
}

export interface UnavailableRegistrationRecord extends RegistrationCommon {
  readonly kind: 'unavailable';
  readonly reasonCode: UnavailableReasonCode;
}

export type RegistrationRecord = UsableRegistrationRecord | UnavailableRegistrationRecord;

export class RegistryError extends Error {
  readonly reason:
    | 'comparisonChanged'
    | 'invalidRecord'
    | 'ioFailure'
    | 'recordTooLarge'
    | 'unsafeRecord'
    | 'versionMismatch';

  constructor(reason: RegistryError['reason'], message: string) {
    super(message);
    this.name = 'RegistryError';
    this.reason = reason;
  }
}

const isObject = (value: JsonValue): value is JsonObject =>
  value !== null && typeof value === 'object' && !Array.isArray(value);

const objectValue = (value: JsonValue | undefined): JsonObject => {
  if (value === undefined || !isObject(value)) {
    throw new RegistryError('invalidRecord', 'Registration record object is invalid.');
  }
  return value;
};

const exactKeys = (
  object: JsonObject,
  required: readonly string[],
  optional: readonly string[] = [],
): void => {
  const allowed = new Set([...required, ...optional]);
  if (
    required.some((key) => !(key in object)) ||
    Object.keys(object).some((key) => !allowed.has(key))
  ) {
    throw new RegistryError('invalidRecord', 'Registration record fields are invalid.');
  }
};

const requiredString = (object: JsonObject, key: string, maximum = 4_096): string => {
  const value = object[key];
  if (typeof value !== 'string' || value.length === 0 || value.length > maximum) {
    throw new RegistryError('invalidRecord', `Registration ${key} is invalid.`);
  }
  return value;
};

const positiveInteger = (object: JsonObject, key: string): number => {
  const value = object[key];
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 1) {
    throw new RegistryError('invalidRecord', `Registration ${key} is invalid.`);
  }
  return value;
};

const timestamp = (object: JsonObject, key: string): number => positiveInteger(object, key);

const validateRecordNonce = (value: string): string => {
  const decoded = Buffer.from(value, 'base64url');
  if (
    !/^[A-Za-z0-9_-]{22}$/u.test(value) ||
    decoded.byteLength !== 16 ||
    decoded.toString('base64url') !== value
  ) {
    throw new RegistryError('invalidRecord', 'Registration nonce is invalid.');
  }
  return value;
};

const commonFields = (object: JsonObject): RegistrationCommon => {
  if (object.registryVersion !== REGISTRY_VERSION || object.protocolVersion !== IPC_PROTOCOL_VERSION) {
    throw new RegistryError('versionMismatch', 'Registration version is unsupported.');
  }
  const instanceId = requiredString(object, 'instanceId', 36);
  const workspaceId = requiredString(object, 'workspaceId', 25);
  if (!isInstanceId(instanceId) || !isWorkspaceId(workspaceId)) {
    throw new RegistryError('invalidRecord', 'Registration identity is invalid.');
  }
  const publishedAt = timestamp(object, 'publishedAt');
  const updatedAt = timestamp(object, 'updatedAt');
  const activationStartedAt = timestamp(object, 'activationStartedAt');
  if (updatedAt < publishedAt || publishedAt < activationStartedAt) {
    throw new RegistryError('invalidRecord', 'Registration timestamps are inconsistent.');
  }
  return {
    registryVersion: REGISTRY_VERSION,
    protocolVersion: IPC_PROTOCOL_VERSION,
    instanceId,
    workspaceId,
    workspaceGeneration: positiveInteger(object, 'workspaceGeneration'),
    recordNonce: validateRecordNonce(requiredString(object, 'recordNonce', 22)),
    workspaceName: requiredString(object, 'workspaceName', 512),
    extensionHostPid: positiveInteger(object, 'extensionHostPid'),
    activationStartedAt,
    publishedAt,
    updatedAt,
  };
};

const parseEndpoint = (value: JsonValue | undefined): RegistrationEndpoint => {
  const object = objectValue(value);
  exactKeys(object, ['kind', 'address']);
  const kind = requiredString(object, 'kind', 16);
  if (kind !== 'namedPipe') {
    throw new RegistryError('invalidRecord', 'Registration endpoint kind is invalid.');
  }
  return Object.freeze({ kind, address: requiredString(object, 'address', 512) });
};

const parseRoot = (value: JsonValue): RegistrationRoot => {
  const object = objectValue(value);
  exactKeys(object, [
    'alias',
    'folderName',
    'folderIndex',
    'lexicalRoot',
    'canonicalRoot',
    'lexicalComparisonKey',
    'canonicalComparisonKey',
  ]);
  const alias = requiredString(object, 'alias', 64);
  if (!/^[a-z0-9._-]+(?:~[0-9a-f]{8,64})?$/u.test(alias)) {
    throw new RegistryError('invalidRecord', 'Registration root alias is invalid.');
  }
  const folderIndex = object.folderIndex;
  if (typeof folderIndex !== 'number' || !Number.isSafeInteger(folderIndex) || folderIndex < 0) {
    throw new RegistryError('invalidRecord', 'Registration root index is invalid.');
  }
  return Object.freeze({
    alias,
    folderName: requiredString(object, 'folderName', 512),
    folderIndex,
    lexicalRoot: requiredString(object, 'lexicalRoot'),
    canonicalRoot: requiredString(object, 'canonicalRoot'),
    lexicalComparisonKey: requiredString(object, 'lexicalComparisonKey'),
    canonicalComparisonKey: requiredString(object, 'canonicalComparisonKey'),
  });
};

export const validateRegistrationRecord = (value: JsonValue): RegistrationRecord => {
  const object = objectValue(value);
  const commonRequired = [
    'kind',
    'registryVersion',
    'protocolVersion',
    'instanceId',
    'workspaceId',
    'workspaceGeneration',
    'recordNonce',
    'workspaceName',
    'extensionHostPid',
    'activationStartedAt',
    'publishedAt',
    'updatedAt',
  ] as const;
  const kind = requiredString(object, 'kind', 16);
  if (kind === 'usable') {
    exactKeys(
      object,
      [...commonRequired, 'endpoint', 'authToken', 'rootsFingerprint', 'roots', 'vscodeVersion'],
      ['remoteName'],
    );
    const common = commonFields(object);
    const token = requiredString(object, 'authToken', 43);
    try {
      assertAuthToken(token);
    } catch {
      throw new RegistryError('invalidRecord', 'Registration auth token is invalid.');
    }
    const rootsValue = object.roots;
    if (!Array.isArray(rootsValue) || rootsValue.length < 1 || rootsValue.length > 128) {
      throw new RegistryError('invalidRecord', 'Registration roots are invalid.');
    }
    const roots = Object.freeze(rootsValue.map(parseRoot));
    if (
      roots.some((root, index) => root.folderIndex !== index) ||
      new Set(roots.map((root) => root.alias)).size !== roots.length ||
      new Set(roots.map((root) => root.canonicalComparisonKey)).size !== roots.length
    ) {
      throw new RegistryError('invalidRecord', 'Registration roots are inconsistent.');
    }
    const rootsFingerprint = requiredString(object, 'rootsFingerprint', 64);
    if (!/^[0-9a-f]{64}$/u.test(rootsFingerprint)) {
      throw new RegistryError('invalidRecord', 'Registration roots fingerprint is invalid.');
    }
    const remoteName = object.remoteName;
    if (remoteName !== undefined && (typeof remoteName !== 'string' || remoteName.length === 0 || remoteName.length > 256)) {
      throw new RegistryError('invalidRecord', 'Registration remote name is invalid.');
    }
    return Object.freeze({
      ...common,
      kind,
      endpoint: parseEndpoint(object.endpoint),
      authToken: token,
      rootsFingerprint,
      roots,
      vscodeVersion: requiredString(object, 'vscodeVersion', 128),
      ...(remoteName === undefined ? {} : { remoteName }),
    });
  }
  if (kind === 'unavailable') {
    exactKeys(object, [...commonRequired, 'reasonCode']);
    const reasonCode = requiredString(object, 'reasonCode', 64);
    if (!(UNAVAILABLE_REASON_CODES as readonly string[]).includes(reasonCode)) {
      throw new RegistryError('invalidRecord', 'Registration unavailable reason is invalid.');
    }
    return Object.freeze({
      ...commonFields(object),
      kind,
      reasonCode: reasonCode as UnavailableReasonCode,
    });
  }
  throw new RegistryError('invalidRecord', 'Registration kind is invalid.');
};

export const parseRegistrationRecord = (text: string): RegistrationRecord =>
  validateRegistrationRecord(parseStrictJson(text));

export interface RegistrationSecrets {
  readonly authToken: string;
  readonly recordNonce: string;
}

export const createRegistrationSecrets = (primitives: RuntimePrimitives): RegistrationSecrets => {
  const recordNonce = Buffer.from(primitives.secureRandomBytes(16)).toString('base64url');
  validateRecordNonce(recordNonce);
  return Object.freeze({ authToken: createAuthToken(primitives), recordNonce });
};

export interface RegistrationComparison {
  readonly instanceId: InstanceId;
  readonly workspaceId: WorkspaceId;
  readonly recordNonce: string;
  readonly updatedAt: number;
}

export const registrationComparison = (record: RegistrationRecord): RegistrationComparison =>
  Object.freeze({
    instanceId: record.instanceId,
    workspaceId: record.workspaceId,
    recordNonce: record.recordNonce,
    updatedAt: record.updatedAt,
  });

export const registrationMatchesComparison = (
  record: RegistrationRecord,
  comparison: RegistrationComparison,
): boolean =>
  record.instanceId === comparison.instanceId &&
  record.workspaceId === comparison.workspaceId &&
  record.recordNonce === comparison.recordNonce &&
  record.updatedAt === comparison.updatedAt;

export const registrationLeaseState = (
  record: RegistrationRecord,
  now: number,
): 'fresh' | 'stale' | 'abandoned' => {
  const age = Math.max(0, now - record.updatedAt);
  return age <= REGISTRY_FRESH_MS
    ? 'fresh'
    : age >= REGISTRY_ABANDONED_MS
      ? 'abandoned'
      : 'stale';
};

export interface RegistrationCleanupProbe {
  readonly helloSucceeded: boolean;
  readonly pidDefinitelyDead: boolean;
}

export const decideRegistrationCleanup = (
  record: RegistrationRecord,
  now: number,
  probe: RegistrationCleanupProbe,
): 'delete' | 'degraded' | 'retain' => {
  if (registrationLeaseState(record, now) === 'fresh') {
    return 'retain';
  }
  if (probe.helloSucceeded) {
    return 'degraded';
  }
  if (probe.pidDefinitelyDead || registrationLeaseState(record, now) === 'abandoned') {
    return 'delete';
  }
  return 'retain';
};

export interface RegistrationStoreOptions {
  readonly layout: RuntimeDirectoryLayout;
  readonly primitives: RuntimePrimitives;
  readonly windowsSecurity?: WindowsRuntimeSecurityBoundary;
}

const recordFileName = (instanceId: InstanceId): string => `${instanceId}.json`;

export class RegistrationStore {
  readonly #layout: RuntimeDirectoryLayout;
  readonly #primitives: RuntimePrimitives;
  readonly #windowsSecurity: WindowsRuntimeSecurityBoundary | undefined;

  constructor(options: RegistrationStoreOptions) {
    if (options.layout.platform === 'win32' && options.windowsSecurity === undefined) {
      throw new RuntimeSecurityError(
        'windowsAdapterUnavailable',
        'Windows registry access requires the native security adapter.',
      );
    }
    this.#layout = options.layout;
    this.#primitives = options.primitives;
    this.#windowsSecurity = options.windowsSecurity;
  }

  #recordPath(instanceId: InstanceId): string {
    return path.join(this.#layout.registrations, recordFileName(instanceId));
  }

  async #verifySecureFile(filePath: string): Promise<void> {
    if (this.#windowsSecurity?.verifySecureRegistryFile(filePath) !== true) {
      throw new RegistryError('unsafeRecord', 'Registration file security is invalid.');
    }
  }

  async publish(record: RegistrationRecord): Promise<void> {
    const validated = validateRegistrationRecord(record as unknown as JsonValue);
    const payload = Buffer.from(toStrictJson(validated), 'utf8');
    if (payload.byteLength > REGISTRY_MAX_RECORD_BYTES) {
      throw new RegistryError('recordTooLarge', 'Registration record exceeds its size limit.');
    }
    const temporaryName = `.${validated.instanceId}.${Buffer.from(
      this.#primitives.secureRandomBytes(8),
    ).toString('base64url')}.tmp`;
    const temporaryPath = path.join(this.#layout.registrations, temporaryName);
    const finalPath = this.#recordPath(validated.instanceId);
    let handle;
    try {
      handle = await open(temporaryPath, 'wx', 0o600);
      await handle.writeFile(payload);
      await handle.sync();
      await handle.close();
      handle = undefined;
      await rename(temporaryPath, finalPath);
      await this.#verifySecureFile(finalPath);
    } catch (error) {
      await handle?.close().catch(() => undefined);
      await unlink(temporaryPath).catch(() => undefined);
      if (error instanceof RegistryError) {
        throw error;
      }
      throw new RegistryError('ioFailure', 'Registration publish failed.');
    }
  }

  async #readPath(filePath: string): Promise<RegistrationRecord> {
    await this.#verifySecureFile(filePath);
    let handle;
    try {
      const flags = this.#layout.platform === 'win32'
        ? constants.O_RDONLY
        : constants.O_RDONLY | constants.O_NOFOLLOW;
      handle = await open(filePath, flags);
      const metadata = await handle.stat();
      if (!metadata.isFile() || metadata.size < 1 || metadata.size > REGISTRY_MAX_RECORD_BYTES) {
        throw new RegistryError('recordTooLarge', 'Registration record size is invalid.');
      }
      const payload = await handle.readFile({ encoding: 'utf8' });
      await handle.close();
      handle = undefined;
      return parseRegistrationRecord(payload);
    } catch (error) {
      await handle?.close().catch(() => undefined);
      if (error instanceof RegistryError) {
        throw error;
      }
      throw new RegistryError('invalidRecord', 'Registration record could not be parsed.');
    }
  }

  async read(instanceId: InstanceId): Promise<RegistrationRecord | undefined> {
    const filePath = this.#recordPath(instanceId);
    try {
      await lstat(filePath);
    } catch (error) {
      const code = error !== null && typeof error === 'object' && 'code' in error
        ? (error as { readonly code?: unknown }).code
        : undefined;
      if (code === 'ENOENT') {
        return undefined;
      }
      throw new RegistryError('ioFailure', 'Registration file could not be inspected.');
    }
    return this.#readPath(filePath);
  }

  async #quarantine(filePath: string): Promise<void> {
    const base = path.basename(filePath, '.json');
    const nonce = Buffer.from(this.#primitives.secureRandomBytes(8)).toString('base64url');
    const target = path.join(this.#layout.quarantine, `${base}.${nonce}.invalid`);
    await rename(filePath, target).catch(() => undefined);
  }

  async scan(): Promise<readonly RegistrationRecord[]> {
    let entries;
    try {
      entries = await readdir(this.#layout.registrations, { withFileTypes: true });
    } catch {
      throw new RegistryError('ioFailure', 'Registration directory scan failed.');
    }
    const candidates = entries
      .filter((entry) =>
        (entry.isFile() || entry.isSymbolicLink()) && entry.name.endsWith('.json'),
      )
      .sort((left, right) => left.name < right.name ? -1 : left.name > right.name ? 1 : 0)
      .slice(0, REGISTRY_MAX_RECORDS);
    const records: RegistrationRecord[] = [];
    for (const candidate of candidates) {
      const filePath = path.join(this.#layout.registrations, candidate.name);
      try {
        const record = await this.#readPath(filePath);
        if (recordFileName(record.instanceId) !== candidate.name) {
          throw new RegistryError('invalidRecord', 'Registration filename and identity differ.');
        }
        records.push(record);
      } catch (error) {
        if (error instanceof RegistryError && error.reason === 'versionMismatch') {
          continue;
        }
        await this.#quarantine(filePath);
      }
    }
    return Object.freeze(records);
  }

  async comparisonAndDelete(comparison: RegistrationComparison): Promise<boolean> {
    const filePath = this.#recordPath(comparison.instanceId);
    let record: RegistrationRecord;
    try {
      record = await this.#readPath(filePath);
    } catch {
      return false;
    }
    if (!registrationMatchesComparison(record, comparison)) {
      return false;
    }
    try {
      await unlink(filePath);
      return true;
    } catch {
      return false;
    }
  }
}
