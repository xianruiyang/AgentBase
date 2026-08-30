import type { TextDocument } from 'vscode';
import {
  HIERARCHY_BRIDGE_METHODS,
  SYMBOL_KINDS,
  WorkspaceBoundaryError,
  isHierarchyNodeId,
  isHierarchyTraversalId,
  logicalPathFromProviderLocation,
  systemWorkspacePathAccess,
  type HierarchyBridgeDirection,
  type HierarchyBridgeKind,
  type HierarchyBridgeNode,
  type HierarchySymbol,
  type IpcRequest,
  type JsonValue,
  type Range,
  type SymbolKind,
  type WorkspacePathAccess,
  type WorkspacePathContext,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  ProviderRuntime,
  classifyArrayProviderResult,
  type ProviderCommandAdapter,
  type ProviderInvocationResult,
  type VscodeProviderHost,
} from './provider-runtime.js';

const cppSourceFile = /\.(?:c|cc|cpp|cxx|h|hh|hpp|hxx|inl|ipp)$/i;
const cppIdentifierCharacter = /[A-Za-z0-9_]/;
const CPP_COLD_HIERARCHY_POLL_DELAYS_MS = Object.freeze([
  0,
  250,
  500,
  1_000,
  2_000,
  5_000,
  5_000,
  5_000,
  5_000,
  5_000,
  5_000,
  5_000,
  5_000,
] as const);

export const HIERARCHY_MAX_ACTIVE_TRAVERSALS = 32;
export const HIERARCHY_MAX_NODES_PER_TRAVERSAL = 5_000;
export const HIERARCHY_TRAVERSAL_TTL_MS = 60_000;

interface PrepareParams {
  readonly kind: HierarchyBridgeKind;
  readonly file: string;
  readonly line: number;
  readonly column: number;
}

interface ExpandParams {
  readonly traversalId: string;
  readonly nodeId: string;
  readonly direction: HierarchyBridgeDirection;
}

interface ReleaseParams {
  readonly traversalId: string;
}

interface ProviderPoint {
  readonly line: number;
  readonly character: number;
}

interface ProviderUri {
  readonly scheme: string;
  readonly fsPath: string;
}

interface MappedProviderItem {
  readonly raw: unknown;
  readonly symbol: HierarchySymbol;
  readonly callSites?: readonly Range[];
}

interface TraversalState {
  readonly id: string;
  readonly kind: HierarchyBridgeKind;
  readonly nodes: Map<string, unknown>;
  lastTouchedAt: number;
  nextNode: number;
}

export interface HierarchyProviderHost extends VscodeProviderHost {
  createPosition(line: number, character: number): unknown;
}

export type HierarchyBridgeHandler = (
  context: WorkspacePathContext,
  request: IpcRequest,
  signal: AbortSignal,
) => Promise<JsonValue | undefined>;

const asRecord = (value: unknown): Record<string, unknown> | undefined =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;

const exactFields = (value: Record<string, unknown>, fields: readonly string[]): boolean => {
  const allowed = new Set(fields);
  return Object.keys(value).every((key) => allowed.has(key));
};

const positiveInteger = (value: unknown): number | undefined =>
  Number.isSafeInteger(value) && (value as number) >= 1
    ? value as number
    : undefined;

const parsePrepare = (value: unknown): PrepareParams | undefined => {
  const record = asRecord(value);
  const line = positiveInteger(record?.line);
  const column = positiveInteger(record?.column);
  if (record === undefined ||
      !exactFields(record, ['kind', 'file', 'line', 'column']) ||
      (record.kind !== 'call' && record.kind !== 'type') ||
      typeof record.file !== 'string' || record.file.length === 0 ||
      line === undefined || column === undefined) {
    return undefined;
  }
  return { kind: record.kind, file: record.file, line, column };
};

const directionMatchesKind = (
  kind: HierarchyBridgeKind,
  direction: HierarchyBridgeDirection,
): boolean => kind === 'call'
  ? direction === 'incoming' || direction === 'outgoing'
  : direction === 'supertype' || direction === 'subtype';

const parseExpand = (value: unknown): ExpandParams | undefined => {
  const record = asRecord(value);
  if (record === undefined ||
      !exactFields(record, ['traversalId', 'nodeId', 'direction']) ||
      !isHierarchyTraversalId(record.traversalId) ||
      !isHierarchyNodeId(record.nodeId) ||
      (record.direction !== 'incoming' && record.direction !== 'outgoing' &&
       record.direction !== 'supertype' && record.direction !== 'subtype')) {
    return undefined;
  }
  return {
    traversalId: record.traversalId,
    nodeId: record.nodeId,
    direction: record.direction,
  };
};

