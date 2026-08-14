import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import type { RuntimePrimitives } from './runtime.js';
import type { InstanceId } from './workspace-identity.js';

export type RuntimePlatform = 'win32';

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
    | 'filesystemFailure'
    | 'insecureDirectory'
    | 'unsupportedPlatform'
    | 'windowsAdapterUnavailable';

  constructor(reason: RuntimeSecurityError['reason'], message: string) {
    super(message);
    this.name = 'RuntimeSecurityError';
    this.reason = reason;
  }
}

export interface RuntimeDirectoryDerivationOptions {
  readonly platform: RuntimePlatform;
  readonly environment: Readonly<Record<string, string | undefined>>;
  readonly windowsSecurity?: WindowsRuntimeSecurityBoundary;
}

export const deriveRuntimeDirectoryRoot = (
  options: RuntimeDirectoryDerivationOptions,
): { readonly root: string; readonly currentUserSid: string } => {
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
  return Object.freeze({
    root: path.win32.normalize(info.path),
    currentUserSid: info.currentUserSid,
  });
};

export const ensureRuntimeDirectory = async (
  options: RuntimeDirectoryDerivationOptions,
): Promise<RuntimeDirectoryLayout> => {
  const derived = deriveRuntimeDirectoryRoot(options);
  const registrations = path.win32.join(derived.root, 'registrations');
  const quarantine = path.win32.join(derived.root, 'quarantine');
  try {
    await mkdir(registrations, { recursive: true });
    await mkdir(quarantine, { recursive: true });
  } catch {
    throw new RuntimeSecurityError('filesystemFailure', 'Windows runtime subdirectory setup failed.');
  }
  return Object.freeze({
    platform: options.platform,
    root: derived.root,
    registrations,
    quarantine,
  });
};

export const createIpcEndpoint = (
  _layout: RuntimeDirectoryLayout,
  instanceId: InstanceId,
  primitives: Pick<RuntimePrimitives, 'sha256Hex'>,
  currentUserSid?: string,
): { readonly kind: 'namedPipe'; readonly address: string } => {
  if (currentUserSid === undefined || currentUserSid.length === 0) {
    throw new RuntimeSecurityError('windowsAdapterUnavailable', 'Current Windows SID is required.');
  }
  const compactInstance = instanceId.replaceAll('-', '');
  const sidHash = primitives
    .sha256Hex(new TextEncoder().encode(currentUserSid))
    .slice(0, 12);
  return Object.freeze({
    kind: 'namedPipe',
    address: `\\\\.\\pipe\\vscode-lsp-mcp-${sidHash}-${compactInstance}`,
  });
};
