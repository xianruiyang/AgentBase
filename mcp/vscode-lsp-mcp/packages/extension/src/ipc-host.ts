import {
  createUnixRawByteServer,
  type RawByteServer,
  type RegistrationEndpoint,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  createSecurePipeServer,
  type SecureRawByteServer,
} from '@simplechat/vscode-lsp-mcp-win32-security';

export interface WindowsSecureServerFactory {
  create(options: { readonly name: string; readonly maxInstances: number }): SecureRawByteServer;
}

export interface ExtensionTransportHostOptions {
  readonly endpoint: RegistrationEndpoint;
  readonly platform: 'darwin' | 'linux' | 'win32';
  readonly unixUid?: number;
  readonly windowsFactory?: WindowsSecureServerFactory | null;
  readonly unixFactory?: (address: string, uid: number) => Promise<RawByteServer>;
}

export const MAX_BRIDGE_CONNECTIONS = 4;

export class ExtensionTransportHostError extends Error {
  readonly reason: 'endpointMismatch' | 'secureAdapterUnavailable';

  constructor(reason: ExtensionTransportHostError['reason'], message: string) {
    super(message);
    this.name = 'ExtensionTransportHostError';
    this.reason = reason;
  }
}

const defaultWindowsFactory: WindowsSecureServerFactory = Object.freeze({
  create: (options: { readonly name: string; readonly maxInstances: number }) =>
    createSecurePipeServer(options),
});

export const createExtensionTransportServer = async (
  options: ExtensionTransportHostOptions,
): Promise<RawByteServer> => {
  if (options.platform === 'win32') {
    if (options.endpoint.kind !== 'namedPipe') {
      throw new ExtensionTransportHostError(
        'endpointMismatch',
        'Windows transport requires a named pipe endpoint.',
      );
    }
    const factory = options.windowsFactory === undefined
      ? defaultWindowsFactory
      : options.windowsFactory;
    if (factory === null) {
      throw new ExtensionTransportHostError(
        'secureAdapterUnavailable',
        'Secure Windows pipe adapter is unavailable; transport failed closed.',
      );
    }
    return factory.create({
      name: options.endpoint.address,
      maxInstances: MAX_BRIDGE_CONNECTIONS,
    });
  }

  if (options.endpoint.kind !== 'unix' || options.unixUid === undefined) {
    throw new ExtensionTransportHostError(
      'endpointMismatch',
      'Unix transport requires a Unix endpoint and uid.',
    );
  }
  const unixFactory = options.unixFactory ?? createUnixRawByteServer;
  return unixFactory(options.endpoint.address, options.unixUid);
};