const parseRelease = (value: unknown): ReleaseParams | undefined => {
  const record = asRecord(value);
  return record !== undefined && exactFields(record, ['traversalId']) &&
    isHierarchyTraversalId(record.traversalId)
    ? { traversalId: record.traversalId }
    : undefined;
};

const providerPoint = (value: unknown): ProviderPoint | undefined => {
  const record = asRecord(value);
  if (record === undefined ||
      !Number.isSafeInteger(record.line) || (record.line as number) < 0 ||
      (record.line as number) >= Number.MAX_SAFE_INTEGER ||
      !Number.isSafeInteger(record.character) || (record.character as number) < 0 ||
      (record.character as number) >= Number.MAX_SAFE_INTEGER) {
    return undefined;
  }
  return { line: record.line as number, character: record.character as number };
};

const providerRange = (value: unknown): Range | undefined => {
  const record = asRecord(value);
  const start = providerPoint(record?.start);
  const end = providerPoint(record?.end);
  if (start === undefined || end === undefined || end.line < start.line ||
      (end.line === start.line && end.character < start.character)) {
    return undefined;
  }
  return Object.freeze({
    startLine: start.line + 1,
    startColumn: start.character + 1,
    endLine: end.line + 1,
    endColumn: end.character + 1,
  });
};

const providerUri = (value: unknown): ProviderUri | undefined => {
  const record = asRecord(value);
  return record !== undefined && typeof record.scheme === 'string' &&
    typeof record.fsPath === 'string'
    ? { scheme: record.scheme, fsPath: record.fsPath }
    : undefined;
};

const publicKind = (value: unknown): SymbolKind | undefined => {
  if (!Number.isSafeInteger(value)) return undefined;
  return SYMBOL_KINDS[value as number] ?? 'unknown';
};

const providerPosition = (
  host: HierarchyProviderHost,
  input: PrepareParams,
  document: TextDocument,
): unknown => {
  const line = input.line - 1;
  const character = input.column - 1;
  const lines = document.getText().replaceAll('\r\n', '\n').replaceAll('\r', '\n').split('\n');
  if (line >= lines.length || character > (lines[line]?.length ?? -1)) {
    throw new RangeError('Hierarchy position is outside the document.');
  }
  return host.createPosition(line, character);
};

const looksLikeCppCallable = (
  document: TextDocument,
  input: PrepareParams,
): boolean => {
  if (!cppSourceFile.test(input.file)) return false;
  const lines = document.getText().replaceAll('\r\n', '\n').replaceAll('\r', '\n').split('\n');
  const text = lines[input.line - 1];
  if (text === undefined || text.length === 0) return false;
  let cursor = Math.min(input.column - 1, text.length - 1);
  if (!cppIdentifierCharacter.test(text[cursor] ?? '') && cursor > 0 &&
      cppIdentifierCharacter.test(text[cursor - 1] ?? '')) {
    cursor -= 1;
  }
  if (!cppIdentifierCharacter.test(text[cursor] ?? '')) return false;
  let end = cursor + 1;
  while (end < text.length && cppIdentifierCharacter.test(text[end] ?? '')) end += 1;
  while (end < text.length && /\s/.test(text[end] ?? '')) end += 1;
  return text[end] === '(';
};

const prepareAdapter = (
  host: HierarchyProviderHost,
  kind: HierarchyBridgeKind,
): ProviderCommandAdapter<PrepareParams, readonly unknown[]> => {
  let retryTransientEmpty = false;
  return {
    command: kind === 'call' ? 'vscode.prepareCallHierarchy' : 'vscode.prepareTypeHierarchy',
    requiresDocument: true,
    buildArguments: (input, document) => {
      if (document === undefined) throw new RangeError('Document activation invariant failed.');
      retryTransientEmpty = kind === 'call' && looksLikeCppCallable(document, input);
      return [document.uri, providerPosition(host, input, document)];
    },
    classifyResult: (value) => {
      const classified = classifyArrayProviderResult(value);
      return classified.status === 'ready' && retryTransientEmpty && classified.value.length === 0
        ? { status: 'notReady' }
        : classified;
    },
  };
};

const expandAdapter = (
  direction: HierarchyBridgeDirection,
): ProviderCommandAdapter<unknown, readonly unknown[]> => ({
  command: direction === 'incoming'
    ? 'vscode.provideIncomingCalls'
    : direction === 'outgoing'
      ? 'vscode.provideOutgoingCalls'
      : direction === 'supertype'
        ? 'vscode.provideSupertypes'
        : 'vscode.provideSubtypes',
  requiresDocument: false,
  buildArguments: (item) => [item],
  classifyResult: classifyArrayProviderResult,
});

