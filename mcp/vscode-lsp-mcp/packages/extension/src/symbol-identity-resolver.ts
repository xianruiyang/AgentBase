import type { Position as VscodePosition } from 'vscode';
import {
  WorkspaceBoundaryError,
  logicalPathFromProviderLocation,
  systemWorkspacePathAccess,
  type WorkspacePathAccess,
  type WorkspacePathContext,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  ProviderRuntime,
  classifyArrayProviderResult,
  type ProviderCommandAdapter,
  type ProviderInvocationResult,
  type PublicProviderCommand,
  type VscodeProviderHost,
} from './provider-runtime.js';

export interface SymbolIdentityPosition {
  readonly file: string;
  readonly line: number;
  readonly column: number;
}

export interface SymbolIdentityHost extends VscodeProviderHost {
  createPosition(line: number, character: number): VscodePosition;
}

export type SymbolIdentityFailureStatus =
  | 'unresolved'
  | 'unavailable'
  | 'notReady'
  | 'cancelled'
  | 'timedOut'
  | 'failed'
  | 'positionOutOfRange'
  | 'budgetExceeded';

export type SymbolIdentityResolution =
  | { readonly status: 'resolved'; readonly anchors: readonly string[] }
  | { readonly status: SymbolIdentityFailureStatus };

export type SymbolIdentityVerification =
  | { readonly status: 'verified' }
  | { readonly status: 'mismatched' }
  | { readonly status: SymbolIdentityFailureStatus };

export interface SymbolIdentityResolverOptions {
  readonly defaultTimeoutMs?: number;
  readonly maximumAnchors?: number;
  readonly pathAccess?: WorkspacePathAccess;
}

interface ProviderPoint {
  readonly line: number;
  readonly character: number;
}

interface ProviderLocation {
  readonly point: ProviderPoint;
  readonly uri: { readonly scheme: string; readonly fsPath: string };
}

const DEFAULT_MAXIMUM_ANCHORS = 32;

const asRecord = (value: unknown): Record<string, unknown> | undefined =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;

const pointFromRange = (value: unknown): ProviderPoint | undefined => {
  const range = asRecord(value);
  const start = asRecord(range?.start);
  if (start === undefined ||
      !Number.isSafeInteger(start.line) || (start.line as number) < 0 ||
      (start.line as number) >= Number.MAX_SAFE_INTEGER ||
      !Number.isSafeInteger(start.character) || (start.character as number) < 0 ||
      (start.character as number) >= Number.MAX_SAFE_INTEGER) {
    return undefined;
  }
  return Object.freeze({
    line: start.line as number,
    character: start.character as number,
  });
};

const providerLocation = (value: unknown): ProviderLocation | undefined => {
  const record = asRecord(value);
  if (record === undefined) return undefined;
  const rawUri = record.targetUri ?? record.uri;
  const uri = asRecord(rawUri);
  const point = record.targetUri === undefined
    ? pointFromRange(record.range)
    : pointFromRange(record.targetSelectionRange ?? record.targetRange);
  if (uri === undefined || typeof uri.scheme !== 'string' || typeof uri.fsPath !== 'string' ||
      point === undefined) {
    return undefined;
  }
  return Object.freeze({
    point,
    uri: Object.freeze({ scheme: uri.scheme, fsPath: uri.fsPath }),
  });
};

const samePosition = (left: VscodePosition, right: VscodePosition): boolean =>
  left.line === right.line && left.character === right.character;

const identityAdapter = (
  host: SymbolIdentityHost,
  command: PublicProviderCommand,
): ProviderCommandAdapter<SymbolIdentityPosition, readonly unknown[]> => ({
  command,
  requiresDocument: true,
  buildArguments: (input, document) => {
    if (document === undefined) throw new RangeError('Identity document was not activated.');
    const requested = host.createPosition(input.line - 1, input.column - 1);
    const validated = document.validatePosition(requested);
    if (!samePosition(requested, validated)) {
      throw new RangeError('Identity position is outside the document.');
    }
    return [document.uri, requested];
  },
  classifyResult: classifyArrayProviderResult,
});

const invocationStatus = (
  result: ProviderInvocationResult<readonly unknown[]>,
): SymbolIdentityFailureStatus => {
  if (result.status === 'completed') {
    throw new TypeError('Completed identity invocation has no failure status.');
  }
  if (result.status === 'failed' && result.reason === 'providerArgumentsInvalid') {
    return 'positionOutOfRange';
  }
  return result.status;
};

const recoverableEmptyStatus = (status: SymbolIdentityFailureStatus): boolean =>
  status === 'unresolved' || status === 'unavailable' || status === 'notReady';

export class SymbolIdentityResolver {
  readonly #host: SymbolIdentityHost;
  readonly #maximumAnchors: number;
  readonly #pathAccess: WorkspacePathAccess;
  readonly #runtime: ProviderRuntime;

