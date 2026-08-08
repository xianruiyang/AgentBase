import type { TextDocument } from 'vscode';
import {
  CAPABILITIES_BRIDGE_METHOD,
  CAPABILITY_NAMES,
  resolveLogicalPath,
  systemWorkspacePathAccess,
  type Capability,
  type CapabilityName,
  type CapabilityProbeReason,
  type IpcRequest,
  type JsonValue,
  type WorkspacePathAccess,
  type WorkspacePathContext,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  PROVIDER_DEFAULT_TIMEOUT_MS,
  ProviderRuntime,
  type ProviderCommandAdapter,
  type ProviderInvocationResult,
  type PublicProviderCommand,
  type VscodeProviderHost,
} from './provider-runtime.js';

interface CapabilitiesBridgeParams {
  readonly file?: string;
  readonly capabilities: readonly CapabilityName[];
}

type ProbeEvidence = 'positive' | 'empty';

export interface CapabilitiesProviderHost extends VscodeProviderHost {
  createPosition(line: number, character: number): unknown;
  createRange(startLine: number, startCharacter: number, endLine: number, endCharacter: number): unknown;
  getDiagnostics(resource?: unknown): unknown;
}

export type CapabilitiesBridgeHandler = (
  context: WorkspacePathContext,
  request: IpcRequest,
  signal: AbortSignal,
) => Promise<JsonValue | undefined>;

const capabilityNames = new Set<CapabilityName>(CAPABILITY_NAMES);

const asRecord = (value: unknown): Record<string, unknown> | undefined =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;

const parseParams = (value: unknown): CapabilitiesBridgeParams | undefined => {
  const record = asRecord(value);
  if (record === undefined ||
      Object.keys(record).some((field) => field !== 'file' && field !== 'capabilities') ||
      (record.file !== undefined && (typeof record.file !== 'string' || record.file.length === 0)) ||
      !Array.isArray(record.capabilities) || record.capabilities.length === 0 ||
      record.capabilities.length > CAPABILITY_NAMES.length ||
      new Set(record.capabilities).size !== record.capabilities.length ||
      record.capabilities.some((name) => typeof name !== 'string' ||
        !capabilityNames.has(name as CapabilityName))) {
    return undefined;
  }
  return Object.freeze({
    ...(record.file === undefined ? {} : { file: record.file as string }),
    capabilities: Object.freeze([...record.capabilities]) as readonly CapabilityName[],
  });
};

const classifyArray = (value: unknown) => {
  if (value === undefined) return { status: 'notReady' } as const;
  return Array.isArray(value)
    ? { status: 'ready', value: value.length > 0 ? 'positive' : 'empty' } as const
    : { status: 'invalid' } as const;
};

const classifyDefined = (value: unknown) => value === undefined || value === null
  ? { status: 'notReady' } as const
  : { status: 'ready', value: 'positive' } as const;

const adapter = (
  command: PublicProviderCommand,
  requiresDocument: boolean,
  buildArguments: (document: TextDocument | undefined) => readonly unknown[],
  classifyResult: (value: unknown) =>
    | { readonly status: 'ready'; readonly value: ProbeEvidence }
    | { readonly status: 'notReady' | 'invalid' },
): ProviderCommandAdapter<null, ProbeEvidence> => ({
  command,
  requiresDocument,
  buildArguments: (_input, document) => buildArguments(document),
  classifyResult,
});

const requireDocument = (document: TextDocument | undefined): TextDocument => {
  if (document === undefined) throw new Error('Capability probe document was not activated.');
  return document;
};

const providerAdapter = (
  host: CapabilitiesProviderHost,
  capability: CapabilityName,
): ProviderCommandAdapter<null, ProbeEvidence> | undefined => {
  const position = () => host.createPosition(0, 0);
  const range = () => host.createRange(0, 0, 0, 0);
  const documentArray = (command: PublicProviderCommand, extras: readonly unknown[] = []) =>
    adapter(command, true, (document) => [requireDocument(document).uri, ...extras], classifyArray);
  const documentPositionArray = (command: PublicProviderCommand) =>
    adapter(command, true, (document) => [requireDocument(document).uri, position()], classifyArray);
  const documentPositionDefined = (command: PublicProviderCommand) =>
    adapter(command, true, (document) => [requireDocument(document).uri, position()], classifyDefined);

  if (capability === 'workspaceSymbols') {
    return adapter(
      'vscode.executeWorkspaceSymbolProvider',
      false,
      () => ['__vscode_lsp_mcp_capability_probe__'],
      classifyArray,
    );
  }
  if (capability === 'documentSymbols') {
    return documentArray('vscode.executeDocumentSymbolProvider');
  }
  if (capability === 'hover') return documentPositionArray('vscode.executeHoverProvider');
  if (capability === 'declaration') return documentPositionArray('vscode.executeDeclarationProvider');
  if (capability === 'definition') return documentPositionArray('vscode.executeDefinitionProvider');
  if (capability === 'typeDefinition') {
    return documentPositionArray('vscode.executeTypeDefinitionProvider');
  }
  if (capability === 'implementation') {
    return documentPositionArray('vscode.executeImplementationProvider');
  }
  if (capability === 'signatureHelp') {
    return documentPositionDefined('vscode.executeSignatureHelpProvider');
  }
  if (capability === 'references') return documentPositionArray('vscode.executeReferenceProvider');
  if (capability === 'callHierarchy') return documentPositionArray('vscode.prepareCallHierarchy');
  if (capability === 'typeHierarchy') return documentPositionArray('vscode.prepareTypeHierarchy');
  if (capability === 'rename') return documentPositionDefined('vscode.prepareRename');
  if (capability === 'codeActions') {
    return adapter(
      'vscode.executeCodeActionProvider',
      true,
      (document) => [requireDocument(document).uri, range()],
      classifyArray,
    );
  }
  if (capability === 'documentFormatting') {
    return documentArray('vscode.executeFormatDocumentProvider', [{ tabSize: 4, insertSpaces: true }]);
  }
  if (capability === 'rangeFormatting') {
    return adapter(
      'vscode.executeFormatRangeProvider',
      true,
      (document) => [
        requireDocument(document).uri,
        range(),
        { tabSize: 4, insertSpaces: true },
      ],
      classifyArray,
    );
  }
  return undefined;
};

