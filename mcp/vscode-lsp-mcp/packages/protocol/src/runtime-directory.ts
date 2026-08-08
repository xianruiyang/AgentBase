import { Buffer } from 'node:buffer';
import { open, chmod, lstat, mkdir, unlink } from 'node:fs/promises';
import path from 'node:path';
import type { RuntimePrimitives } from './runtime.js';
import type { InstanceId } from './workspace-identity.js';

export type RuntimePlatform = 'darwin' | 'linux' | 'win32';

export interface RuntimeDirectoryLayout {
  readonly platform: RuntimePlatform;
  readonly root: string;
  readonly registrations: string;
  readonly quarantine: string;
}

export interface WindowsRuntimeDirectoryInfo {
  readonly path: string;
  readonly currentUserSid: string;
  readonly protectedDacl: true;
  readonly reparsePoint: false;
}

export interface WindowsRuntimeSecurityBoundary {
  ensureSecureRuntimeDirectory(): WindowsRuntimeDirectoryInfo;
  verifySecureRegistryFile(filePath: string): boolean;
}

export class RuntimeSecurityError extends Error {
  readonly reason:
    | 'endpointPathTooLong'
    | 'filesystemFailure'
    | 'insecureDirectory'
    | 'insecureSocket'
    | 'unsupportedPlatform'
    | 'windowsAdapterUnavailable';

  constructor(reason: RuntimeSecurityError['reason'], message: string) {
    super(message);
    this.name = 'RuntimeSecurityError';
    this.reason = reason;
  }
}

const uidHash = (uid: number, primitives: Pick<RuntimePrimitives, 'sha256Hex'>): string =>
  primitives.sha256Hex(new TextEncoder().encode(String(uid))).slice(0, 12);

export interface RuntimeDirectoryDerivationOptions {
  readonly platform: RuntimePlatform;
  readonly environment: Readonly<Record<string, string | undefined>>;
  readonly uid?: number;
  readonly windowsSecurity?: WindowsRuntimeSecurityBoundary;
}

export const deriveRuntimeDirectoryRoot = (
  options: RuntimeDirectoryDerivationOptions,
  primitives: Pick<RuntimePrimitives, 'sha256Hex'>,
): { readonly root: string; readonly currentUserSid?: string } => {
  if (options.platform === 'win32') {
    if (options.windowsSecurity === undefined) {
      throw new RuntimeSecurityError(
        'windowsAdapterUnavailable',
        'The secure Windows runtime adapter is required.',
      );
    }
    const info = options.windowsSecurity.ensureSecureRuntimeDirectory();
    if (!info.protectedDacl || info.reparsePoint) {
      throw new RuntimeSecurityError('insecureDirectory', 'Windows runtime directory is unsafe.');
    }
    return Object.freeze({ root: path.win32.normalize(info.path), currentUserSid: info.currentUserSid });
  }

  const uid = options.uid ?? (typeof process.getuid === 'function' ? process.getuid() : undefined);
  if (uid === undefined || !Number.isSafeInteger(uid) || uid < 0) {
    throw new RuntimeSecurityError('unsupportedPlatform', 'A numeric Unix uid is required.');
  }
  const shortHash = uidHash(uid, primitives);
  if (options.platform === 'linux') {
    const xdg = options.environment.XDG_RUNTIME_DIR;
    return Object.freeze({
      root: xdg !== undefined && path.posix.isAbsolute(xdg)
        ? path.posix.join(xdg, 'vscode-lsp-mcp')
        : `/tmp/vlm-${shortHash}`,
    });
  }
  const temporary = options.environment.TMPDIR;
  return Object.freeze({
    root: temporary !== undefined && path.posix.isAbsolute(temporary)
      ? path.posix.join(temporary, `vscode-lsp-mcp-${shortHash}`)
      : `/tmp/vlm-${shortHash}`,
  });
};

export interface PosixSecurityMetadata {
  readonly isDirectory: boolean;
  readonly isSymbolicLink: boolean;
  readonly mode: number;
  readonly uid: number;
}

export const assertSecurePosixDirectoryMetadata = (
  metadata: PosixSecurityMetadata,
  expectedUid: number,
): void => {
  if (
    !metadata.isDirectory ||
    metadata.isSymbolicLink ||
    metadata.uid !== expectedUid ||
    (metadata.mode & 0o777) !== 0o700
  ) {
    throw new RuntimeSecurityError('insecureDirectory', 'Unix runtime directory is unsafe.');
  }
};

const ensurePosixDirectory = async (directory: string, uid: number): Promise<void> => {
  try {
    await mkdir(directory, { recursive: true, mode: 0o700 });
    const before = await lstat(directory);
    if (!before.isDirectory() || before.isSymbolicLink() || before.uid !== uid) {
      throw new RuntimeSecurityError('insecureDirectory', 'Unix runtime directory is unsafe.');
    }
    if ((before.mode & 0o777) !== 0o700) {
      await chmod(directory, 0o700);
    }
    const after = await lstat(directory);
    assertSecurePosixDirectoryMetadata({
      isDirectory: after.isDirectory(),
      isSymbolicLink: after.isSymbolicLink(),
      mode: after.mode,
      uid: after.uid,
    }, uid);
  } catch (error) {
    if (error instanceof RuntimeSecurityError) {
      throw error;
    }
    throw new RuntimeSecurityError('filesystemFailure', 'Unix runtime directory setup failed.');
  }
};

