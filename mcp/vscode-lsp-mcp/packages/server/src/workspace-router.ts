import {
  BridgeTransportError,
  CAPABILITIES_BRIDGE_METHOD,
  CAPABILITY_NAMES,
  HIERARCHY_BRIDGE_METHODS,
  IPC_HEALTH_TIMEOUT_MS,
  RegistrationStore,
  buildCandidateCollection,
  compareTextOrdinal,
  decideRegistrationCleanup,
  ensureRuntimeDirectory,
  matchesLogicalGlobs,
  applyResultWindow,
  normalizeToolInput,
  parseDiagnosticsBridgeResponse,
  parseCapabilitiesBridgeResponse,
  parseHierarchyExpandBridgeResponse,
  parseHierarchyPrepareBridgeResponse,
  parseHierarchyReleaseBridgeResponse,
  parseDocumentSymbolBridgeResponse,
  parseReferencesBridgeResponse,
  parseVerifySymbolCandidatesBridgeResponse,
  parseSymbolInfoBridgeResponse,
  parseWorkspaceSymbolBridgeResponse,
  registrationComparison,
  registrationLeaseState,
  systemRuntimePrimitives,
  SYMBOL_BRIDGE_METHODS,
  DIAGNOSTICS_BRIDGE_METHOD,
  REFERENCES_BRIDGE_METHOD,
  VERIFY_SYMBOL_CANDIDATES_BRIDGE_METHOD,
  SYMBOL_INFO_BRIDGE_METHOD,
  type Diagnostic,
  type Capability,
  type CallHierarchyEntry,
  type DiagnosticSeverity,
  type DocumentSymbol,
  type HealthResult,
  type HierarchyBridgeDirection,
  type HierarchyBridgeKind,
  type HierarchySymbol,
  type JsonObject,
  type ProviderObservation,
  type RegistrationRecord,
  type ReferenceHit,
  type SymbolCandidateVerification,
  type RuntimePlatform,
  type RuntimePrimitives,
  type ToolResponseMap,
  type SymbolHit,
  type SymbolInfoBridgeCandidate,
  type SymbolInfoResult,
  type TypeHierarchyEntry,
  type UsableRegistrationRecord,
  type WindowsRuntimeSecurityBoundary,
  type Workspace,
  type WorkspaceRouteIdentity,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  ensureSecureRuntimeDirectory,
  verifySecureRegistryFile,
} from '@simplechat/vscode-lsp-mcp-win32-security';
import { connectRegisteredBridgeOnce } from './bridge-client.js';

export interface BridgeProbeSession {
  call(
    method: string,
    params: JsonObject,
    options?: {
      readonly deadlineAt?: number;
      readonly maximumTimeoutMs?: number;
      readonly signal?: AbortSignal;
    },
  ): Promise<unknown>;
  close(): Promise<void>;
}

export interface ConnectedWorkspaceRoute {
  readonly workspace: WorkspaceRouteIdentity;
  readonly session: BridgeProbeSession;
}

type SemanticToolName =
  | 'get_capabilities'
  | 'get_call_hierarchy'
  | 'get_type_hierarchy'
  | 'workspace_symbols'
  | 'document_symbols'
  | 'symbol_info'
  | 'get_references'
  | 'verify_symbol_candidates'
  | 'get_diagnostics';
type SemanticToolFailure = Extract<ToolResponseMap[SemanticToolName], { readonly ok: false }>;

const semanticFailure = (
  error: SemanticToolFailure['error'],
): SemanticToolFailure => Object.freeze({
  ok: false,
  error: Object.freeze(error),
});

const providerStatusFailure = (
  status: 'unavailable' | 'notReady' | 'cancelled' | 'timedOut' | 'failed' | 'positionOutOfRange',
  provider?: ProviderObservation,
): SemanticToolFailure => {
  if (status === 'timedOut') {
    return semanticFailure({
      code: 'PROVIDER_TIMEOUT',
      message: 'The semantic provider timed out.',
      retryable: true,
      ...(provider === undefined ? {} : { provider }),
    });
  }
  if (status === 'positionOutOfRange') {
    return semanticFailure({
      code: 'POSITION_OUT_OF_RANGE',
      message: 'The requested symbol position is outside the document.',
      retryable: false,
      ...(provider === undefined ? {} : { provider }),
    });
  }
  return semanticFailure({
      code: 'PROVIDER_UNAVAILABLE',
      message: status === 'unavailable'
        ? 'The requested semantic provider is unavailable.'
        : 'The requested semantic provider could not produce a result.',
      retryable: false,
      ...(provider === undefined ? {} : { provider }),
    });
};

const routeFailure = (error: unknown): SemanticToolFailure => {
  if (error instanceof WorkspaceRoutingError) {
    return error.reason === 'notFound'
      ? semanticFailure({ code: 'WORKSPACE_NOT_FOUND', message: 'The requested workspace route was not found.', retryable: true })
      : semanticFailure({ code: 'WORKSPACE_DISCONNECTED', message: 'The requested workspace is disconnected.', retryable: true });
  }
  if (error instanceof BridgeTransportError) {
    if (error.reason === 'remote') {
      return error.remoteCode === 'BRIDGE_RESPONSE_TOO_LARGE'
        ? semanticFailure({
            code: 'INTERNAL_ERROR',
            message: 'The semantic provider result exceeded the bridge safety limit.',
            retryable: true,
          })
        : semanticFailure({
            code: 'INTERNAL_ERROR',
            message: 'The semantic bridge rejected the request.',
            retryable: true,
          });
    }
    return error.reason === 'timeout'
      ? semanticFailure({ code: 'PROVIDER_TIMEOUT', message: 'The semantic provider timed out.', retryable: true })
      : semanticFailure({ code: 'WORKSPACE_DISCONNECTED', message: 'The requested workspace is disconnected.', retryable: true });
  }
  return semanticFailure({ code: 'INTERNAL_ERROR', message: 'The semantic request could not be completed.', retryable: true });
};

const shouldDiscardSemanticSession = (error: unknown): boolean =>
  error instanceof BridgeTransportError &&
  (error.reason === 'authentication' ||
    error.reason === 'disconnected' ||
    error.reason === 'protocol');

const capabilityOrder = new Map(CAPABILITY_NAMES.map((name, index) => [name, index] as const));

const compareCapabilities = (left: Capability, right: Capability): number =>
  (capabilityOrder.get(left.name) ?? Number.MAX_SAFE_INTEGER) -
  (capabilityOrder.get(right.name) ?? Number.MAX_SAFE_INTEGER);

const SEMANTIC_BRIDGE_TIMEOUT_MS = 305_000;
const HIERARCHY_TOTAL_TIMEOUT_MS = 90_000;
const HIERARCHY_MAX_ENTRIES = 5_000;