const unavailable = (
  name: CapabilityName,
  status: Exclude<Capability['status'], 'available'>,
  reason: CapabilityProbeReason,
): Capability => Object.freeze({ name, status, reason });

const fromInvocation = (
  name: CapabilityName,
  invocation: ProviderInvocationResult<ProbeEvidence>,
): Capability => {
  if (invocation.status === 'completed') {
    return invocation.value === 'positive'
      ? Object.freeze({ name, status: 'available' })
      : unavailable(name, 'unknown', 'probe_returned_no_evidence');
  }
  if (invocation.status === 'unavailable') {
    return unavailable(name, 'unavailable', 'provider_command_unavailable');
  }
  if (invocation.status === 'timedOut') {
    return unavailable(name, 'timedOut', 'provider_timed_out');
  }
  if (invocation.status === 'notReady') {
    return unavailable(name, 'unknown', 'provider_not_ready');
  }
  if (invocation.status === 'cancelled') {
    return unavailable(name, 'unknown', 'probe_cancelled');
  }
  return unavailable(name, 'unknown', 'probe_failed');
};

const mapBounded = async <T, R>(
  values: readonly T[],
  limit: number,
  operation: (value: T) => Promise<R>,
): Promise<readonly R[]> => {
  const results = new Array<R>(values.length);
  let next = 0;
  const worker = async (): Promise<void> => {
    while (next < values.length) {
      const index = next;
      next += 1;
      const value = values[index];
      if (value !== undefined) results[index] = await operation(value);
    }
  };
  await Promise.all(Array.from({ length: Math.min(limit, values.length) }, worker));
  return Object.freeze(results);
};

export class CapabilitiesProviderBridge {
  readonly #host: CapabilitiesProviderHost;
  readonly #pathAccess: WorkspacePathAccess;
  readonly #probeTimeoutMs: number;
  readonly #runtime: ProviderRuntime;

  constructor(
    host: CapabilitiesProviderHost,
    pathAccess: WorkspacePathAccess = systemWorkspacePathAccess,
    probeTimeoutMs = PROVIDER_DEFAULT_TIMEOUT_MS,
  ) {
    this.#host = host;
    this.#pathAccess = pathAccess;
    this.#probeTimeoutMs = probeTimeoutMs;
    this.#runtime = new ProviderRuntime({
      host,
      pathAccess,
      defaultTimeoutMs: probeTimeoutMs,
    });
  }

  async #probe(
    context: WorkspacePathContext,
    params: CapabilitiesBridgeParams,
    name: CapabilityName,
    document: TextDocument | undefined,
    signal: AbortSignal,
  ): Promise<Capability> {
    if (name === 'commands' || name === 'tasks') {
      return Object.freeze({ name, status: 'available' });
    }
    if (name === 'diagnostics') {
      if (document === undefined) return unavailable(name, 'unknown', 'document_required');
      try {
        const diagnostics = this.#host.getDiagnostics(document.uri);
        return Array.isArray(diagnostics) && diagnostics.length > 0
          ? Object.freeze({ name, status: 'available' })
          : unavailable(name, 'unknown', 'probe_returned_no_evidence');
      } catch {
        return unavailable(name, 'unknown', 'probe_failed');
      }
    }
    const selected = providerAdapter(this.#host, name);
    if (selected === undefined) return unavailable(name, 'unknown', 'probe_failed');
    if (selected.requiresDocument && params.file === undefined) {
      return unavailable(name, 'unknown', 'document_required');
    }
    const invocation = await this.#runtime.invoke(context, selected, null, {
      ...(params.file === undefined ? {} : { logicalFile: params.file }),
      signal,
      timeoutMs: this.#probeTimeoutMs,
    });
    return fromInvocation(name, invocation);
  }

  handle: CapabilitiesBridgeHandler = async (context, request, signal) => {
    if (request.method !== CAPABILITIES_BRIDGE_METHOD) return undefined;
    const params = parseParams(request.params);
    if (params === undefined) return { status: 'failed' };
    let document: TextDocument | undefined;
    if (params.file !== undefined) {
      try {
        const resolved = await resolveLogicalPath(context, params.file, this.#pathAccess);
        document = await this.#host.openTextDocument(resolved.lexicalAbsolutePath);
      } catch {
        return { status: 'failed' };
      }
    }
    const candidates = await mapBounded(params.capabilities, 4, (name) =>
      this.#probe(context, params, name, document, signal));
    return {
      status: 'completed',
      candidates,
    } as unknown as JsonValue;
  };
}

export const createCapabilitiesBridgeHandler = (
  host: CapabilitiesProviderHost,
  pathAccess: WorkspacePathAccess = systemWorkspacePathAccess,
  probeTimeoutMs?: number,
): CapabilitiesBridgeHandler =>
  new CapabilitiesProviderBridge(host, pathAccess, probeTimeoutMs).handle;
