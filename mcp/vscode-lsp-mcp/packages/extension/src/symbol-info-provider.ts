import type { TextDocument } from 'vscode';
import {
  SYMBOL_INFO_BRIDGE_METHOD,
  SYMBOL_INFO_INCLUDES,
  WorkspaceBoundaryError,
  contextSnippetForLine,
  logicalPathFromProviderLocation,
  systemWorkspacePathAccess,
  type IpcRequest,
  type JsonValue,
  type LocationInfo,
  type SignatureInfoBridgeCandidate,
  type SignatureParameter,
  type SymbolInfoBridgeCandidate,
  type SymbolInfoInclude,
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

interface SymbolInfoInput {
  readonly file: string;
  readonly line: number;
  readonly column: number;
}

interface SymbolInfoBridgeParams extends SymbolInfoInput {
  readonly include: readonly SymbolInfoInclude[];
  readonly contextLines: number;
}

interface ProviderPoint {
  readonly character: number;
  readonly line: number;
}

interface ProviderLocation {
  readonly point: ProviderPoint;
  readonly rawUri: unknown;
  readonly uri: { readonly scheme: string; readonly fsPath: string };
}

type CapabilityStatus =
  | 'completed'
  | 'unavailable'
  | 'notReady'
  | 'cancelled'
  | 'timedOut'
  | 'failed'
  | 'positionOutOfRange';

interface CapabilityOutcome {
  readonly status: CapabilityStatus;
  readonly candidates: readonly SymbolInfoBridgeCandidate[];
}

export interface SymbolInfoProviderHost extends VscodeProviderHost {
  createPosition(line: number, character: number): unknown;
  openProviderDocument(uri: unknown): PromiseLike<TextDocument>;
}

export type SymbolInfoBridgeHandler = (
  context: WorkspacePathContext,
  request: IpcRequest,
  signal: AbortSignal,
) => Promise<JsonValue | undefined>;

const includeSet = new Set<string>(SYMBOL_INFO_INCLUDES);

const asRecord = (value: unknown): Record<string, unknown> | undefined =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;

const exactFields = (value: Record<string, unknown>, fields: readonly string[]): boolean => {
  const allowed = new Set(fields);
  return Object.keys(value).every((key) => allowed.has(key));
};

const parseParams = (value: unknown): SymbolInfoBridgeParams | undefined => {
  const record = asRecord(value);
  if (record === undefined ||
      !exactFields(record, ['file', 'line', 'column', 'include', 'contextLines']) ||
      typeof record.file !== 'string' || record.file.length === 0 ||
      !Number.isSafeInteger(record.line) || (record.line as number) < 1 ||
      !Number.isSafeInteger(record.column) || (record.column as number) < 1 ||
      !Number.isSafeInteger(record.contextLines) || (record.contextLines as number) < 0 ||
      (record.contextLines as number) > 5 ||
      !Array.isArray(record.include) || record.include.length === 0) {
    return undefined;
  }
  const includes = record.include;
  if (new Set(includes).size !== includes.length ||
      includes.some((entry) => typeof entry !== 'string' || !includeSet.has(entry))) {
    return undefined;
  }
  return {
    file: record.file,
    line: record.line as number,
    column: record.column as number,
    contextLines: record.contextLines as number,
    include: Object.freeze([...includes]) as readonly SymbolInfoInclude[],
  };
};

const normalizedText = (value: string): string | undefined => {
  const normalized = value.replaceAll('\r\n', '\n').replaceAll('\r', '\n').trim();
  return normalized.length === 0 ? undefined : normalized;
};

const documentationText = (value: unknown): string | undefined => {
  if (typeof value === 'string') return normalizedText(value);
  const record = asRecord(value);
  return typeof record?.value === 'string' ? normalizedText(record.value) : undefined;
};

const hoverPart = (value: unknown): string | undefined => {
  if (typeof value === 'string') return normalizedText(value);
  const record = asRecord(value);
  if (typeof record?.value !== 'string') return undefined;
  const text = normalizedText(record.value);
  if (text === undefined) return undefined;
  if (typeof record.language !== 'string') return text;
  const language = /^[A-Za-z0-9_+#.-]+$/u.test(record.language) ? record.language : '';
  return `\`\`\`${language}\n${text}\n\`\`\``;
};

const documentLines = (document: TextDocument): readonly string[] =>
  Object.freeze(document.getText().replaceAll('\r\n', '\n').replaceAll('\r', '\n').split('\n'));

const providerPosition = (
  host: SymbolInfoProviderHost,
  input: SymbolInfoInput,
  document: TextDocument,
): unknown => {
  const line = input.line - 1;
  const character = input.column - 1;
  const lines = documentLines(document);
  if (line >= lines.length || character > (lines[line]?.length ?? -1)) {
    throw new RangeError('Symbol info position is outside the document.');
  }
  return host.createPosition(line, character);
};

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
  return { line: start.line as number, character: start.character as number };
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
  return {
    point,
    rawUri,
    uri: { scheme: uri.scheme, fsPath: uri.fsPath },
  };
};

const snippetForLocation = async (
  host: SymbolInfoProviderHost,
  location: ProviderLocation,
  contextLines: number,
): Promise<string | undefined> => {
  if (contextLines === 0) return undefined;
  const document = await host.openProviderDocument(location.rawUri);
  const snippet = contextSnippetForLine(document.getText(), location.point.line + 1, contextLines);
  return snippet === undefined || snippet.length === 0 ? undefined : snippet;
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

const arrayAdapter = (
  host: SymbolInfoProviderHost,
  command: PublicProviderCommand,
): ProviderCommandAdapter<SymbolInfoInput, readonly unknown[]> => ({
  command,
  requiresDocument: true,
  buildArguments: (input, document) => {
    if (document === undefined) throw new RangeError('Document activation invariant failed.');
    return [document.uri, providerPosition(host, input, document)];
  },
  classifyResult: classifyArrayProviderResult,
});

const signatureAdapter = (
  host: SymbolInfoProviderHost,
): ProviderCommandAdapter<SymbolInfoInput, Record<string, unknown>> => ({
  command: 'vscode.executeSignatureHelpProvider',
  requiresDocument: true,
  buildArguments: (input, document) => {
    if (document === undefined) throw new RangeError('Document activation invariant failed.');
    return [document.uri, providerPosition(host, input, document)];
  },
  classifyResult: (value) => {
    if (value === undefined) return { status: 'notReady' };
    const record = asRecord(value);
    return record !== undefined && Array.isArray(record.signatures)
      ? { status: 'ready', value: record }
      : { status: 'invalid' };
  },
});

const invocationStatus = <T>(result: ProviderInvocationResult<T>): CapabilityStatus =>
  result.status === 'failed' && result.reason === 'providerArgumentsInvalid'
    ? 'positionOutOfRange'
    : result.status;

const parameterLabel = (value: unknown, signatureLabel: string): string | undefined => {
  if (typeof value === 'string') return normalizedText(value);
  if (!Array.isArray(value) || value.length !== 2 ||
      !Number.isSafeInteger(value[0]) || !Number.isSafeInteger(value[1])) {
    return undefined;
  }
  const start = value[0] as number;
  const end = value[1] as number;
  return start >= 0 && end > start && end <= signatureLabel.length
    ? signatureLabel.slice(start, end)
    : undefined;
};

const signatureCandidates = (
  value: Record<string, unknown>,
  warnings: Set<string>,
): readonly SignatureInfoBridgeCandidate[] => {
  const rawSignatures = value.signatures as readonly unknown[];
  const activeIndex = Number.isSafeInteger(value.activeSignature) &&
    (value.activeSignature as number) >= 0 &&
    (value.activeSignature as number) < rawSignatures.length
    ? value.activeSignature as number
    : undefined;
  const order = rawSignatures.map((_entry, index) => index);
  if (activeIndex !== undefined) {
    order.splice(activeIndex, 1);
    order.unshift(activeIndex);
  }

  const candidates: SignatureInfoBridgeCandidate[] = [];
  for (const index of order) {
    const record = asRecord(rawSignatures[index]);
    const label = typeof record?.label === 'string' ? normalizedText(record.label) : undefined;
    if (record === undefined || label === undefined) {
      warnings.add('signatureHelp_candidate_invalid');
      continue;
    }
    const rawParameters = Array.isArray(record.parameters) ? record.parameters : [];
    const mappedParameters: SignatureParameter[] = [];
    let hasParameterDocumentation = false;
    for (const rawParameter of rawParameters) {
      const parameter = asRecord(rawParameter);
      const mappedLabel = parameter === undefined
        ? undefined
        : parameterLabel(parameter.label, label);
      if (parameter === undefined || mappedLabel === undefined) {
        warnings.add('signatureHelp_candidate_invalid');
        continue;
      }
      const documentation = documentationText(parameter.documentation);
      if (documentation !== undefined) hasParameterDocumentation = true;
      mappedParameters.push(Object.freeze({
        label: mappedLabel,
        ...(documentation === undefined ? {} : { documentation }),
      }));
    }
    const signatureActiveParameter = Number.isSafeInteger(record.activeParameter)
      ? record.activeParameter as number
      : index === activeIndex && Number.isSafeInteger(value.activeParameter)
        ? value.activeParameter as number
        : undefined;
    const activeParameter = signatureActiveParameter !== undefined &&
      signatureActiveParameter >= 0 && signatureActiveParameter < rawParameters.length
      ? signatureActiveParameter
      : undefined;
    const documentation = documentationText(record.documentation);
    candidates.push(Object.freeze({
      type: 'signatureHelp',
      label,
      activeSignature: index === activeIndex,
      ...(activeParameter === undefined ? {} : { activeParameter }),
      ...(documentation === undefined ? {} : { documentation }),
      ...(!hasParameterDocumentation || mappedParameters.length === 0
        ? {}
        : { parameters: Object.freeze(mappedParameters) }),
    }));
  }
  return Object.freeze(candidates);
};

export class SymbolInfoProviderBridge {
  readonly #host: SymbolInfoProviderHost;
  readonly #pathAccess: WorkspacePathAccess;
  readonly #runtime: ProviderRuntime;

  constructor(
    host: SymbolInfoProviderHost,
    pathAccess: WorkspacePathAccess = systemWorkspacePathAccess,
    defaultTimeoutMs?: number,
  ) {
    this.#host = host;
    this.#pathAccess = pathAccess;
    this.#runtime = new ProviderRuntime({
      host,
      pathAccess,
      ...(defaultTimeoutMs === undefined ? {} : { defaultTimeoutMs }),
    });
  }

  async #locations(
    context: WorkspacePathContext,
    type: LocationInfo['type'],
    command: PublicProviderCommand,
    input: SymbolInfoBridgeParams,
    signal: AbortSignal,
    warnings: Set<string>,
  ): Promise<CapabilityOutcome> {
    const invocation = await this.#runtime.invoke(
      context,
      arrayAdapter(this.#host, command),
      input,
      { logicalFile: input.file, signal },
    );
    if (invocation.status !== 'completed') {
      return { status: invocationStatus(invocation), candidates: [] };
    }
    const mapped = await mapBounded(invocation.value, 4, async (raw) => {
      const location = providerLocation(raw);
      if (location === undefined) {
        warnings.add(`${type}_candidate_invalid`);
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
          ? `${type}_candidate_outside_workspace`
          : `${type}_candidate_invalid`);
        return undefined;
      }
      let snippet: string | undefined;
      try {
        snippet = await snippetForLocation(this.#host, location, input.contextLines);
        if (input.contextLines > 0 && snippet === undefined) warnings.add(`${type}_snippet_unavailable`);
      } catch {
        warnings.add(`${type}_snippet_unavailable`);
      }
      return Object.freeze({
        type,
        file,
        line: location.point.line + 1,
        column: location.point.character + 1,
        ...(snippet === undefined ? {} : { snippet }),
      }) satisfies LocationInfo;
    });
    return {
      status: 'completed',
      candidates: Object.freeze(mapped.filter(
        (candidate): candidate is LocationInfo => candidate !== undefined,
      )),
    };
  }

  async #hover(
    context: WorkspacePathContext,
    input: SymbolInfoBridgeParams,
    signal: AbortSignal,
    warnings: Set<string>,
  ): Promise<CapabilityOutcome> {
    const invocation = await this.#runtime.invoke(
      context,
      arrayAdapter(this.#host, 'vscode.executeHoverProvider'),
      input,
      { logicalFile: input.file, signal },
    );
    if (invocation.status !== 'completed') {
      return { status: invocationStatus(invocation), candidates: [] };
    }
    const candidates: SymbolInfoBridgeCandidate[] = [];
    for (const raw of invocation.value) {
      const record = asRecord(raw);
      if (record === undefined || !Array.isArray(record.contents)) {
        warnings.add('hover_candidate_invalid');
        continue;
      }
      const text = normalizedText(record.contents.map(hoverPart).filter(
        (part): part is string => part !== undefined,
      ).join('\n\n'));
      if (text === undefined) {
        warnings.add('hover_candidate_invalid');
        continue;
      }
      candidates.push(Object.freeze({ type: 'hover', text }));
    }
    return { status: 'completed', candidates: Object.freeze(candidates) };
  }

  async #signatureHelp(
    context: WorkspacePathContext,
    input: SymbolInfoBridgeParams,
    signal: AbortSignal,
    warnings: Set<string>,
  ): Promise<CapabilityOutcome> {
    const invocation = await this.#runtime.invoke(
      context,
      signatureAdapter(this.#host),
      input,
      { logicalFile: input.file, signal },
    );
    return invocation.status === 'completed'
      ? { status: 'completed', candidates: signatureCandidates(invocation.value, warnings) }
      : { status: invocationStatus(invocation), candidates: [] };
  }

  async #capability(
    context: WorkspacePathContext,
    include: SymbolInfoInclude,
    input: SymbolInfoBridgeParams,
    signal: AbortSignal,
    warnings: Set<string>,
  ): Promise<CapabilityOutcome> {
    switch (include) {
      case 'hover':
        return this.#hover(context, input, signal, warnings);
      case 'declaration':
        return this.#locations(context, include, 'vscode.executeDeclarationProvider', input, signal, warnings);
      case 'definition':
        return this.#locations(context, include, 'vscode.executeDefinitionProvider', input, signal, warnings);
      case 'typeDefinition':
        return this.#locations(context, include, 'vscode.executeTypeDefinitionProvider', input, signal, warnings);
      case 'implementation':
        return this.#locations(context, include, 'vscode.executeImplementationProvider', input, signal, warnings);
      case 'signatureHelp':
        return this.#signatureHelp(context, input, signal, warnings);
      default: {
        const exhaustive: never = include;
        throw new Error(`Unhandled symbol info capability: ${exhaustive}`);
      }
    }
  }

  async #symbolInfo(
    context: WorkspacePathContext,
    params: SymbolInfoBridgeParams,
    signal: AbortSignal,
  ): Promise<JsonValue> {
    const selected = SYMBOL_INFO_INCLUDES.filter((include) => params.include.includes(include));
    const warnings = new Set<string>();
    const outcomes = await Promise.all(selected.map((include) =>
      this.#capability(context, include, params, signal, warnings)));
    const completed = outcomes.filter((outcome) => outcome.status === 'completed');
    for (const [index, outcome] of outcomes.entries()) {
      if (outcome.status !== 'completed') warnings.add(`${selected[index]}_${outcome.status}`);
    }
    if (completed.length === 0) {
      const priority: readonly CapabilityStatus[] = [
        'positionOutOfRange',
        'timedOut',
        'cancelled',
        'failed',
        'notReady',
        'unavailable',
      ];
      return { status: priority.find((status) => outcomes.some((outcome) => outcome.status === status)) ?? 'failed' };
    }
    const publicWarnings = warnings.size === 0 ? undefined : Object.freeze([...warnings]);
    return {
      status: 'completed',
      candidates: Object.freeze(completed.flatMap((outcome) => outcome.candidates)),
      ...(publicWarnings === undefined ? {} : { warnings: publicWarnings }),
    } as unknown as JsonValue;
  }

  handle: SymbolInfoBridgeHandler = async (context, request, signal) => {
    if (request.method !== SYMBOL_INFO_BRIDGE_METHOD) return undefined;
    const params = parseParams(request.params);
    return params === undefined ? { status: 'failed' } : this.#symbolInfo(context, params, signal);
  };
}

export const createSymbolInfoBridgeHandler = (
  host: SymbolInfoProviderHost,
  pathAccess: WorkspacePathAccess = systemWorkspacePathAccess,
  defaultTimeoutMs?: number,
): SymbolInfoBridgeHandler => new SymbolInfoProviderBridge(host, pathAccess, defaultTimeoutMs).handle;