type HierarchyEntry = CallHierarchyEntry | TypeHierarchyEntry;

interface HierarchyFrontierNode {
  readonly nodeId: string;
  readonly symbol: HierarchySymbol;
  readonly depth: number;
}

interface NormalizedHierarchyInput {
  readonly workspaceId: string;
  readonly file: string;
  readonly line: number;
  readonly column: number;
  readonly direction: string;
  readonly maxDepth: number;
  readonly resultStart?: number;
  readonly resultEnd?: number;
}

type HierarchyTraversalResult =
  | SemanticToolFailure
  | {
      readonly ok: true;
      readonly data: {
        readonly results: readonly HierarchyEntry[];
        readonly available: number;
        readonly warnings?: readonly string[];
      };
    };

class HierarchyBoundError extends Error {
  constructor() {
    super('Hierarchy traversal exceeded its safety bound.');
    this.name = 'HierarchyBoundError';
  }
}

const hierarchySymbolKey = (symbol: HierarchySymbol): string => JSON.stringify([
  symbol.file,
  symbol.line,
  symbol.column,
  symbol.name,
  symbol.kind,
]);

const hierarchyRelationRank = Object.freeze({
  root: 0,
  incoming: 1,
  supertype: 1,
  outgoing: 2,
  subtype: 2,
} satisfies Readonly<Record<HierarchyEntry['relation'], number>>);

const compareHierarchySymbols = (left: HierarchySymbol, right: HierarchySymbol): number =>
  compareTextOrdinal(left.file, right.file) ||
  left.line - right.line ||
  left.column - right.column ||
  compareTextOrdinal(left.name, right.name) ||
  compareTextOrdinal(left.kind, right.kind);

const compareHierarchyEntries = (left: HierarchyEntry, right: HierarchyEntry): number =>
  left.depth - right.depth ||
  hierarchyRelationRank[left.relation] - hierarchyRelationRank[right.relation] ||
  compareHierarchySymbols(left.symbol, right.symbol) ||
  (left.parent === undefined
    ? right.parent === undefined ? 0 : -1
    : right.parent === undefined ? 1 : compareHierarchySymbols(left.parent, right.parent)) ||
  compareTextOrdinal(JSON.stringify('callSites' in left ? left.callSites ?? [] : []),
    JSON.stringify('callSites' in right ? right.callSites ?? [] : []));

const hierarchyEntryKey = (entry: HierarchyEntry): string => JSON.stringify([
  entry.relation,
  hierarchySymbolKey(entry.symbol),
  entry.parent === undefined ? null : hierarchySymbolKey(entry.parent),
  'callSites' in entry ? entry.callSites ?? null : null,
]);

const hierarchyDirections = (
  kind: HierarchyBridgeKind,
  direction: string,
): readonly HierarchyBridgeDirection[] => {
  if (kind === 'call') {
    return direction === 'both'
      ? ['incoming', 'outgoing']
      : [direction as HierarchyBridgeDirection];
  }
  return direction === 'both'
    ? ['supertype', 'subtype']
    : [direction === 'supertypes' ? 'supertype' : 'subtype'];
};

const publicRelation = (
  direction: HierarchyBridgeDirection,
): Exclude<HierarchyEntry['relation'], 'root'> => direction === 'incoming'
  ? 'incoming'
  : direction === 'outgoing'
    ? 'outgoing'
    : direction === 'supertype'
      ? 'supertype'
      : 'subtype';

const isSubsequence = (query: string, value: string): boolean => {
  let queryIndex = 0;
  for (const character of value) {
    if (character === query[queryIndex]) queryIndex += 1;
    if (queryIndex === query.length) return true;
  }
  return query.length === 0;
};

const workspaceMatchQuality = (name: string, query: string): number => {
  if (name === query) return 0;
  const lowerName = name.toLowerCase();
  const lowerQuery = query.toLowerCase();
  if (lowerName === lowerQuery) return 1;
  if (name.startsWith(query)) return 2;
  if (lowerName.startsWith(lowerQuery)) return 3;
  if (name.includes(query)) return 4;
  if (lowerName.includes(lowerQuery)) return 5;
  return isSubsequence(lowerQuery, lowerName) ? 6 : 7;
};

const compareWorkspaceSymbols = (
  query: string,
  left: SymbolHit,
  right: SymbolHit,
): number => workspaceMatchQuality(left.name, query) - workspaceMatchQuality(right.name, query) ||
  compareTextOrdinal(left.name, right.name) ||
  compareTextOrdinal(left.file, right.file) ||
  left.line - right.line ||
  left.column - right.column;

const symbolInfoGroupRank = Object.freeze({
  hover: 0,
  declaration: 1,
  definition: 2,
  typeDefinition: 3,
  implementation: 4,
  signatureHelp: 5,
} satisfies Readonly<Record<SymbolInfoBridgeCandidate['type'], number>>);

const compareSymbolInfo = (
  left: SymbolInfoBridgeCandidate,
  right: SymbolInfoBridgeCandidate,
): number => {
  const group = symbolInfoGroupRank[left.type] - symbolInfoGroupRank[right.type];
  if (group !== 0) return group;
  if (left.type === 'hover' && right.type === 'hover') {
    return compareTextOrdinal(left.text, right.text);
  }
  if (left.type !== 'hover' && left.type !== 'signatureHelp' &&
      right.type !== 'hover' && right.type !== 'signatureHelp') {
    return compareTextOrdinal(left.file, right.file) ||
      left.line - right.line ||
      left.column - right.column ||
      compareTextOrdinal(left.snippet ?? '', right.snippet ?? '');
  }
  if (left.type === 'signatureHelp' && right.type === 'signatureHelp') {
    return Number(right.activeSignature) - Number(left.activeSignature) ||
      compareTextOrdinal(left.label, right.label) ||
      compareTextOrdinal(left.documentation ?? '', right.documentation ?? '');
  }
  return 0;
};

const symbolInfoDedupeKey = (candidate: SymbolInfoBridgeCandidate): string => {
  if (candidate.type === 'hover') return JSON.stringify([candidate.type, candidate.text]);
  if (candidate.type !== 'signatureHelp') {
    return JSON.stringify([
      candidate.type,
      candidate.file,
      candidate.line,
      candidate.column,
      candidate.snippet ?? null,
    ]);
  }
  return JSON.stringify([
    candidate.type,
    candidate.label,
    candidate.activeParameter ?? null,
    candidate.documentation ?? null,
    candidate.parameters ?? null,
  ]);
};