const invocationStatus = <T>(
  result: ProviderInvocationResult<T>,
): 'completed' | 'unavailable' | 'notReady' | 'cancelled' | 'timedOut' | 'failed' | 'positionOutOfRange' =>
  result.status === 'failed' && result.reason === 'providerArgumentsInvalid'
    ? 'positionOutOfRange'
    : result.status;

const warningList = (warnings: ReadonlySet<string>): readonly string[] | undefined =>
  warnings.size === 0 ? undefined : Object.freeze([...warnings]);

export class HierarchyProviderBridge {
  readonly #host: HierarchyProviderHost;
  readonly #runtime: ProviderRuntime;
  readonly #pathAccess: WorkspacePathAccess;
  readonly #now: () => number;
  readonly #traversals = new Map<string, TraversalState>();
  #nextTraversal = 0;

  constructor(
    host: HierarchyProviderHost,
    pathAccess: WorkspacePathAccess = systemWorkspacePathAccess,
    now: () => number = Date.now,
    defaultTimeoutMs?: number,
  ) {
    this.#host = host;
    this.#runtime = new ProviderRuntime({
      host,
      pathAccess,
      ...(defaultTimeoutMs === undefined ? {} : { defaultTimeoutMs }),
    });
    this.#pathAccess = pathAccess;
    this.#now = now;
  }

  #timestamp(): number {
    const value = this.#now();
    if (!Number.isSafeInteger(value) || value < 0) {
      throw new RangeError('Hierarchy cache clock returned an invalid timestamp.');
    }
    return value;
  }

  #prune(now: number): void {
    for (const [id, state] of this.#traversals) {
      if (now - state.lastTouchedAt >= HIERARCHY_TRAVERSAL_TTL_MS) {
        this.#traversals.delete(id);
      }
    }
  }

  #createTraversal(kind: HierarchyBridgeKind): TraversalState | undefined {
    const now = this.#timestamp();
    this.#prune(now);
    if (this.#traversals.size >= HIERARCHY_MAX_ACTIVE_TRAVERSALS ||
        this.#nextTraversal >= Number.MAX_SAFE_INTEGER) {
      return undefined;
    }
    this.#nextTraversal += 1;
    const state: TraversalState = {
      id: `h${this.#nextTraversal}`,
      kind,
      nodes: new Map(),
      lastTouchedAt: now,
      nextNode: 0,
    };
    this.#traversals.set(state.id, state);
    return state;
  }

  async #mapItem(
    context: WorkspacePathContext,
    raw: unknown,
    warnings: Set<string>,
    callSites?: readonly Range[],
  ): Promise<MappedProviderItem | undefined> {
    const record = asRecord(raw);
    const name = typeof record?.name === 'string' && record.name.length > 0 && record.name.length <= 4_096
      ? record.name
      : undefined;
    const kind = publicKind(record?.kind);
    const uri = providerUri(record?.uri);
    const selection = providerRange(record?.selectionRange);
    if (record === undefined || name === undefined || kind === undefined ||
        uri === undefined || selection === undefined) {
      warnings.add('provider_candidate_invalid');
      return undefined;
    }
    let file: string;
    try {
      file = (await logicalPathFromProviderLocation(context, {
        uriScheme: uri.scheme,
        lexicalAbsolutePath: uri.fsPath,
      }, this.#pathAccess)).logicalPath;
    } catch (error) {
      warnings.add(error instanceof WorkspaceBoundaryError
        ? 'provider_candidate_outside_workspace'
        : 'provider_candidate_invalid');
      return undefined;
    }
    return Object.freeze({
      raw,
      symbol: Object.freeze({
        name,
        kind,
        file,
        line: selection.startLine,
        column: selection.startColumn,
      }),
      ...(callSites === undefined || callSites.length === 0 ? {} : { callSites }),
    });
  }

  #registerItems(
    state: TraversalState,
    values: readonly MappedProviderItem[],
  ): readonly HierarchyBridgeNode[] | undefined {
    if (state.nodes.size + values.length > HIERARCHY_MAX_NODES_PER_TRAVERSAL) {
      return undefined;
    }
    const nodes: HierarchyBridgeNode[] = [];
    for (const value of values) {
      if (state.nextNode >= Number.MAX_SAFE_INTEGER) return undefined;
      state.nextNode += 1;
      const nodeId = `n${state.nextNode}`;
      state.nodes.set(nodeId, value.raw);
      nodes.push(Object.freeze({
        nodeId,
        symbol: value.symbol,
        ...(value.callSites === undefined ? {} : { callSites: value.callSites }),
      }));
    }
    state.lastTouchedAt = this.#timestamp();
    return Object.freeze(nodes);
  }

  async #prepare(
    context: WorkspacePathContext,
    params: PrepareParams,
    signal: AbortSignal,
  ): Promise<JsonValue> {
    const invocation = await this.#runtime.invoke(
      context,
      prepareAdapter(this.#host, params.kind),
      params,
      {
        logicalFile: params.file,
        signal,
        ...(params.kind === 'call' && cppSourceFile.test(params.file)
          ? {
              pollDelaysMs: CPP_COLD_HIERARCHY_POLL_DELAYS_MS,
              prioritizeDocument: true,
            }
          : {}),
      },
    );
    const status = invocationStatus(invocation);
    if (status !== 'completed' || invocation.status !== 'completed') return { status };
    const state = this.#createTraversal(params.kind);
    if (state === undefined) return { status: 'failed' };
    const warnings = new Set<string>();
    const mapped: MappedProviderItem[] = [];
    for (const raw of invocation.value) {
      const item = await this.#mapItem(context, raw, warnings);
      if (item !== undefined) mapped.push(item);
    }
    const nodes = this.#registerItems(state, mapped);
    if (nodes === undefined) {
      this.#traversals.delete(state.id);
      return { status: 'failed' };
    }
    const publicWarnings = warningList(warnings);
    return {
      status: 'completed',
      traversalId: state.id,
      nodes,
      ...(publicWarnings === undefined ? {} : { warnings: publicWarnings }),
    } as unknown as JsonValue;
  }

  async #expand(
    context: WorkspacePathContext,
    params: ExpandParams,
    signal: AbortSignal,
  ): Promise<JsonValue> {
    const now = this.#timestamp();
    this.#prune(now);
    const state = this.#traversals.get(params.traversalId);
    const rawParent = state?.nodes.get(params.nodeId);
    if (state === undefined || rawParent === undefined ||
        !directionMatchesKind(state.kind, params.direction)) {
      return { status: 'failed' };
    }
    state.lastTouchedAt = now;
    const invocation = await this.#runtime.invoke(
      context,
      expandAdapter(params.direction),
      rawParent,
      { signal },
    );
    if (invocation.status !== 'completed') return { status: invocation.status };

    const warnings = new Set<string>();
    const mapped: MappedProviderItem[] = [];
    for (const raw of invocation.value) {
      if (state.kind === 'type') {
        const item = await this.#mapItem(context, raw, warnings);
        if (item !== undefined) mapped.push(item);
        continue;
      }
      const edge = asRecord(raw);
      const rawChild = params.direction === 'incoming' ? edge?.from : edge?.to;
      if (edge === undefined || !Array.isArray(edge.fromRanges)) {
        warnings.add('provider_candidate_invalid');
        continue;
      }
      const callSites: Range[] = [];
      let invalidRange = false;
      for (const range of edge.fromRanges) {
        const mappedRange = providerRange(range);
        if (mappedRange === undefined) {
          invalidRange = true;
          break;
        }
        callSites.push(mappedRange);
      }
      if (invalidRange) {
        warnings.add('provider_candidate_invalid');
        continue;
      }
      const item = await this.#mapItem(context, rawChild, warnings, Object.freeze(callSites));
      if (item !== undefined) mapped.push(item);
    }
    const nodes = this.#registerItems(state, mapped);
    if (nodes === undefined) return { status: 'failed' };
    const publicWarnings = warningList(warnings);
    return {
      status: 'completed',
      nodes,
      ...(publicWarnings === undefined ? {} : { warnings: publicWarnings }),
    } as unknown as JsonValue;
  }

  handle: HierarchyBridgeHandler = async (context, request, signal) => {
    if (request.method === HIERARCHY_BRIDGE_METHODS.prepare) {
      const params = parsePrepare(request.params);
      return params === undefined ? { status: 'failed' } : this.#prepare(context, params, signal);
    }
    if (request.method === HIERARCHY_BRIDGE_METHODS.expand) {
      const params = parseExpand(request.params);
      return params === undefined ? { status: 'failed' } : this.#expand(context, params, signal);
    }
    if (request.method === HIERARCHY_BRIDGE_METHODS.release) {
      const params = parseRelease(request.params);
      if (params === undefined || !this.#traversals.delete(params.traversalId)) {
        return { status: 'failed' };
      }
      return { status: 'completed' };
    }
    return undefined;
  };
}

export const createHierarchyBridgeHandler = (
  host: HierarchyProviderHost,
  pathAccess: WorkspacePathAccess = systemWorkspacePathAccess,
  defaultTimeoutMs?: number,
): HierarchyBridgeHandler =>
  new HierarchyProviderBridge(host, pathAccess, Date.now, defaultTimeoutMs).handle;