  constructor(host: SymbolIdentityHost, options: SymbolIdentityResolverOptions = {}) {
    this.#host = host;
    this.#maximumAnchors = options.maximumAnchors ?? DEFAULT_MAXIMUM_ANCHORS;
    if (!Number.isSafeInteger(this.#maximumAnchors) || this.#maximumAnchors < 1 ||
        this.#maximumAnchors > 256) {
      throw new RangeError('Symbol identity anchor budget must be from 1 through 256.');
    }
    this.#pathAccess = options.pathAccess ?? systemWorkspacePathAccess;
    this.#runtime = new ProviderRuntime({
      host,
      pathAccess: this.#pathAccess,
      ...(options.defaultTimeoutMs === undefined
        ? {}
        : { defaultTimeoutMs: options.defaultTimeoutMs }),
    });
  }

  async #resolveCommand(
    context: WorkspacePathContext,
    command: 'vscode.executeDefinitionProvider' | 'vscode.executeDeclarationProvider',
    position: SymbolIdentityPosition,
    signal: AbortSignal,
    timeoutMs?: number,
    allowOutsideWorkspace = false,
  ): Promise<SymbolIdentityResolution> {
    let invocation: ProviderInvocationResult<readonly unknown[]>;
    try {
      invocation = await this.#runtime.invoke(
        context,
        identityAdapter(this.#host, command),
        position,
        {
          logicalFile: position.file,
          pollDelaysMs: [0],
          signal,
          ...(timeoutMs === undefined ? {} : { timeoutMs }),
        },
      );
    } catch (error) {
      if (error instanceof WorkspaceBoundaryError) return { status: 'failed' };
      return { status: 'failed' };
    }
    if (invocation.status !== 'completed') {
      return Object.freeze({ status: invocationStatus(invocation) });
    }
    if (invocation.value.length > this.#maximumAnchors) {
      return Object.freeze({ status: 'budgetExceeded' });
    }
    const anchors = new Set<string>();
    for (const raw of invocation.value) {
      const location = providerLocation(raw);
      if (location === undefined) return Object.freeze({ status: 'failed' });
      try {
        const mapped = await logicalPathFromProviderLocation(context, {
          uriScheme: location.uri.scheme,
          lexicalAbsolutePath: location.uri.fsPath,
        }, this.#pathAccess);
        const file = context.platform === 'win32'
          ? mapped.logicalPath.toLowerCase()
          : mapped.logicalPath;
        anchors.add(JSON.stringify([file, location.point.line, location.point.character]));
      } catch (error) {
        if (!allowOutsideWorkspace || !(error instanceof WorkspaceBoundaryError) ||
            location.uri.scheme.length > 64 || location.uri.fsPath.length > 4_096) {
          return Object.freeze({ status: 'failed' });
        }
        const scheme = location.uri.scheme.toLowerCase();
        const externalPath = context.platform === 'win32'
          ? location.uri.fsPath.replaceAll('\\', '/').toLowerCase()
          : location.uri.fsPath;
        anchors.add(JSON.stringify([
          'outside-workspace',
          scheme,
          externalPath,
          location.point.line,
          location.point.character,
        ]));
      }
      if (anchors.size > this.#maximumAnchors) {
        return Object.freeze({ status: 'budgetExceeded' });
      }
    }
    return anchors.size === 0
      ? Object.freeze({ status: 'unresolved' })
      : Object.freeze({ status: 'resolved', anchors: Object.freeze([...anchors].sort()) });
  }

  async resolveTarget(
    context: WorkspacePathContext,
    position: SymbolIdentityPosition,
    signal: AbortSignal,
    timeoutMs?: number,
  ): Promise<SymbolIdentityResolution> {
    const definition = await this.#resolveCommand(
      context,
      'vscode.executeDefinitionProvider',
      position,
      signal,
      timeoutMs,
    );
    // A resolved definition is already a stable semantic identity. Asking the
    // declaration provider as well can double (or, for cpptools, multiply) the
    // latency without making candidate verification safer: candidates are
    // verified against their definition first too.
    if (definition.status === 'resolved') return definition;
    if (!recoverableEmptyStatus(definition.status)) return definition;
    const declaration = await this.#resolveCommand(
      context,
      'vscode.executeDeclarationProvider',
      position,
      signal,
      timeoutMs,
    );
    if (declaration.status !== 'resolved') {
      if (!recoverableEmptyStatus(declaration.status)) return declaration;
      return definition.status === 'notReady' || declaration.status === 'notReady'
        ? Object.freeze({ status: 'notReady' })
        : definition.status === 'unavailable' && declaration.status === 'unavailable'
          ? Object.freeze({ status: 'unavailable' })
          : Object.freeze({ status: 'unresolved' });
    }
    return declaration;
  }

  async verifyCandidate(
    context: WorkspacePathContext,
    position: SymbolIdentityPosition,
    targetAnchors: ReadonlySet<string>,
    signal: AbortSignal,
    timeoutMs?: number,
  ): Promise<SymbolIdentityVerification> {
    const definition = await this.#resolveCommand(
      context,
      'vscode.executeDefinitionProvider',
      position,
      signal,
      timeoutMs,
      true,
    );
    if (definition.status === 'resolved') {
      return definition.anchors.every((anchor) => targetAnchors.has(anchor))
        ? Object.freeze({ status: 'verified' })
        : Object.freeze({ status: 'mismatched' });
    }
    if (!recoverableEmptyStatus(definition.status)) return definition;

    const declaration = await this.#resolveCommand(
      context,
      'vscode.executeDeclarationProvider',
      position,
      signal,
      timeoutMs,
      true,
    );
    if (declaration.status === 'resolved') {
      return declaration.anchors.every((anchor) => targetAnchors.has(anchor))
        ? Object.freeze({ status: 'verified' })
        : Object.freeze({ status: 'mismatched' });
    }
    if (!recoverableEmptyStatus(declaration.status)) return declaration;
    return definition.status === 'notReady' || declaration.status === 'notReady'
      ? Object.freeze({ status: 'notReady' })
      : definition.status === 'unavailable' && declaration.status === 'unavailable'
        ? Object.freeze({ status: 'unavailable' })
        : Object.freeze({ status: 'unresolved' });
  }
}
