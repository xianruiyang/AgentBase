import { Buffer } from 'node:buffer';
import { createRequire } from 'node:module';
import { join } from 'node:path';

export const SUPPORTED_WINDOWS_ARCHITECTURES = ['x64', 'arm64'] as const;

export type SupportedWindowsArchitecture = (typeof SUPPORTED_WINDOWS_ARCHITECTURES)[number];

export interface NativeBuildInfo {
  readonly abi: 'node-api';
  readonly napiVersion: number;
  readonly targetArch: SupportedWindowsArchitecture | 'unknown';
  readonly securityOperationsImplemented: true;
}

export interface SecureRuntimeDirectoryInfo {
  readonly path: string;
  readonly currentUserSid: string;
  readonly protectedDacl: true;
  readonly reparsePoint: false;
  readonly ownerCurrentUser: true;
  readonly systemFullControl: true;
  readonly otherUsersDenied: true;
}

export interface SecurePipeInspection {
  readonly protectedDacl: true;
  readonly ownerCurrentUser: true;
  readonly currentUserFullControl: true;
  readonly systemFullControl: true;
  readonly otherUsersDenied: true;
  readonly remoteClientsRejected: true;
  readonly byteMode: true;
  readonly firstInstance: true;
  readonly maxInstances: number;
}

interface NativePipeConnection {
  read(maximumBytes?: number): Promise<Buffer | null>;
  write(bytes: Buffer): Promise<void>;
  close(): void;
}

interface NativePipeServer {
  accept(): Promise<NativePipeConnection>;
  close(): void;
  inspectSecurity(): SecurePipeInspection;
}

interface NativeBinding {
  getBuildInfo(): NativeBuildInfo;
  ensureSecureRuntimeDirectory(): SecureRuntimeDirectoryInfo;
  verifySecureRegistryFile(filePath: string): boolean;
  createSecurePipeServer(options: {
    readonly name: string;
    readonly maxInstances: number;
  }): NativePipeServer;
}

export interface SecureRawByteConnection {
  read(): Promise<Uint8Array | null>;
  write(bytes: Uint8Array): Promise<void>;
  close(): Promise<void>;
}

export interface SecureRawByteServer {
  accept(): Promise<SecureRawByteConnection>;
  close(): Promise<void>;
  inspectSecurity(): SecurePipeInspection;
}

const requireNative = createRequire(__filename);
let cachedBinding: NativeBinding | undefined;

function assertTrue(value: boolean, message: string): asserts value {
  if (!value) {
    throw new Error(message);
  }
}

const loadNativeBinding = (): NativeBinding => {
  if (process.platform !== 'win32') {
    throw new Error('The Windows security adapter is only loadable on Windows.');
  }
  if (cachedBinding !== undefined) {
    return cachedBinding;
  }
  let binding: NativeBinding;
  try {
    const bindingPath = join(__dirname, '..', 'build', 'Release', 'win32_security.node');
    binding = requireNative(bindingPath) as NativeBinding;
  } catch {
    throw new Error('The native Windows security adapter could not be loaded.');
  }
  const info = binding.getBuildInfo();
  assertTrue(
    info.abi === 'node-api' &&
      info.napiVersion >= 8 &&
      info.securityOperationsImplemented === true &&
      info.targetArch === process.arch,
    'The native Windows security adapter contract or architecture is invalid.',
  );
  assertTrue(
    typeof binding.ensureSecureRuntimeDirectory === 'function' &&
      typeof binding.verifySecureRegistryFile === 'function' &&
      typeof binding.createSecurePipeServer === 'function',
    'The native Windows security adapter is incomplete.',
  );
  cachedBinding = binding;
  return binding;
};

export const getNativeBuildInfo = (): NativeBuildInfo =>
  Object.freeze({ ...loadNativeBinding().getBuildInfo() });

export const ensureSecureRuntimeDirectory = (): SecureRuntimeDirectoryInfo => {
  const info = loadNativeBinding().ensureSecureRuntimeDirectory();
  assertTrue(
    info.path.length > 0 &&
      info.currentUserSid.startsWith('S-1-') &&
      info.protectedDacl &&
      !info.reparsePoint &&
      info.ownerCurrentUser &&
      info.systemFullControl &&
      info.otherUsersDenied,
    'The Windows runtime directory failed security verification.',
  );
  return Object.freeze({ ...info });
};

export const verifySecureRegistryFile = (filePath: string): boolean => {
  if (filePath.length === 0) {
    return false;
  }
  return loadNativeBinding().verifySecureRegistryFile(filePath);
};

class RawConnectionAdapter implements SecureRawByteConnection {
  readonly #native: NativePipeConnection;

  constructor(native: NativePipeConnection) {
    this.#native = native;
  }

  async read(): Promise<Uint8Array | null> {
    const chunk = await this.#native.read(65_536);
    return chunk === null ? null : Buffer.from(chunk);
  }

  write(bytes: Uint8Array): Promise<void> {
    return this.#native.write(Buffer.from(bytes));
  }

  close(): Promise<void> {
    this.#native.close();
    return Promise.resolve();
  }
}

class RawServerAdapter implements SecureRawByteServer {
  readonly #native: NativePipeServer;

  constructor(native: NativePipeServer) {
    this.#native = native;
  }

  async accept(): Promise<SecureRawByteConnection> {
    return new RawConnectionAdapter(await this.#native.accept());
  }

  close(): Promise<void> {
    this.#native.close();
    return Promise.resolve();
  }

  inspectSecurity(): SecurePipeInspection {
    const inspection = this.#native.inspectSecurity();
    assertTrue(
      inspection.protectedDacl &&
        inspection.ownerCurrentUser &&
        inspection.currentUserFullControl &&
        inspection.systemFullControl &&
        inspection.otherUsersDenied &&
        inspection.remoteClientsRejected &&
        inspection.byteMode &&
        inspection.firstInstance &&
        inspection.maxInstances >= 1 &&
        inspection.maxInstances <= 4,
      'The Windows pipe failed security verification.',
    );
    return Object.freeze({ ...inspection });
  }
}

export const createSecurePipeServer = (
  options: { readonly name: string; readonly maxInstances?: number },
): SecureRawByteServer => {
  if (!options.name.startsWith('\\\\.\\pipe\\vscode-lsp-mcp-')) {
    throw new Error('Secure pipe name is outside the component namespace.');
  }
  const maxInstances = options.maxInstances ?? 4;
  if (!Number.isSafeInteger(maxInstances) || maxInstances < 1 || maxInstances > 4) {
    throw new RangeError('Secure pipe maxInstances must be from 1 through 4.');
  }
  const server = new RawServerAdapter(
    loadNativeBinding().createSecurePipeServer({ name: options.name, maxInstances }),
  );
  server.inspectSecurity();
  return server;
};