const publicSymbolInfo = (candidate: SymbolInfoBridgeCandidate): SymbolInfoResult => {
  if (candidate.type !== 'signatureHelp') return candidate;
  return Object.freeze({
    type: candidate.type,
    label: candidate.label,
    ...(candidate.activeParameter === undefined ? {} : { activeParameter: candidate.activeParameter }),
    ...(candidate.documentation === undefined ? {} : { documentation: candidate.documentation }),
    ...(candidate.parameters === undefined ? {} : { parameters: candidate.parameters }),
  });
};

const compareReferences = (left: ReferenceHit, right: ReferenceHit): number =>
  compareTextOrdinal(left.file, right.file) ||
  left.line - right.line ||
  left.column - right.column ||
  compareTextOrdinal(left.snippet ?? '', right.snippet ?? '');

const diagnosticSeverityRank = Object.freeze({
  error: 0,
  warning: 1,
  information: 2,
  hint: 3,
} satisfies Readonly<Record<DiagnosticSeverity, number>>);

const compareDiagnostics = (left: Diagnostic, right: Diagnostic): number =>
  compareTextOrdinal(left.file, right.file) ||
  left.range.startLine - right.range.startLine ||
  left.range.startColumn - right.range.startColumn ||
  left.range.endLine - right.range.endLine ||
  left.range.endColumn - right.range.endColumn ||
  diagnosticSeverityRank[left.severity] - diagnosticSeverityRank[right.severity] ||
  compareTextOrdinal(left.message, right.message) ||
  compareTextOrdinal(String(left.code ?? ''), String(right.code ?? '')) ||
  compareTextOrdinal(left.source ?? '', right.source ?? '');

const normalizeDiagnostic = (
  candidate: Diagnostic,
  includeRelatedInformation: boolean,
): Diagnostic => includeRelatedInformation || candidate.relatedInformation === undefined
  ? candidate
  : Object.freeze({
      file: candidate.file,
      range: candidate.range,
      severity: candidate.severity,
      message: candidate.message,
      ...(candidate.code === undefined ? {} : { code: candidate.code }),
      ...(candidate.source === undefined ? {} : { source: candidate.source }),
      ...(candidate.tags === undefined ? {} : { tags: candidate.tags }),
    });

export interface WorkspaceRouterOptions {
  readonly connect?: (
    record: UsableRegistrationRecord,
    signal?: AbortSignal,
  ) => Promise<BridgeProbeSession>;
  readonly isPidDefinitelyDead?: (pid: number) => Promise<boolean>;
  readonly now?: () => number;
  readonly primitives: RuntimePrimitives;
  readonly registry: RegistrationStore;
}

interface ProbeResult {
  readonly issue?: string;
  readonly status: HealthResult['status'];
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);

const defaultPidProbe = async (pid: number): Promise<boolean> => {
  try {
    process.kill(pid, 0);
    return false;
  } catch (error) {
    const code = error !== null && typeof error === 'object' && 'code' in error
      ? (error as { readonly code?: unknown }).code
      : undefined;
    return code === 'ESRCH';
  }
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
      if (value !== undefined) {
        results[index] = await operation(value);
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(limit, values.length) }, worker));
  return Object.freeze(results);
};

export class WorkspaceRoutingError extends Error {
  readonly reason: 'disconnected' | 'notFound' | 'timedOut';

  constructor(reason: WorkspaceRoutingError['reason'], message: string) {
    super(message);
    this.name = 'WorkspaceRoutingError';
    this.reason = reason;
  }
}

export class WorkspaceRouter {
  readonly #options: WorkspaceRouterOptions;
  readonly #connect: NonNullable<WorkspaceRouterOptions['connect']>;
  readonly #mutationSessions = new Map<string, Promise<ConnectedWorkspaceRoute>>();
  readonly #semanticSessions = new Map<string, Promise<BridgeProbeSession>>();