export const ensureRuntimeDirectory = async (
  options: RuntimeDirectoryDerivationOptions,
  primitives: Pick<RuntimePrimitives, 'sha256Hex'>,
): Promise<RuntimeDirectoryLayout> => {
  const derived = deriveRuntimeDirectoryRoot(options, primitives);
  const pathApi = options.platform === 'win32' ? path.win32 : path.posix;
  const registrations = pathApi.join(derived.root, 'registrations');
  const quarantine = pathApi.join(derived.root, 'quarantine');
  if (options.platform !== 'win32') {
    const uid = options.uid ?? (typeof process.getuid === 'function' ? process.getuid() : undefined);
    if (uid === undefined) {
      throw new RuntimeSecurityError('unsupportedPlatform', 'A numeric Unix uid is required.');
    }
    await ensurePosixDirectory(derived.root, uid);
    await ensurePosixDirectory(registrations, uid);
    await ensurePosixDirectory(quarantine, uid);
  } else {
    try {
      await mkdir(registrations, { recursive: true });
      await mkdir(quarantine, { recursive: true });
    } catch {
      throw new RuntimeSecurityError('filesystemFailure', 'Windows runtime subdirectory setup failed.');
    }
  }
  return Object.freeze({ platform: options.platform, root: derived.root, registrations, quarantine });
};

export const createIpcEndpoint = (
  layout: RuntimeDirectoryLayout,
  instanceId: InstanceId,
  primitives: Pick<RuntimePrimitives, 'sha256Hex'>,
  currentUserSid?: string,
): { readonly kind: 'namedPipe' | 'unix'; readonly address: string } => {
  const compactInstance = instanceId.replaceAll('-', '');
  if (layout.platform === 'win32') {
    if (currentUserSid === undefined || currentUserSid.length === 0) {
      throw new RuntimeSecurityError('windowsAdapterUnavailable', 'Current Windows SID is required.');
    }
    const sidHash = primitives
      .sha256Hex(new TextEncoder().encode(currentUserSid))
      .slice(0, 12);
    return Object.freeze({
      kind: 'namedPipe',
      address: `\\\\.\\pipe\\vscode-lsp-mcp-${sidHash}-${compactInstance}`,
    });
  }
  const address = path.posix.join(layout.root, `i-${compactInstance.slice(0, 24)}.sock`);
  if (Buffer.byteLength(address, 'utf8') > 100) {
    throw new RuntimeSecurityError('endpointPathTooLong', 'Unix socket endpoint exceeds 100 bytes.');
  }
  return Object.freeze({ kind: 'unix', address });
};

export interface PosixSocketSecurityMetadata {
  readonly isSocket: boolean;
  readonly isSymbolicLink: boolean;
  readonly mode: number;
  readonly uid: number;
}

export const assertSecurePosixSocketMetadata = (
  metadata: PosixSocketSecurityMetadata,
  expectedUid: number,
): void => {
  if (
    !metadata.isSocket ||
    metadata.isSymbolicLink ||
    metadata.uid !== expectedUid ||
    (metadata.mode & 0o777) !== 0o600
  ) {
    throw new RuntimeSecurityError('insecureSocket', 'Unix socket endpoint is unsafe.');
  }
};

export const secureUnixSocketAfterBind = async (
  endpoint: string,
  expectedUid: number,
): Promise<void> => {
  try {
    await chmod(endpoint, 0o600);
    const metadata = await lstat(endpoint);
    assertSecurePosixSocketMetadata({
      isSocket: metadata.isSocket(),
      isSymbolicLink: metadata.isSymbolicLink(),
      mode: metadata.mode,
      uid: metadata.uid,
    }, expectedUid);
  } catch (error) {
    if (error instanceof RuntimeSecurityError) {
      throw error;
    }
    throw new RuntimeSecurityError('filesystemFailure', 'Unix socket security verification failed.');
  }
};

export interface StaleUnixSocketCleanupOptions {
  readonly endpoint: string;
  readonly expectedEndpoint: string;
  readonly expectedUid: number;
  readonly hasValidRegistration: boolean;
  readonly canConnect: () => Promise<boolean>;
  readonly filesystem?: StaleUnixSocketFilesystem;
}

export interface StaleUnixSocketMetadata {
  readonly uid: number;
  isSocket(): boolean;
  isSymbolicLink(): boolean;
}

export interface StaleUnixSocketFilesystem {
  lstat(endpoint: string): Promise<StaleUnixSocketMetadata>;
  unlink(endpoint: string): Promise<void>;
}

const systemStaleUnixSocketFilesystem: StaleUnixSocketFilesystem = Object.freeze({
  lstat,
  unlink,
});

export const cleanupStaleUnixSocket = async (
  options: StaleUnixSocketCleanupOptions,
): Promise<boolean> => {
  if (options.endpoint !== options.expectedEndpoint || options.hasValidRegistration) {
    return false;
  }
  const filesystem = options.filesystem ?? systemStaleUnixSocketFilesystem;
  let metadata;
  try {
    metadata = await filesystem.lstat(options.endpoint);
  } catch {
    return false;
  }
  if (
    !metadata.isSocket() ||
    metadata.isSymbolicLink() ||
    metadata.uid !== options.expectedUid
  ) {
    return false;
  }
  if (await options.canConnect()) {
    return false;
  }
  try {
    await filesystem.unlink(options.endpoint);
    return true;
  } catch {
    return false;
  }
};

export const flushDirectoryBestEffort = async (directory: string): Promise<void> => {
  if (process.platform === 'win32') {
    return;
  }
  try {
    const handle = await open(directory, 'r');
    try {
      await handle.sync();
    } finally {
      await handle.close();
    }
  } catch {
    // The file payload itself is already fsynced; unsupported directory fsync is non-fatal.
  }
};
