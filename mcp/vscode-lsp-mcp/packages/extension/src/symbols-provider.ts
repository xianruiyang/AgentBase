import type { TextDocument } from 'vscode';
import {
  SYMBOL_BRIDGE_METHODS,
  SYMBOL_KINDS,
  WorkspaceBoundaryError,
  contextSnippetForLine,
  logicalPathFromProviderLocation,
  systemWorkspacePathAccess,
  type IpcRequest,
  type JsonValue,
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

interface ProviderUri {
  readonly fsPath: string;
  readonly scheme: string;
}

interface ProviderPoint {
  readonly character: number;
  readonly line: number;
}

interface ProviderRange {
  readonly start: ProviderPoint;
  readonly end: ProviderPoint;
}

interface ProviderLocation {
  readonly range: ProviderRange;
  readonly uri: ProviderUri;
  readonly rawUri: unknown;
}

interface WorkspaceProviderInput {
  readonly query: string;
}

interface DocumentProviderInput {
  readonly file: string;
}

interface WorkspaceBridgeParams {
  readonly contextLines: number;
  readonly query: string;
}

interface DocumentBridgeParams {
  readonly contextLines: number;
  readonly file: string;
}

interface WorkspaceCandidate {
  readonly name: string;
  readonly kind: SymbolKind;
  readonly file: string;
  readonly line: number;
  readonly column: number;
  readonly container?: string;
  readonly snippet?: string;
}

interface DocumentCandidate {
  readonly kind: SymbolKind;
  readonly path: readonly string[];
  readonly line: number;
  readonly column: number;
  readonly range?: {
    readonly startLine: number;
    readonly startColumn: number;
    readonly endLine: number;
    readonly endColumn: number;
  };
  readonly snippet?: string;
}

export interface SymbolsProviderHost extends VscodeProviderHost {
  openProviderDocument(uri: unknown): PromiseLike<TextDocument>;
}

export type SymbolsBridgeHandler = (
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

const contextLines = (value: unknown): number | undefined =>
  Number.isSafeInteger(value) && (value as number) >= 0 && (value as number) <= 5
    ? value as number
    : undefined;

const parseWorkspaceParams = (value: unknown): WorkspaceBridgeParams | undefined => {
  const record = asRecord(value);
  if (record === undefined || !exactFields(record, ['query', 'contextLines'])) return undefined;
  const lines = contextLines(record.contextLines);
  return typeof record.query === 'string' && record.query.length > 0 && record.query.length <= 500 &&
    lines !== undefined
    ? { query: record.query, contextLines: lines }
    : undefined;
};

const parseDocumentParams = (value: unknown): DocumentBridgeParams | undefined => {
  const record = asRecord(value);
  if (record === undefined || !exactFields(record, ['file', 'contextLines'])) return undefined;
  const lines = contextLines(record.contextLines);
  return typeof record.file === 'string' && record.file.length > 0 && lines !== undefined
    ? { file: record.file, contextLines: lines }
    : undefined;
};

const pointFromValue = (value: unknown): ProviderPoint | undefined => {
  const point = asRecord(value);
  if (point === undefined ||
      !Number.isSafeInteger(point.line) || (point.line as number) < 0 ||
      (point.line as number) >= Number.MAX_SAFE_INTEGER ||
      !Number.isSafeInteger(point.character) || (point.character as number) < 0 ||
      (point.character as number) >= Number.MAX_SAFE_INTEGER) {
    return undefined;
  }
  return { line: point.line as number, character: point.character as number };
};

const rangeFromValue = (value: unknown): ProviderRange | undefined => {
  const range = asRecord(value);
  const start = pointFromValue(range?.start);
  const end = pointFromValue(range?.end);
  if (start === undefined || end === undefined ||
      end.line < start.line ||
      (end.line === start.line && end.character < start.character)) {
    return undefined;
  }
  return { start, end };
};

const pointFromRange = (value: unknown): ProviderPoint | undefined => {
  const range = asRecord(value);
  return pointFromValue(range?.start);
};

const locationFromValue = (value: unknown): ProviderLocation | undefined => {
  const location = asRecord(value);
  const rawUri = location?.uri;
  const uri = asRecord(rawUri);
  const range = rangeFromValue(location?.range);
  if (
    uri === undefined ||
    typeof uri.scheme !== 'string' ||
    typeof uri.fsPath !== 'string' ||
    range === undefined
  ) {
    return undefined;
  }
  return {
    uri: { scheme: uri.scheme, fsPath: uri.fsPath },
    range,
    rawUri,
  };
};

const publicKind = (value: unknown): SymbolKind | undefined => {
  if (!Number.isSafeInteger(value)) return undefined;
  return SYMBOL_KINDS[value as number] ?? 'unknown';
};

const nonEmptyText = (value: unknown): string | undefined =>
  typeof value === 'string' && value.length > 0
    ? value
    : undefined;

const snippetFor = (
  document: TextDocument,
  oneBasedLine: number,
  lines: number,
): string | undefined => {
  const snippet = contextSnippetForLine(document.getText(), oneBasedLine, lines);
  return snippet === undefined || snippet.length === 0 ? undefined : snippet;
};

const documentLines = (document: TextDocument): readonly string[] =>
  Object.freeze(document.getText().replaceAll('\r\n', '\n').replaceAll('\r', '\n').split('\n'));

const isValidDocumentPoint = (
  lines: readonly string[],
  point: ProviderPoint,
): boolean => point.line < lines.length && point.character <= (lines[point.line]?.length ?? -1);

const isValidDocumentRange = (
  lines: readonly string[],
  range: ProviderRange,
): boolean => isValidDocumentPoint(lines, range.start) && isValidDocumentPoint(lines, range.end);

const publicRange = (range: ProviderRange) => Object.freeze({
  startLine: range.start.line + 1,
  startColumn: range.start.character + 1,
  endLine: range.end.line + 1,
  endColumn: range.end.character + 1,
});

const mapBounded = async <T, R>(
  values: readonly T[],
  limit: number,
  operation: (value: T, index: number) => Promise<R>,
): Promise<readonly R[]> => {
  const results = new Array<R>(values.length);
  let next = 0;
  const worker = async (): Promise<void> => {
    while (next < values.length) {
      const index = next;
      next += 1;
      const value = values[index];
      if (value !== undefined) results[index] = await operation(value, index);
    }
  };
  await Promise.all(Array.from({ length: Math.min(limit, values.length) }, worker));
  return Object.freeze(results);
};

const providerObservation = <T>(result: ProviderInvocationResult<T>) => Object.freeze({
  status: result.status,
  elapsedMs: result.elapsedMs,
  attempts: result.attempts,
});

const bridgeStatus = <T>(result: ProviderInvocationResult<T>): JsonValue | undefined => {
  if (result.status === 'completed') return undefined;
  return { status: result.status, provider: providerObservation(result) };
};

const workspaceAdapter: ProviderCommandAdapter<WorkspaceProviderInput, readonly unknown[]> = {
  command: 'vscode.executeWorkspaceSymbolProvider',
  requiresDocument: false,
  buildArguments: (input) => [input.query],
  classifyResult: classifyArrayProviderResult,
};

const createDocumentAdapter = (): {
  readonly adapter: ProviderCommandAdapter<DocumentProviderInput, readonly unknown[]>;
  readonly document: () => TextDocument | undefined;
} => {
  let activeDocument: TextDocument | undefined;
  return {
    adapter: {
      command: 'vscode.executeDocumentSymbolProvider',
      requiresDocument: true,
      buildArguments: (_input, document) => {
        if (document === undefined) throw new Error('Document activation invariant failed.');
        activeDocument = document;
        return [document.uri];
      },
      classifyResult: classifyArrayProviderResult,
    },
    document: () => activeDocument,
  };
};

const warningList = (warnings: ReadonlySet<string>): readonly string[] | undefined =>
  warnings.size === 0 ? undefined : Object.freeze([...warnings]);

export class SymbolsProviderBridge {
  readonly #host: SymbolsProviderHost;
  readonly #runtime: ProviderRuntime;
  readonly #pathAccess: WorkspacePathAccess;

  constructor(
    host: SymbolsProviderHost,
    pathAccess: WorkspacePathAccess = systemWorkspacePathAccess,
    defaultTimeoutMs?: number,
  ) {
    this.#host = host;
    this.#runtime = new ProviderRuntime({
      host,
      pathAccess,
      ...(defaultTimeoutMs === undefined ? {} : { defaultTimeoutMs }),
    });
    this.#pathAccess = pathAccess;
  }

  async #workspaceSymbols(
    context: WorkspacePathContext,
    params: WorkspaceBridgeParams,
    signal: AbortSignal,
  ): Promise<JsonValue> {
    const invocation = await this.#runtime.invoke(
      context,
      workspaceAdapter,
      { query: params.query },
      { signal },
    );
    const terminal = bridgeStatus(invocation);
    if (terminal !== undefined || invocation.status !== 'completed') {
      return terminal ?? { status: 'failed' };
    }

    const warnings = new Set<string>();
    const mapped = await mapBounded(invocation.value, 4, async (raw) => {
      const record = asRecord(raw);
      const name = nonEmptyText(record?.name);
      const kind = publicKind(record?.kind);
      const location = locationFromValue(record?.location);
      if (record === undefined || name === undefined || kind === undefined || location === undefined) {
        warnings.add('provider_candidate_invalid');
        return undefined;
      }
      let file: string;
      try {
        file = (await logicalPathFromProviderLocation(context, {
          uriScheme: location.uri.scheme,
          lexicalAbsolutePath: location.uri.fsPath,
        }, this.#pathAccess)).logicalPath;
      } catch (error) {
        warnings.add(error instanceof WorkspaceBoundaryError
          ? 'provider_candidate_outside_workspace'
          : 'provider_candidate_invalid');
        return undefined;
      }
      const line = location.range.start.line + 1;
      const column = location.range.start.character + 1;
      let snippet: string | undefined;
      if (params.contextLines > 0) {
        try {
          snippet = snippetFor(
            await this.#host.openProviderDocument(location.rawUri),
            line,
            params.contextLines,
          );
          if (snippet === undefined) warnings.add('snippet_unavailable');
        } catch {
          warnings.add('snippet_unavailable');
        }
      }
      const container = nonEmptyText(record.containerName);
      return Object.freeze({
        name,
        kind,
        file,
        line,
        column,
        ...(container === undefined ? {} : { container }),
        ...(snippet === undefined ? {} : { snippet }),
      }) satisfies WorkspaceCandidate;
    });
    const candidates = Object.freeze(mapped.filter(
      (candidate): candidate is WorkspaceCandidate => candidate !== undefined,
    ));
    const publicWarnings = warningList(warnings);
    return {
      status: 'completed',
      candidates,
      provider: providerObservation(invocation),
      ...(publicWarnings === undefined ? {} : { warnings: publicWarnings }),
    } as unknown as JsonValue;
  }

  async #documentSymbols(
    context: WorkspacePathContext,
    params: DocumentBridgeParams,
    signal: AbortSignal,
  ): Promise<JsonValue> {
    const documentAdapter = createDocumentAdapter();
    const invocation = await this.#runtime.invoke(
      context,
      documentAdapter.adapter,
      { file: params.file },
      { logicalFile: params.file, signal },
    );
    const terminal = bridgeStatus(invocation);
    if (terminal !== undefined || invocation.status !== 'completed') {
      return terminal ?? { status: 'failed' };
    }
    const document = documentAdapter.document();
    if (document === undefined) return { status: 'failed' };
    const lines = documentLines(document);

    const warnings = new Set<string>();
    const candidates: DocumentCandidate[] = [];
    const visited = new Set<object>();
    const stack = [...invocation.value].reverse().map((raw) => ({
      raw,
      parentPath: Object.freeze([]) as readonly string[],
    }));
    while (stack.length > 0) {
      const current = stack.pop();
      if (current === undefined) break;
      const record = asRecord(current.raw);
      if (record === undefined || visited.has(record)) {
        warnings.add('provider_candidate_invalid');
        continue;
      }
      visited.add(record);

      const name = nonEmptyText(record.name);
      const kind = publicKind(record.kind);
      const selection = pointFromRange(record.selectionRange);
      const fullRange = rangeFromValue(record.range);
      if (name !== undefined && kind !== undefined && selection !== undefined && Array.isArray(record.children)) {
        const path = Object.freeze([...current.parentPath, name]);
        if (!isValidDocumentPoint(lines, selection)) {
          warnings.add('provider_candidate_invalid');
          for (let index = record.children.length - 1; index >= 0; index -= 1) {
            stack.push({ raw: record.children[index], parentPath: path });
          }
          continue;
        }
        const line = selection.line + 1;
        let snippet: string | undefined;
        if (params.contextLines > 0) {
          try {
            snippet = snippetFor(document, line, params.contextLines);
          } catch {
            snippet = undefined;
          }
        }
        if (params.contextLines > 0 && snippet === undefined) warnings.add('snippet_unavailable');
        candidates.push(Object.freeze({
          kind,
          path,
          line,
          column: selection.character + 1,
          ...(fullRange === undefined || !isValidDocumentRange(lines, fullRange)
            ? {}
            : { range: publicRange(fullRange) }),
          ...(snippet === undefined ? {} : { snippet }),
        }));
        for (let index = record.children.length - 1; index >= 0; index -= 1) {
          stack.push({ raw: record.children[index], parentPath: path });
        }
        continue;
      }

      const location = locationFromValue(record.location);
      if (name === undefined || kind === undefined || location === undefined) {
        warnings.add('provider_candidate_invalid');
        continue;
      }
      if (!isValidDocumentPoint(lines, location.range.start)) {
        warnings.add('provider_candidate_invalid');
        continue;
      }
      try {
        const mapped = await logicalPathFromProviderLocation(context, {
          uriScheme: location.uri.scheme,
          lexicalAbsolutePath: location.uri.fsPath,
        }, this.#pathAccess);
        if (mapped.logicalPath !== params.file) {
          warnings.add('provider_candidate_document_mismatch');
          continue;
        }
      } catch (error) {
        warnings.add(error instanceof WorkspaceBoundaryError
          ? 'provider_candidate_outside_workspace'
          : 'provider_candidate_invalid');
        continue;
      }
      const line = location.range.start.line + 1;
      let snippet: string | undefined;
      if (params.contextLines > 0) {
        try {
          snippet = snippetFor(document, line, params.contextLines);
        } catch {
          snippet = undefined;
        }
      }
      if (params.contextLines > 0 && snippet === undefined) warnings.add('snippet_unavailable');
      candidates.push(Object.freeze({
        kind,
        path: Object.freeze([name]),
        line,
        column: location.range.start.character + 1,
        ...(isValidDocumentRange(lines, location.range)
          ? { range: publicRange(location.range) }
          : {}),
        ...(snippet === undefined ? {} : { snippet }),
      }));
    }
    const publicWarnings = warningList(warnings);
    return {
      status: 'completed',
      candidates: Object.freeze(candidates),
      provider: providerObservation(invocation),
      ...(publicWarnings === undefined ? {} : { warnings: publicWarnings }),
    } as unknown as JsonValue;
  }

  handle: SymbolsBridgeHandler = async (context, request, signal) => {
    if (request.method === SYMBOL_BRIDGE_METHODS.workspace) {
      const params = parseWorkspaceParams(request.params);
      return params === undefined
        ? { status: 'failed' }
        : this.#workspaceSymbols(context, params, signal);
    }
    if (request.method === SYMBOL_BRIDGE_METHODS.document) {
      const params = parseDocumentParams(request.params);
      return params === undefined
        ? { status: 'failed' }
        : this.#documentSymbols(context, params, signal);
    }
    return undefined;
  };
}

export const createSymbolsBridgeHandler = (
  host: SymbolsProviderHost,
  pathAccess: WorkspacePathAccess = systemWorkspacePathAccess,
  defaultTimeoutMs?: number,
): SymbolsBridgeHandler => new SymbolsProviderBridge(host, pathAccess, defaultTimeoutMs).handle;