  constructor(options: WorkspaceRouterOptions) {
    this.#options = options;
    this.#connect = options.connect ?? ((record, signal) =>
      connectRegisteredBridgeOnce({ record, primitives: options.primitives, ...(signal === undefined ? {} : { signal }) }));
  }

  #now(): number {
    const now = (this.#options.now ?? Date.now)();
    if (!Number.isSafeInteger(now) || now < 1) {
      throw new RangeError('Workspace router clock returned an invalid timestamp.');
    }
    return now;
  }

  async #probe(record: UsableRegistrationRecord, file?: string): Promise<ProbeResult> {
    let session: BridgeProbeSession | undefined;
    const semanticPending = this.#semanticSessions.get(record.workspaceId);
    const mutationPending = semanticPending === undefined
      ? this.#mutationSessions.get(record.workspaceId)
      : undefined;
    const pooled = semanticPending !== undefined
      ? 'semantic'
      : mutationPending !== undefined ? 'mutation' : undefined;
    let failed = false;
    try {
      if (semanticPending !== undefined) {
        session = await semanticPending;
      } else if (mutationPending !== undefined) {
        const route = await mutationPending;
        session = route.session;
        if (route.workspace.generation !== record.workspaceGeneration) {
          throw new WorkspaceRoutingError('notFound', 'Workspace route generation changed.');
        }
      } else {
        session = await this.#connect(record);
      }
      const response = await session.call(
        'bridge.health',
        file === undefined ? {} : { file },
        { deadlineAt: Date.now() + IPC_HEALTH_TIMEOUT_MS },
      );
      if (!isRecord(response) || (response.status !== 'healthy' && response.status !== 'unavailable')) {
        return { status: 'degraded', issue: 'bridge_response_invalid' };
      }
      if (response.status === 'unavailable') {
        return {
          status: 'unavailable',
          issue: typeof response.issue === 'string' ? response.issue : 'document_unavailable',
        };
      }
      return registrationLeaseState(record, this.#now()) === 'fresh'
        ? { status: 'healthy' }
        : { status: 'degraded', issue: 'heartbeat_stale' };
    } catch (error) {
      failed = true;
      return error instanceof BridgeTransportError && error.reason === 'timeout'
        ? { status: 'timedOut', issue: 'bridge_timeout' }
        : { status: 'unavailable', issue: 'bridge_disconnected' };
    } finally {
      if (pooled === undefined) {
        await session?.close().catch(() => undefined);
      } else if (failed) {
        if (pooled === 'semantic' && this.#semanticSessions.get(record.workspaceId) === semanticPending) {
          this.#semanticSessions.delete(record.workspaceId);
        }
        if (pooled === 'mutation' && this.#mutationSessions.get(record.workspaceId) === mutationPending) {
          this.#mutationSessions.delete(record.workspaceId);
        }
        await session?.close().catch(() => undefined);
      }
    }
  }

  async #cleanupIfDead(record: UsableRegistrationRecord, probe: ProbeResult): Promise<void> {
    if (probe.status === 'healthy' || probe.status === 'degraded') {
      return;
    }
    const pidDefinitelyDead = await (this.#options.isPidDefinitelyDead ?? defaultPidProbe)(
      record.extensionHostPid,
    );
    const decision = decideRegistrationCleanup(record, this.#now(), {
      helloSucceeded: false,
      pidDefinitelyDead,
    });
    if (decision !== 'delete') {
      return;
    }
    await this.#options.registry.comparisonAndDelete(registrationComparison(record));
  }

  async #inspect(
    records: readonly RegistrationRecord[],
    file?: string,
  ): Promise<ReadonlyMap<RegistrationRecord, ProbeResult>> {
    const usable = records.filter((record): record is UsableRegistrationRecord => record.kind === 'usable');
    const probes = await mapBounded(usable, 4, (record) => this.#probe(record, file));
    const result = new Map<RegistrationRecord, ProbeResult>();
    for (const [index, record] of usable.entries()) {
      const probe = probes[index];
      if (probe !== undefined) {
        result.set(record, probe);
        await this.#cleanupIfDead(record, probe);
      }
    }
    for (const record of records) {
      if (record.kind === 'unavailable') {
        result.set(record, { status: 'unavailable', issue: record.reasonCode });
        const pidDefinitelyDead = await (this.#options.isPidDefinitelyDead ?? defaultPidProbe)(
          record.extensionHostPid,
        );
        if (decideRegistrationCleanup(record, this.#now(), {
          helloSucceeded: false,
          pidDefinitelyDead,
        }) === 'delete') {
          await this.#options.registry.comparisonAndDelete(registrationComparison(record));
        }
      }
    }
    return result;
  }

  async listWorkspaces(inputValue: unknown): Promise<ToolResponseMap['list_workspaces']> {
    const input = normalizeToolInput('list_workspaces', inputValue);
    const records = await this.#options.registry.scan();
    const probes = await this.#inspect(records);
    const results = records
      .filter((record): record is UsableRegistrationRecord =>
        record.kind === 'usable' &&
        registrationLeaseState(record, this.#now()) === 'fresh' &&
        probes.get(record)?.status === 'healthy')
      .map((record): Workspace => Object.freeze({
        workspaceId: record.workspaceId,
        name: record.workspaceName,
        roots: Object.freeze(record.roots.map((root) => root.alias)),
      }))
      .sort((left, right) => left.workspaceId < right.workspaceId ? -1 : left.workspaceId > right.workspaceId ? 1 : 0);
    return Object.freeze({ ok: true, data: applyResultWindow(results, input) });
  }

  async healthCheck(inputValue: unknown): Promise<ToolResponseMap['health_check']> {
    const input = normalizeToolInput('health_check', inputValue);
    const records = await this.#options.registry.scan();
    const selected = input.workspaceId === undefined
      ? records
      : records.filter((record) => record.workspaceId === input.workspaceId);
    const probes = await this.#inspect(selected, input.file);
    const results: HealthResult[] = [{ target: 'server', status: 'healthy' }];
    for (const record of [...selected].sort((left, right) =>
      left.workspaceId < right.workspaceId ? -1 : left.workspaceId > right.workspaceId ? 1 : 0)) {
      const probe = probes.get(record) ?? { status: 'unavailable', issue: 'bridge_unchecked' };
      results.push(Object.freeze({
        target: `workspace:${record.workspaceId}`,
        status: probe.status,
        ...(probe.issue === undefined ? {} : { issues: Object.freeze([probe.issue]) }),
      }));
    }
    if (input.workspaceId !== undefined && selected.length === 0) {
      results.push(Object.freeze({
        target: `workspace:${input.workspaceId}`,
        status: 'unavailable',
        issues: Object.freeze(['workspace_not_found']),
      }));
    }
    return Object.freeze({ ok: true, data: applyResultWindow(results, input) });
  }

  async getCapabilities(
    inputValue: unknown,
    signal?: AbortSignal,
  ): Promise<ToolResponseMap['get_capabilities']> {
    const input = normalizeToolInput('get_capabilities', inputValue);
    const requested = input.capabilities ?? CAPABILITY_NAMES;
    let raw: unknown;
    try {
      raw = await this.#callSemanticBridge(input.workspaceId, CAPABILITIES_BRIDGE_METHOD, {
        ...(input.file === undefined ? {} : { file: input.file }),
        capabilities: requested,
      }, Date.now() + SEMANTIC_BRIDGE_TIMEOUT_MS, signal);
    } catch (error) {
      return routeFailure(error);
    }

    let response;
    try {
      response = parseCapabilitiesBridgeResponse(raw);
    } catch {
      return semanticFailure({
        code: 'INTERNAL_ERROR',
        message: 'The capabilities bridge returned an invalid response.',
        retryable: true,
      });
    }
    if (response.status !== 'completed') {
      return semanticFailure({
        code: 'PROVIDER_UNAVAILABLE',
        message: 'The capabilities probe could not be completed.',
        retryable: false,
      });
    }
    const requestedSet = new Set(requested);
    if (response.candidates.length !== requested.length ||
        response.candidates.some((candidate) => !requestedSet.has(candidate.name))) {
      return semanticFailure({
        code: 'INTERNAL_ERROR',
        message: 'The capabilities bridge returned an incomplete response.',
        retryable: true,
      });
    }
    const collection = buildCandidateCollection<Capability, Capability>(response.candidates, {
      normalize: (candidate) => candidate,
      dedupeKey: (candidate) => candidate.name,
      compare: compareCapabilities,
      resultStart: input.resultStart ?? 1,
      resultEnd: input.resultEnd ?? ((input.resultStart ?? 1) + 19),
    });
    return Object.freeze({ ok: true, data: collection });
  }

  async #callSemanticBridge(
    workspaceId: string,
    method: string,
    params: JsonObject,
    deadlineAt: number = Date.now() + SEMANTIC_BRIDGE_TIMEOUT_MS,
    signal?: AbortSignal,
  ): Promise<unknown> {
    let pending = this.#semanticSessions.get(workspaceId);
    if (pending === undefined) {
      pending = this.connectWorkspace(workspaceId);
      this.#semanticSessions.set(workspaceId, pending);
    }
    let session: BridgeProbeSession | undefined;
    try {
      session = await pending;
      return await session.call(method, params, {
        deadlineAt,
        maximumTimeoutMs: SEMANTIC_BRIDGE_TIMEOUT_MS,
        ...(signal === undefined ? {} : { signal }),
      });
    } catch (error) {
      if (session === undefined || shouldDiscardSemanticSession(error)) {
        if (this.#semanticSessions.get(workspaceId) === pending) {
          this.#semanticSessions.delete(workspaceId);
        }
        await session?.close().catch(() => undefined);
      }
      throw error;
    }
  }

  async close(): Promise<void> {
    const pending = [
      ...this.#semanticSessions.values(),
      ...this.#mutationSessions.values(),
    ];
    this.#semanticSessions.clear();
    this.#mutationSessions.clear();
    const settled = await Promise.allSettled(pending);
    await Promise.all(settled.flatMap((result) =>
      result.status === 'fulfilled'
        ? ['session' in result.value
            ? result.value.session.close().catch(() => undefined)
            : result.value.close().catch(() => undefined)]
        : []));
  }

  async #releaseHierarchyTraversal(workspaceId: string, traversalId: string): Promise<void> {
    const pending = this.#semanticSessions.get(workspaceId);
    if (pending === undefined) return;
    let session: BridgeProbeSession | undefined;
    try {
      session = await pending;
      parseHierarchyReleaseBridgeResponse(await session.call(
        HIERARCHY_BRIDGE_METHODS.release,
        { traversalId },
        { deadlineAt: Date.now() + 1_000 },
      ));
    } catch {
      if (this.#semanticSessions.get(workspaceId) === pending) {
        this.#semanticSessions.delete(workspaceId);
      }
      await session?.close().catch(() => undefined);
    }
  }

  async #traverseHierarchy(
    kind: HierarchyBridgeKind,
    input: NormalizedHierarchyInput,
    signal?: AbortSignal,
  ): Promise<HierarchyTraversalResult> {
    const deadlineAt = Date.now() + HIERARCHY_TOTAL_TIMEOUT_MS;
    let traversalId: string | undefined;
    try {
      const prepared = parseHierarchyPrepareBridgeResponse(await this.#callSemanticBridge(
        input.workspaceId,
        HIERARCHY_BRIDGE_METHODS.prepare,
        {
          kind,
          file: input.file,
          line: input.line,
          column: input.column,
        },
        deadlineAt,
        signal,
      ));
      if (prepared.status !== 'completed') return providerStatusFailure(prepared.status);
      traversalId = prepared.traversalId;

      const warnings = new Set(prepared.warnings ?? []);
      const candidates: HierarchyEntry[] = prepared.nodes.map((node) => Object.freeze({
        relation: 'root' as const,
        depth: 0,
        symbol: node.symbol,
      }));
      if (candidates.length > HIERARCHY_MAX_ENTRIES) throw new HierarchyBoundError();

      for (const direction of hierarchyDirections(kind, input.direction)) {
        let frontier: readonly HierarchyFrontierNode[] = Object.freeze(prepared.nodes.map((node) => ({
          nodeId: node.nodeId,
          symbol: node.symbol,
          depth: 0,
        })));
        const expanded = new Set<string>();
        while (frontier.length > 0 && (frontier[0]?.depth ?? input.maxDepth) < input.maxDepth) {
          const parents = frontier.filter((parent) => {
            const key = hierarchySymbolKey(parent.symbol);
            if (expanded.has(key)) return false;
            expanded.add(key);
            return true;
          });
          const expansions = await mapBounded(parents, 4, async (parent) => ({
            parent,
            response: parseHierarchyExpandBridgeResponse(await this.#callSemanticBridge(
              input.workspaceId,
              HIERARCHY_BRIDGE_METHODS.expand,
              {
                traversalId: prepared.traversalId,
                nodeId: parent.nodeId,
                direction,
              },
              deadlineAt,
              signal,
            )),
          }));
          const next: HierarchyFrontierNode[] = [];
          const nextKeys = new Set<string>();
          for (const expansion of expansions) {
            if (expansion.response.status !== 'completed') {
              return providerStatusFailure(expansion.response.status);
            }
            for (const warning of expansion.response.warnings ?? []) warnings.add(warning);
            for (const node of expansion.response.nodes) {
              if (kind === 'type' && node.callSites !== undefined) {
                throw new TypeError('Type hierarchy bridge returned call sites.');
              }
              if (candidates.length >= HIERARCHY_MAX_ENTRIES) throw new HierarchyBoundError();
              const depth = expansion.parent.depth + 1;
              const relation = publicRelation(direction);
              candidates.push(Object.freeze(kind === 'call'
                ? {
                    relation: relation as 'incoming' | 'outgoing',
                    depth,
                    symbol: node.symbol,
                    parent: expansion.parent.symbol,
                    ...(node.callSites === undefined ? {} : { callSites: node.callSites }),
                  }
                : {
                    relation: relation as 'supertype' | 'subtype',
                    depth,
                    symbol: node.symbol,
                    parent: expansion.parent.symbol,
                  }));
              const key = hierarchySymbolKey(node.symbol);
              if (depth < input.maxDepth && !expanded.has(key) && !nextKeys.has(key)) {
                nextKeys.add(key);
                next.push({ nodeId: node.nodeId, symbol: node.symbol, depth });
              }
            }
          }
          frontier = Object.freeze(next);
        }
      }

      const collection = buildCandidateCollection<HierarchyEntry, HierarchyEntry>(candidates, {
        normalize: (candidate) => candidate,
        dedupeKey: hierarchyEntryKey,
        compare: compareHierarchyEntries,
        resultStart: input.resultStart ?? 1,
        resultEnd: input.resultEnd ?? ((input.resultStart ?? 1) + 19),
        ...(warnings.size === 0 ? {} : { warnings: Object.freeze([...warnings]) }),
      });
      return Object.freeze({ ok: true, data: collection });
    } catch (error) {
      return error instanceof HierarchyBoundError
        ? semanticFailure({
            code: 'PROVIDER_UNAVAILABLE',
            message: 'The hierarchy exceeds the bounded traversal limit.',
            retryable: false,
          })
        : routeFailure(error);
    } finally {
      if (traversalId !== undefined) {
        await this.#releaseHierarchyTraversal(input.workspaceId, traversalId);
      }
    }
  }

  async getCallHierarchy(
    inputValue: unknown,
    signal?: AbortSignal,
  ): Promise<ToolResponseMap['get_call_hierarchy']> {
    const input = normalizeToolInput('get_call_hierarchy', inputValue);
    const result = await this.#traverseHierarchy('call', {
      ...input,
      direction: input.direction ?? 'both',
      maxDepth: input.maxDepth ?? 1,
    }, signal);
    if (!result.ok) return result;
    const results = result.data.results.filter((entry): entry is CallHierarchyEntry =>
      entry.relation === 'root' || entry.relation === 'incoming' || entry.relation === 'outgoing');
    if (results.length !== result.data.results.length) {
      return semanticFailure({
        code: 'INTERNAL_ERROR',
        message: 'The call hierarchy produced an invalid relation.',
        retryable: true,
      });
    }
    return Object.freeze({
      ok: true,
      data: Object.freeze({
        results: Object.freeze(results),
        available: result.data.available,
        ...(result.data.warnings === undefined ? {} : { warnings: result.data.warnings }),
      }),
    });
  }

  async getTypeHierarchy(
    inputValue: unknown,
    signal?: AbortSignal,
  ): Promise<ToolResponseMap['get_type_hierarchy']> {
    const input = normalizeToolInput('get_type_hierarchy', inputValue);
    const result = await this.#traverseHierarchy('type', {
      ...input,
      direction: input.direction ?? 'both',
      maxDepth: input.maxDepth ?? 1,
    }, signal);
    if (!result.ok) return result;
    const results = result.data.results.filter((entry): entry is TypeHierarchyEntry =>
      entry.relation === 'root' || entry.relation === 'supertype' || entry.relation === 'subtype');
    if (results.length !== result.data.results.length) {
      return semanticFailure({
        code: 'INTERNAL_ERROR',
        message: 'The type hierarchy produced an invalid relation.',
        retryable: true,
      });
    }
    return Object.freeze({
      ok: true,
      data: Object.freeze({
        results: Object.freeze(results),
        available: result.data.available,
        ...(result.data.warnings === undefined ? {} : { warnings: result.data.warnings }),
      }),
    });
  }

  async workspaceSymbols(
    inputValue: unknown,
    signal?: AbortSignal,
  ): Promise<ToolResponseMap['workspace_symbols']> {
    const input = normalizeToolInput('workspace_symbols', inputValue);
    let raw: unknown;
    try {
      raw = await this.#callSemanticBridge(input.workspaceId, SYMBOL_BRIDGE_METHODS.workspace, {
        query: input.query,
        contextLines: input.contextLines ?? 0,
      }, Date.now() + SEMANTIC_BRIDGE_TIMEOUT_MS, signal);
    } catch (error) {
      return routeFailure(error);
    }

    let response;
    try {
      response = parseWorkspaceSymbolBridgeResponse(raw);
    } catch {
      return semanticFailure({
        code: 'INTERNAL_ERROR',
        message: 'The workspace symbol bridge returned an invalid response.',
        retryable: true,
      });
    }
    if (response.status !== 'completed') {
      return providerStatusFailure(response.status, response.provider);
    }

    const kinds = input.kinds === undefined ? undefined : new Set(input.kinds);
    const collection = buildCandidateCollection<SymbolHit, SymbolHit>(response.candidates, {
      normalize: (candidate) => candidate,
      filter: (candidate) => kinds === undefined || kinds.has(candidate.kind),
      logicalPath: (candidate) => candidate.file,
      ...(input.includeGlobs === undefined ? {} : { includeGlobs: input.includeGlobs }),
      ...(input.excludeGlobs === undefined ? {} : { excludeGlobs: input.excludeGlobs }),
      dedupeKey: (candidate) => JSON.stringify([
        candidate.name,
        candidate.kind,
        candidate.file,
        candidate.line,
        candidate.column,
        candidate.container ?? null,
      ]),
      compare: (left, right) => compareWorkspaceSymbols(input.query, left, right),
      resultStart: input.resultStart ?? 1,
      resultEnd: input.resultEnd ?? ((input.resultStart ?? 1) + 19),
      ...(response.warnings === undefined ? {} : { warnings: response.warnings }),
    });
    return Object.freeze({
      ok: true,
      data: Object.freeze({
        ...collection,
        ...(response.provider === undefined ? {} : { provider: response.provider }),
      }),
    });
  }

  async symbolInfo(
    inputValue: unknown,
    signal?: AbortSignal,
  ): Promise<ToolResponseMap['symbol_info']> {
    const input = normalizeToolInput('symbol_info', inputValue);
    let raw: unknown;
    try {
      raw = await this.#callSemanticBridge(input.workspaceId, SYMBOL_INFO_BRIDGE_METHOD, {
        file: input.file,
        line: input.line,
        column: input.column,
        include: input.include ?? ['definition'],
        contextLines: input.contextLines ?? 0,
      }, Date.now() + SEMANTIC_BRIDGE_TIMEOUT_MS, signal);
    } catch (error) {
      return routeFailure(error);
    }

    let response;
    try {
      response = parseSymbolInfoBridgeResponse(raw);
    } catch {
      return semanticFailure({
        code: 'INTERNAL_ERROR',
        message: 'The symbol info bridge returned an invalid response.',
        retryable: true,
      });
    }
    if (response.status !== 'completed') {
      return providerStatusFailure(response.status);
    }

    const collection = buildCandidateCollection<SymbolInfoBridgeCandidate, SymbolInfoBridgeCandidate>(
      response.candidates,
      {
        normalize: (candidate) => candidate,
        filter: (candidate) =>
          candidate.type === 'hover' ||
          candidate.type === 'signatureHelp' ||
          matchesLogicalGlobs(candidate.file, input),
        dedupeKey: symbolInfoDedupeKey,
        compare: compareSymbolInfo,
        resultStart: input.resultStart ?? 1,
        resultEnd: input.resultEnd ?? ((input.resultStart ?? 1) + 19),
        ...(response.warnings === undefined ? {} : { warnings: response.warnings }),
      },
    );
    return Object.freeze({
      ok: true,
      data: Object.freeze({
        results: Object.freeze(collection.results.map(publicSymbolInfo)),
        available: collection.available,
        ...(collection.warnings === undefined ? {} : { warnings: collection.warnings }),
      }),
    });
  }

  async getReferences(
    inputValue: unknown,
    signal?: AbortSignal,
  ): Promise<ToolResponseMap['get_references']> {
    const input = normalizeToolInput('get_references', inputValue);
    const resultStart = input.resultStart ?? 1;
    const resultEnd = input.resultEnd ?? (resultStart + 19);
    let raw: unknown;
    try {
      raw = await this.#callSemanticBridge(input.workspaceId, REFERENCES_BRIDGE_METHOD, {
        file: input.file,
        line: input.line,
        column: input.column,
        contextLines: input.contextLines ?? 0,
        searchMode: input.searchMode ?? 'auto',
        ...(input.includeGlobs === undefined ? {} : { includeGlobs: input.includeGlobs }),
        ...(input.excludeGlobs === undefined ? {} : { excludeGlobs: input.excludeGlobs }),
        ...(input.scopePaths === undefined ? {} : { scopePaths: input.scopePaths }),
        ...(input.timeoutMs === undefined ? {} : { timeoutMs: input.timeoutMs }),
        resultStart,
        resultEnd,
      }, Date.now() + SEMANTIC_BRIDGE_TIMEOUT_MS, signal);
    } catch (error) {
      return routeFailure(error);
    }

    let response;
    try {
      response = parseReferencesBridgeResponse(raw);
    } catch {
      return semanticFailure({
        code: 'INTERNAL_ERROR',
        message: 'The references bridge returned an invalid response.',
        retryable: true,
      });
    }
    if (response.status === 'scopedIncomplete') {
      const targetSlash = input.file.lastIndexOf('/');
      const suggestedScope = targetSlash < 0 ? input.file : input.file.slice(0, targetSlash);
      if (response.reason === 'scopeInvalid') {
        return semanticFailure({
          code: 'INVALID_ARGUMENT',
          message: 'A reference scope path does not identify a valid logical workspace file or directory.',
          retryable: false,
          action: 'Use list_workspaces logical root aliases and normalized scopePaths without globs or absolute paths.',
        });
      }
      return semanticFailure({
        code: 'PROVIDER_UNAVAILABLE',
        message: `The fast C/C++ reference search could not prove a complete result (${response.reason}).`,
        retryable: false,
        action: response.reason === 'scopeBudgetExceeded'
          ? `Retry with scopePaths such as ${JSON.stringify([suggestedScope])}, add only directly relevant source directories, or choose searchMode provider with an explicit long timeout.`
          : response.reason === 'scopeUnsupported'
            ? 'Use searchMode provider for this language; fast scoped identity search currently supports C and C++.'
            : response.reason === 'targetUnresolved'
              ? 'Confirm the exact symbol position with symbol_info, then retry; use searchMode provider only when the Provider can resolve references but not definition identity.'
              : `Retry with scopePaths such as ${JSON.stringify([suggestedScope])}, raise timeoutMs for the same scoped search, or choose searchMode provider for full Provider enumeration.`,
      });
    }
    if (response.status !== 'completed') return providerStatusFailure(response.status);
    if (response.available !== undefined) {
      return Object.freeze({
        ok: true,
        data: Object.freeze({
          results: Object.freeze([...response.candidates]),
          available: response.available,
          ...(response.warnings === undefined ? {} : { warnings: response.warnings }),
        }),
      });
    }

    const collection = buildCandidateCollection<ReferenceHit, ReferenceHit>(response.candidates, {
      normalize: (candidate) => candidate,
      logicalPath: (candidate) => candidate.file,
      ...(input.includeGlobs === undefined ? {} : { includeGlobs: input.includeGlobs }),
      ...(input.excludeGlobs === undefined ? {} : { excludeGlobs: input.excludeGlobs }),
      dedupeKey: (candidate) => JSON.stringify([
        candidate.file,
        candidate.line,
        candidate.column,
        candidate.snippet ?? null,
      ]),
      compare: compareReferences,
      resultStart,
      resultEnd,
      ...(response.warnings === undefined ? {} : { warnings: response.warnings }),
    });
    return Object.freeze({ ok: true, data: collection });
  }

  async verifySymbolCandidates(
    inputValue: unknown,
    signal?: AbortSignal,
  ): Promise<ToolResponseMap['verify_symbol_candidates']> {
    const input = normalizeToolInput('verify_symbol_candidates', inputValue);
    let raw: unknown;
    try {
      raw = await this.#callSemanticBridge(
        input.workspaceId,
        VERIFY_SYMBOL_CANDIDATES_BRIDGE_METHOD,
        {
          file: input.file,
          line: input.line,
          column: input.column,
          candidates: input.candidates.map((candidate) => ({
            file: candidate.file,
            line: candidate.line,
            column: candidate.column,
          })),
          ...(input.timeoutMs === undefined ? {} : { timeoutMs: input.timeoutMs }),
        },
        Date.now() + (input.timeoutMs === undefined
          ? SEMANTIC_BRIDGE_TIMEOUT_MS
          : input.timeoutMs + 5_000),
        signal,
      );
    } catch (error) {
      return routeFailure(error);
    }

    let response;
    try {
      response = parseVerifySymbolCandidatesBridgeResponse(raw);
    } catch {
      return semanticFailure({
        code: 'INTERNAL_ERROR',
        message: 'The symbol candidate bridge returned an invalid response.',
        retryable: true,
      });
    }
    if (response.status !== 'completed') return providerStatusFailure(response.status);
    const results = Object.freeze([...response.candidates]) as readonly SymbolCandidateVerification[];
    return Object.freeze({
      ok: true,
      data: Object.freeze({ results, available: results.length }),
    });
  }

  async getDiagnostics(
    inputValue: unknown,
    signal?: AbortSignal,
  ): Promise<ToolResponseMap['get_diagnostics']> {
    const input = normalizeToolInput('get_diagnostics', inputValue);
    let raw: unknown;
    try {
      raw = await this.#callSemanticBridge(input.workspaceId, DIAGNOSTICS_BRIDGE_METHOD, {
        scope: input.scope ?? 'modifiedFiles',
        ...(input.files === undefined ? {} : { files: input.files }),
        includeRelatedInformation: input.includeRelatedInformation ?? false,
      }, Date.now() + SEMANTIC_BRIDGE_TIMEOUT_MS, signal);
    } catch (error) {
      return routeFailure(error);
    }

    let response;
    try {
      response = parseDiagnosticsBridgeResponse(raw);
    } catch {
      return semanticFailure({
        code: 'INTERNAL_ERROR',
        message: 'The diagnostics bridge returned an invalid response.',
        retryable: true,
      });
    }
    if (response.status !== 'completed') return providerStatusFailure(response.status);

    const severities = new Set(input.severities ?? ['error', 'warning', 'information', 'hint']);
    const sources = input.sources === undefined ? undefined : new Set(input.sources);
    const includeRelatedInformation = input.includeRelatedInformation ?? false;
    const collection = buildCandidateCollection<Diagnostic, Diagnostic>(response.candidates, {
      normalize: (candidate) => normalizeDiagnostic(candidate, includeRelatedInformation),
      filter: (candidate) => severities.has(candidate.severity) &&
        (sources === undefined || (candidate.source !== undefined && sources.has(candidate.source))),
      dedupeKey: (candidate) => JSON.stringify(candidate),
      compare: compareDiagnostics,
      resultStart: input.resultStart ?? 1,
      resultEnd: input.resultEnd ?? ((input.resultStart ?? 1) + 19),
      ...(response.warnings === undefined ? {} : { warnings: response.warnings }),
    });
    return Object.freeze({ ok: true, data: collection });
  }

  async documentSymbols(
    inputValue: unknown,
    signal?: AbortSignal,
  ): Promise<ToolResponseMap['document_symbols']> {
    const input = normalizeToolInput('document_symbols', inputValue);
    let raw: unknown;
    try {
      raw = await this.#callSemanticBridge(input.workspaceId, SYMBOL_BRIDGE_METHODS.document, {
        file: input.file,
        contextLines: input.contextLines ?? 0,
      }, Date.now() + SEMANTIC_BRIDGE_TIMEOUT_MS, signal);
    } catch (error) {
      return routeFailure(error);
    }

    let response;
    try {
      response = parseDocumentSymbolBridgeResponse(raw);
    } catch {
      return semanticFailure({
        code: 'INTERNAL_ERROR',
        message: 'The document symbol bridge returned an invalid response.',
        retryable: true,
      });
    }
    if (response.status !== 'completed') {
      return providerStatusFailure(response.status, response.provider);
    }

    const kinds = input.kinds === undefined ? undefined : new Set(input.kinds);
    const maxDepth = input.maxDepth;
    const collection = buildCandidateCollection<DocumentSymbol, DocumentSymbol>(response.candidates, {
      normalize: (candidate): DocumentSymbol => candidate,
      filter: (candidate) =>
        (kinds === undefined || kinds.has(candidate.kind)) &&
        (maxDepth === undefined || candidate.path.length - 1 <= maxDepth) &&
        (input.nameEquals === undefined || candidate.path.at(-1) === input.nameEquals) &&
        (input.pathEquals === undefined ||
          (candidate.path.length === input.pathEquals.length &&
            candidate.path.every((part, index) => part === input.pathEquals?.[index]))),
      dedupeKey: (candidate) => JSON.stringify([
        candidate.path,
        candidate.kind,
        candidate.line,
        candidate.column,
        candidate.range ?? null,
      ]),
      resultStart: input.resultStart ?? 1,
      resultEnd: input.resultEnd ?? ((input.resultStart ?? 1) + 19),
      ...(response.warnings === undefined ? {} : { warnings: response.warnings }),
    });
    const rangeUnavailable = input.includeRange === true &&
      collection.results.some((candidate) => candidate.range === undefined);
    const warnings = Object.freeze([
      ...(collection.warnings ?? []),
      ...(rangeUnavailable ? ['provider_range_unavailable'] : []),
    ]);
    return Object.freeze({
      ok: true,
      data: Object.freeze({
        results: Object.freeze(collection.results.map((candidate): DocumentSymbol => Object.freeze({
          kind: candidate.kind,
          path: candidate.path,
          line: candidate.line,
          column: candidate.column,
          ...(input.includeRange === true && candidate.range !== undefined
            ? { range: candidate.range }
            : {}),
          ...(candidate.snippet === undefined ? {} : { snippet: candidate.snippet }),
        }))),
        available: collection.available,
        ...(warnings.length === 0 ? {} : { warnings }),
        ...(response.provider === undefined ? {} : { provider: response.provider }),
      }),
    });
  }

  async #connectWorkspaceRecord(
    workspaceId: string,
    generation: number | undefined,
    signal?: AbortSignal,
  ): Promise<ConnectedWorkspaceRoute> {
    const records = await this.#options.registry.scan();
    const matches = records.filter((record): record is UsableRegistrationRecord =>
      record.kind === 'usable' &&
      record.workspaceId === workspaceId &&
      (generation === undefined || record.workspaceGeneration === generation) &&
      registrationLeaseState(record, this.#now()) === 'fresh');
    if (matches.length !== 1) {
      throw new WorkspaceRoutingError('notFound', 'Workspace route was not found.');
    }
    try {
      const record = matches[0] as UsableRegistrationRecord;
      const session = await this.#connect(record, signal);
      return Object.freeze({
        workspace: Object.freeze({
          workspaceId: record.workspaceId,
          generation: record.workspaceGeneration,
        }),
        session,
      });
    } catch (error) {
      throw new WorkspaceRoutingError(
        error instanceof BridgeTransportError && error.reason === 'timeout' ? 'timedOut' : 'disconnected',
        'Workspace route could not be connected.',
      );
    }
  }

  connectWorkspace(workspaceId: string, signal?: AbortSignal): Promise<BridgeProbeSession> {
    return this.#connectWorkspaceRecord(workspaceId, undefined, signal).then(({ session }) => session);
  }

  connectWorkspaceBinding(
    workspaceId: string,
    signal?: AbortSignal,
  ): Promise<ConnectedWorkspaceRoute> {
    return this.#borrowMutationRoute(workspaceId, undefined, signal);
  }

  connectWorkspaceRoute(
    workspace: WorkspaceRouteIdentity,
    signal?: AbortSignal,
  ): Promise<BridgeProbeSession> {
    return this.#borrowMutationRoute(workspace.workspaceId, workspace.generation, signal)
      .then(({ session }) => session);
  }

  async #borrowMutationRoute(
    workspaceId: string,
    generation: number | undefined,
    signal?: AbortSignal,
  ): Promise<ConnectedWorkspaceRoute> {
    let pending = this.#mutationSessions.get(workspaceId);
    if (pending === undefined) {
      pending = this.#connectWorkspaceRecord(workspaceId, generation, signal);
      this.#mutationSessions.set(workspaceId, pending);
    }
    let route: ConnectedWorkspaceRoute;
    try {
      route = await pending;
    } catch (error) {
      if (this.#mutationSessions.get(workspaceId) === pending) {
        this.#mutationSessions.delete(workspaceId);
      }
      throw error;
    }
    if (generation !== undefined && route.workspace.generation !== generation) {
      if (this.#mutationSessions.get(workspaceId) === pending) {
        this.#mutationSessions.delete(workspaceId);
      }
      await route.session.close().catch(() => undefined);
      throw new WorkspaceRoutingError('notFound', 'Workspace route generation changed.');
    }
    const session: BridgeProbeSession = Object.freeze({
      call: async (
        method: string,
        params: JsonObject,
        options?: Parameters<BridgeProbeSession['call']>[2],
      ) => {
        try {
          return await route.session.call(method, params, options);
        } catch (error) {
          if (this.#mutationSessions.get(workspaceId) === pending) {
            this.#mutationSessions.delete(workspaceId);
          }
          await route.session.close().catch(() => undefined);
          throw error;
        }
      },
      close: () => Promise.resolve(),
    });
    return Object.freeze({ workspace: route.workspace, session });
  }
}

const runtimePlatform = (): RuntimePlatform => {
  if (process.platform === 'win32') {
    return 'win32';
  }
  throw new Error('The MCP server requires Windows.');
};

export const createSystemWorkspaceRouter = async (): Promise<WorkspaceRouter> => {
  const platform = runtimePlatform();
  const windowsSecurity: WindowsRuntimeSecurityBoundary = {
    ensureSecureRuntimeDirectory: () => ensureSecureRuntimeDirectory(),
    verifySecureRegistryFile,
  };
  const layout = await ensureRuntimeDirectory({
    platform,
    environment: process.env,
    windowsSecurity,
  });
  const registry = new RegistrationStore({
    layout,
    primitives: systemRuntimePrimitives,
    windowsSecurity,
  });
  return new WorkspaceRouter({
    registry,
    primitives: systemRuntimePrimitives,
  });
};
