import type { Position as VscodePosition, TextDocument } from 'vscode';
import {
  DIAGNOSTICS_BRIDGE_METHOD,
  REFERENCES_BRIDGE_METHOD,
  WorkspaceBoundaryError,
  buildCandidateCollection,
  contextSnippetForLine,
  logicalPathFromProviderLocation,
  matchesLogicalGlobs,
  resolveLogicalPath,
  systemWorkspacePathAccess,
  type Diagnostic,
  type DiagnosticRelatedInformation,
  type DiagnosticSeverity,
  type IpcRequest,
  type JsonValue,
  type Range,
  type ReferenceHit,
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
import { SymbolIdentityResolver } from './symbol-identity-resolver.js';

interface ReferenceBridgeParams {
  readonly file: string;
  readonly line: number;
  readonly column: number;
  readonly contextLines: number;
  readonly includeGlobs?: readonly string[];
  readonly excludeGlobs?: readonly string[];
  readonly resultStart?: number;
  readonly resultEnd?: number;
  readonly timeoutMs?: number;
}

interface DiagnosticsBridgeParams {
  readonly scope: 'files' | 'modifiedFiles' | 'workspace';
  readonly files?: readonly string[];
  readonly includeRelatedInformation: boolean;
}

interface ProviderPoint {
  readonly line: number;
  readonly character: number;
}

interface ProviderLocation {
  readonly rawUri: unknown;
  readonly uri: { readonly scheme: string; readonly fsPath: string };
  readonly point: ProviderPoint;
}

interface MappedReference {
  readonly location: ProviderLocation;
  readonly hit: ReferenceHit;
}

interface ScopedReferenceResult {
  readonly status: 'completed' | 'notApplicable' | 'cancelled';
  readonly candidates?: readonly MappedReference[];
  readonly warnings?: readonly string[];
}

interface DiagnosticEntry {
  readonly rawUri: unknown;
  readonly uri: { readonly scheme: string; readonly fsPath: string };
  readonly diagnostics: readonly unknown[];
}

type ReferenceStatus =
  | 'completed'
  | 'unavailable'
  | 'notReady'
  | 'cancelled'
  | 'timedOut'
  | 'failed'
  | 'positionOutOfRange';

export interface ReferencesDiagnosticsProviderHost extends VscodeProviderHost {
  createPosition(line: number, character: number): VscodePosition;
  findFiles(
    rootAbsolutePath: string,
    includePattern: string,
    maximumResults: number,
  ): PromiseLike<readonly unknown[]>;
  getDiagnostics(resource?: unknown): unknown;
  getOpenDocuments(): readonly TextDocument[];
  openProviderDocument(uri: unknown): PromiseLike<TextDocument>;
  readProviderText(uri: unknown): PromiseLike<string>;
}

const SCOPED_REFERENCE_MAX_FILES = 1_000;
const SCOPED_REFERENCE_MAX_TEXT_CHARACTERS = 24_000_000;
const SCOPED_REFERENCE_MAX_OCCURRENCES = 200;
const SCOPED_REFERENCE_TOTAL_TIMEOUT_MS = 30_000;
const SCOPED_REFERENCE_CALL_TIMEOUT_MS = 2_000;
const cppSourceFile = /\.(?:c|cc|cpp|cxx|h|hh|hpp|hxx|inl|ipp)$/iu;
const asciiIdentifier = /^[A-Za-z_][A-Za-z0-9_]*$/u;
const globMagic = /[*?{}\[\]]/u;

export type ReferencesDiagnosticsBridgeHandler = (
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

const parseGlobList = (value: unknown): readonly string[] | undefined => {
  if (value === undefined) return undefined;
  if (!Array.isArray(value) || value.length === 0 || value.length > 20 ||
      value.some((item) => typeof item !== 'string' || item.length === 0)) {
    return undefined;
  }
  return Object.freeze([...value]) as readonly string[];
};

const parseReferenceParams = (value: unknown): ReferenceBridgeParams | undefined => {
  const record = asRecord(value);
  if (record === undefined ||
      !exactFields(record, [
        'file',
        'line',
        'column',
        'contextLines',
        'includeGlobs',
        'excludeGlobs',
        'resultStart',
        'resultEnd',
        'timeoutMs',
      ]) ||
      typeof record.file !== 'string' || record.file.length === 0 ||
      !Number.isSafeInteger(record.line) || (record.line as number) < 1 ||
      !Number.isSafeInteger(record.column) || (record.column as number) < 1 ||
      !Number.isSafeInteger(record.contextLines) || (record.contextLines as number) < 0 ||
      (record.contextLines as number) > 5) {
    return undefined;
  }
  if (record.timeoutMs !== undefined && (
    !Number.isSafeInteger(record.timeoutMs) || (record.timeoutMs as number) < 1_000 ||
    (record.timeoutMs as number) > 90_000
  )) {
    return undefined;
  }
  const includeGlobs = parseGlobList(record.includeGlobs);
  const excludeGlobs = parseGlobList(record.excludeGlobs);
  if ((record.includeGlobs !== undefined && includeGlobs === undefined) ||
      (record.excludeGlobs !== undefined && excludeGlobs === undefined)) {
    return undefined;
  }
  const hasResultStart = record.resultStart !== undefined;
  const hasResultEnd = record.resultEnd !== undefined;
  if (hasResultStart !== hasResultEnd ||
      (hasResultStart && (
        !Number.isSafeInteger(record.resultStart) || (record.resultStart as number) < 1 ||
        !Number.isSafeInteger(record.resultEnd) || (record.resultEnd as number) < (record.resultStart as number) ||
        (record.resultEnd as number) - (record.resultStart as number) + 1 > 100
      ))) {
    return undefined;
  }
  return {
    file: record.file,
    line: record.line as number,
    column: record.column as number,
    contextLines: record.contextLines as number,
    ...(includeGlobs === undefined ? {} : { includeGlobs }),
    ...(excludeGlobs === undefined ? {} : { excludeGlobs }),
    ...(hasResultStart
      ? { resultStart: record.resultStart as number, resultEnd: record.resultEnd as number }
      : {}),
    ...(record.timeoutMs === undefined ? {} : { timeoutMs: record.timeoutMs as number }),
  };
};

const parseDiagnosticsParams = (value: unknown): DiagnosticsBridgeParams | undefined => {
  const record = asRecord(value);
  if (record === undefined ||
      !exactFields(record, ['scope', 'files', 'includeRelatedInformation']) ||
      (record.scope !== 'files' && record.scope !== 'modifiedFiles' && record.scope !== 'workspace') ||
      typeof record.includeRelatedInformation !== 'boolean') {
    return undefined;
  }
  let files: readonly string[] | undefined;
  if (record.files !== undefined) {
    if (!Array.isArray(record.files) || record.files.length === 0 || record.files.length > 200 ||
        new Set(record.files).size !== record.files.length ||
        record.files.some((file) => typeof file !== 'string' || file.length === 0)) {
      return undefined;
    }
    files = Object.freeze([...record.files]) as readonly string[];
  }
  if ((record.scope === 'files') !== (files !== undefined)) return undefined;
  return {
    scope: record.scope,
    includeRelatedInformation: record.includeRelatedInformation,
    ...(files === undefined ? {} : { files }),
  };
};

const normalizedText = (value: string): string | undefined => {
  const normalized = value.replaceAll('\r\n', '\n').replaceAll('\r', '\n').trim();
  return normalized.length === 0 ? undefined : normalized;
};

const compareTextOrdinal = (left: string, right: string): number =>
  left < right ? -1 : left > right ? 1 : 0;

const documentLines = (document: TextDocument): readonly string[] =>
  Object.freeze(document.getText().replaceAll('\r\n', '\n').replaceAll('\r', '\n').split('\n'));

const providerPosition = (
  host: ReferencesDiagnosticsProviderHost,
  input: ReferenceBridgeParams,
  document: TextDocument,
): unknown => {
  const line = input.line - 1;
  const character = input.column - 1;
  const lines = documentLines(document);
  if (line >= lines.length || character > (lines[line]?.length ?? -1)) {
    throw new RangeError('Reference position is outside the document.');
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
  const rawUri = record?.uri;
  const uri = asRecord(rawUri);
  const point = pointFromRange(record?.range);
  if (uri === undefined || typeof uri.scheme !== 'string' || typeof uri.fsPath !== 'string' ||
      point === undefined) {
    return undefined;
  }
  return { rawUri, uri: { scheme: uri.scheme, fsPath: uri.fsPath }, point };
};

const snippetForReference = async (
  host: ReferencesDiagnosticsProviderHost,
  location: ProviderLocation,
  contextLines: number,
): Promise<string | undefined> => {
  if (contextLines === 0) return undefined;
  const document = await host.openProviderDocument(location.rawUri);
  return contextSnippetForLine(document.getText(), location.point.line + 1, contextLines);
};

const referenceAdapter = (
  host: ReferencesDiagnosticsProviderHost,
): ProviderCommandAdapter<ReferenceBridgeParams, readonly unknown[]> => ({
  command: 'vscode.executeReferenceProvider',
  requiresDocument: true,
  buildArguments: (input, document) => {
    if (document === undefined) throw new RangeError('Document activation invariant failed.');
    return [document.uri, providerPosition(host, input, document)];
  },
  classifyResult: classifyArrayProviderResult,
});

const invocationStatus = <T>(result: ProviderInvocationResult<T>): ReferenceStatus =>
  result.status === 'failed' && result.reason === 'providerArgumentsInvalid'
    ? 'positionOutOfRange'
    : result.status;

const providerRange = (value: unknown): Range | undefined => {
  const record = asRecord(value);
  const start = asRecord(record?.start);
  const end = asRecord(record?.end);
  if (start === undefined || end === undefined ||
      !Number.isSafeInteger(start.line) || (start.line as number) < 0 ||
      (start.line as number) >= Number.MAX_SAFE_INTEGER ||
      !Number.isSafeInteger(start.character) || (start.character as number) < 0 ||
      (start.character as number) >= Number.MAX_SAFE_INTEGER ||
      !Number.isSafeInteger(end.line) || (end.line as number) < 0 ||
      (end.line as number) >= Number.MAX_SAFE_INTEGER ||
      !Number.isSafeInteger(end.character) || (end.character as number) < 0 ||
      (end.character as number) >= Number.MAX_SAFE_INTEGER ||
      (end.line as number) < (start.line as number) ||
      ((end.line as number) === (start.line as number) &&
       (end.character as number) < (start.character as number))) {
    return undefined;
  }
  return Object.freeze({
    startLine: (start.line as number) + 1,
    startColumn: (start.character as number) + 1,
    endLine: (end.line as number) + 1,
    endColumn: (end.character as number) + 1,
  });
};

const uriRecord = (value: unknown): { readonly scheme: string; readonly fsPath: string } | undefined => {
  const record = asRecord(value);
  return record !== undefined && typeof record.scheme === 'string' && typeof record.fsPath === 'string'
    ? { scheme: record.scheme, fsPath: record.fsPath }
    : undefined;
};

const boundedSearchPatterns = (
  context: WorkspacePathContext,
  includeGlobs: readonly string[] | undefined,
): readonly { readonly rootAbsolutePath: string; readonly pattern: string }[] | undefined => {
  if (includeGlobs === undefined) return undefined;
  const patterns = new Map<string, { readonly rootAbsolutePath: string; readonly pattern: string }>();
  const aliases = new Set(context.roots.map((root) => root.alias as string));
  for (const root of context.roots) {
    for (const includeGlob of includeGlobs) {
      let pattern = includeGlob.replaceAll('\\', '/');
      if (context.roots.length > 1) {
        const slash = pattern.indexOf('/');
        const first = slash < 0 ? pattern : pattern.slice(0, slash);
        if (aliases.has(first)) {
          if (first !== root.alias) continue;
          pattern = slash < 0 ? '' : pattern.slice(slash + 1);
        }
      }
      const firstMagic = pattern.search(globMagic);
      const staticPrefix = (firstMagic < 0 ? pattern : pattern.slice(0, firstMagic))
        .replace(/\/+$/u, '');
      if (pattern.length === 0 || staticPrefix.length === 0 || staticPrefix === '.') {
        return undefined;
      }
      const key = `${root.lexicalComparisonKey}\0${pattern}`;
      patterns.set(key, Object.freeze({
        rootAbsolutePath: root.lexicalAbsolutePath,
        pattern,
      }));
    }
  }
  return patterns.size === 0 ? undefined : Object.freeze([...patterns.values()]);
};

const symbolAtPosition = (
  host: ReferencesDiagnosticsProviderHost,
  document: TextDocument,
  line: number,
  column: number,
): string | undefined => {
  const requested = host.createPosition(line - 1, column - 1);
  const validated = document.validatePosition(requested);
  if (validated.line !== requested.line || validated.character !== requested.character) return undefined;
  const text = document.getText();
  let offset = document.offsetAt(validated);
  const isIdentifierCharacter = (value: string | undefined): boolean =>
    value !== undefined && /^[A-Za-z0-9_]$/u.test(value);
  if (!isIdentifierCharacter(text[offset]) && offset > 0 && isIdentifierCharacter(text[offset - 1])) {
    offset -= 1;
  }
  if (!isIdentifierCharacter(text[offset])) return undefined;
  let start = offset;
  let end = offset + 1;
  while (start > 0 && isIdentifierCharacter(text[start - 1])) start -= 1;
  while (end < text.length && isIdentifierCharacter(text[end])) end += 1;
  const candidate = text.slice(start, end);
  return asciiIdentifier.test(candidate) ? candidate : undefined;
};

const identifierOccurrences = (text: string, identifier: string): readonly number[] => {
  const offsets: number[] = [];
  const identifierCharacter = (value: string | undefined): boolean =>
    value !== undefined && /^[A-Za-z0-9_]$/u.test(value);
  let from = 0;
  while (from <= text.length - identifier.length) {
    const index = text.indexOf(identifier, from);
    if (index < 0) break;
    const before = index === 0 ? undefined : text[index - 1];
    const after = text[index + identifier.length];
    if (!identifierCharacter(before) && !identifierCharacter(after)) offsets.push(index);
    from = index + identifier.length;
  }
  return Object.freeze(offsets);
};

const pointAtTextOffset = (text: string, offset: number): ProviderPoint => {
  let line = 0;
  let lineStart = 0;
  for (let index = 0; index < offset; index += 1) {
    if (text.charCodeAt(index) === 10) {
      line += 1;
      lineStart = index + 1;
    }
  }
  return Object.freeze({ line, character: offset - lineStart });
};

const diagnosticSeverity = (value: unknown): DiagnosticSeverity | undefined => {
  switch (value) {
    case 0: return 'error';
    case 1: return 'warning';
    case 2: return 'information';
    case 3: return 'hint';
    default: return undefined;
  }
};

const diagnosticCode = (value: unknown): string | number | undefined => {
  const raw = asRecord(value)?.value ?? value;
  if (typeof raw === 'string') return normalizedText(raw);
  return Number.isSafeInteger(raw) ? raw as number : undefined;
};

const diagnosticTags = (value: unknown): readonly ('unnecessary' | 'deprecated')[] | undefined => {
  if (!Array.isArray(value)) return undefined;
  const tags: Array<'unnecessary' | 'deprecated'> = [];
  if (value.includes(1)) tags.push('unnecessary');
  if (value.includes(2)) tags.push('deprecated');
  return tags.length === 0 ? undefined : Object.freeze(tags);
};

const logicalFileForUri = async (
  context: WorkspacePathContext,
  uri: { readonly scheme: string; readonly fsPath: string },
  pathAccess: WorkspacePathAccess,
): Promise<string | undefined> => {
  try {
    return (await logicalPathFromProviderLocation(context, {
      uriScheme: uri.scheme,
      lexicalAbsolutePath: uri.fsPath,
    }, pathAccess)).logicalPath;
  } catch {
    return undefined;
  }
};

const diagnosticEntry = (value: unknown): DiagnosticEntry | undefined => {
  if (!Array.isArray(value) || value.length !== 2 || !Array.isArray(value[1])) return undefined;
  const uri = uriRecord(value[0]);
  return uri === undefined ? undefined : { rawUri: value[0], uri, diagnostics: value[1] };
};

const mapRelatedInformation = async (
  context: WorkspacePathContext,
  value: unknown,
  pathAccess: WorkspacePathAccess,
  warnings: Set<string>,
): Promise<DiagnosticRelatedInformation | undefined> => {
  const record = asRecord(value);
  const location = asRecord(record?.location);
  const uri = uriRecord(location?.uri);
  const range = providerRange(location?.range);
  const message = typeof record?.message === 'string' ? normalizedText(record.message) : undefined;
  if (uri === undefined || range === undefined || message === undefined) {
    warnings.add('diagnostic_related_information_invalid');
    return undefined;
  }
  const file = await logicalFileForUri(context, uri, pathAccess);
  if (file === undefined) {
    warnings.add('diagnostic_related_information_outside_workspace');
    return undefined;
  }
  return Object.freeze({ file, range, message });
};

const compareRelated = (
  left: DiagnosticRelatedInformation,
  right: DiagnosticRelatedInformation,
): number => compareTextOrdinal(left.file, right.file) ||
  left.range.startLine - right.range.startLine ||
  left.range.startColumn - right.range.startColumn ||
  left.range.endLine - right.range.endLine ||
  left.range.endColumn - right.range.endColumn ||
  compareTextOrdinal(left.message, right.message);

const mapDiagnostic = async (
  context: WorkspacePathContext,
  file: string,
  value: unknown,
  includeRelatedInformation: boolean,
  pathAccess: WorkspacePathAccess,
  warnings: Set<string>,
): Promise<Diagnostic | undefined> => {
  const record = asRecord(value);
  const range = providerRange(record?.range);
  const severity = diagnosticSeverity(record?.severity);
  const message = typeof record?.message === 'string' ? normalizedText(record.message) : undefined;
  if (record === undefined || range === undefined || severity === undefined || message === undefined) {
    warnings.add('diagnostic_candidate_invalid');
    return undefined;
  }
  const code = diagnosticCode(record.code);
  const source = typeof record.source === 'string' ? normalizedText(record.source) : undefined;
  const tags = diagnosticTags(record.tags);
  let relatedInformation: readonly DiagnosticRelatedInformation[] | undefined;
  if (includeRelatedInformation && Array.isArray(record.relatedInformation)) {
    const mapped = await Promise.all(record.relatedInformation.map((entry) =>
      mapRelatedInformation(context, entry, pathAccess, warnings)));
    const seen = new Set<string>();
    const filtered = mapped.filter((entry): entry is DiagnosticRelatedInformation => {
      if (entry === undefined) return false;
      const key = JSON.stringify(entry);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }).sort(compareRelated);
    if (filtered.length > 0) relatedInformation = Object.freeze(filtered);
  }
  return Object.freeze({
    file,
    range,
    severity,
    message,
    ...(code === undefined ? {} : { code }),
    ...(source === undefined ? {} : { source }),
    ...(tags === undefined ? {} : { tags }),
    ...(relatedInformation === undefined ? {} : { relatedInformation }),
  });
};

export class ReferencesDiagnosticsProviderBridge {
  readonly #host: ReferencesDiagnosticsProviderHost;
  readonly #identity: SymbolIdentityResolver;
  readonly #pathAccess: WorkspacePathAccess;
  readonly #runtime: ProviderRuntime;
  readonly #scopedReferenceCallTimeoutMs: number;

  constructor(
    host: ReferencesDiagnosticsProviderHost,
    pathAccess: WorkspacePathAccess = systemWorkspacePathAccess,
    defaultTimeoutMs?: number,
  ) {
    this.#host = host;
    this.#pathAccess = pathAccess;
    this.#scopedReferenceCallTimeoutMs = Math.min(
      SCOPED_REFERENCE_CALL_TIMEOUT_MS,
      defaultTimeoutMs ?? SCOPED_REFERENCE_CALL_TIMEOUT_MS,
    );
    this.#runtime = new ProviderRuntime({
      host,
      pathAccess,
      ...(defaultTimeoutMs === undefined ? {} : { defaultTimeoutMs }),
    });
    this.#identity = new SymbolIdentityResolver(host, {
      pathAccess,
      ...(defaultTimeoutMs === undefined ? {} : { defaultTimeoutMs }),
    });
  }

  async #scopedCppReferences(
    context: WorkspacePathContext,
    input: ReferenceBridgeParams,
    signal: AbortSignal,
  ): Promise<ScopedReferenceResult> {
    const patterns = boundedSearchPatterns(context, input.includeGlobs);
    if (patterns === undefined) return Object.freeze({ status: 'notApplicable' });
    let source: TextDocument;
    try {
      const resolved = await resolveLogicalPath(context, input.file, this.#pathAccess);
      source = await this.#host.openTextDocument(resolved.lexicalAbsolutePath);
    } catch {
      return Object.freeze({ status: 'notApplicable' });
    }
    if (source.languageId !== 'cpp' && source.languageId !== 'c' &&
        !cppSourceFile.test(input.file)) {
      return Object.freeze({ status: 'notApplicable' });
    }
    const identifier = symbolAtPosition(this.#host, source, input.line, input.column);
    if (identifier === undefined) return Object.freeze({ status: 'notApplicable' });

    const deadline = Date.now() + SCOPED_REFERENCE_TOTAL_TIMEOUT_MS;
    const callTimeout = (): number | undefined => {
      const remaining = deadline - Date.now();
      return remaining < 1 ? undefined : Math.min(this.#scopedReferenceCallTimeoutMs, remaining);
    };
    const targetTimeout = callTimeout();
    if (targetTimeout === undefined) return Object.freeze({ status: 'notApplicable' });
    const target = await this.#identity.resolveTarget(
      context,
      { file: input.file, line: input.line, column: input.column },
      signal,
      targetTimeout,
    );
    if (target.status === 'cancelled') return Object.freeze({ status: 'cancelled' });
    if (target.status !== 'resolved') return Object.freeze({ status: 'notApplicable' });
    const targetAnchors = new Set(target.anchors);

    const files = new Map<string, { readonly file: string; readonly rawUri: unknown }>();
    for (const pattern of patterns) {
      if (signal.aborted) return Object.freeze({ status: 'cancelled' });
      let found: readonly unknown[];
      try {
        found = await this.#host.findFiles(
          pattern.rootAbsolutePath,
          pattern.pattern,
          SCOPED_REFERENCE_MAX_FILES + 1,
        );
      } catch {
        return Object.freeze({ status: 'notApplicable' });
      }
      if (found.length > SCOPED_REFERENCE_MAX_FILES) {
        return Object.freeze({ status: 'notApplicable' });
      }
      for (const rawUri of found) {
        const uri = uriRecord(rawUri);
        if (uri === undefined) return Object.freeze({ status: 'notApplicable' });
        let file: string;
        try {
          file = (await logicalPathFromProviderLocation(context, {
            uriScheme: uri.scheme,
            lexicalAbsolutePath: uri.fsPath,
          }, this.#pathAccess)).logicalPath;
        } catch {
          return Object.freeze({ status: 'notApplicable' });
        }
        if (!cppSourceFile.test(file) || !matchesLogicalGlobs(file, input)) continue;
        const key = context.platform === 'win32' ? file.toLowerCase() : file;
        files.set(key, Object.freeze({ file, rawUri }));
        if (files.size > SCOPED_REFERENCE_MAX_FILES) {
          return Object.freeze({ status: 'notApplicable' });
        }
      }
    }

    let textCharacters = 0;
    const occurrences: MappedReference[] = [];
    for (const entry of files.values()) {
      if (signal.aborted) return Object.freeze({ status: 'cancelled' });
      let text: string;
      try {
        text = await this.#host.readProviderText(entry.rawUri);
      } catch {
        return Object.freeze({ status: 'notApplicable' });
      }
      textCharacters += text.length;
      if (textCharacters > SCOPED_REFERENCE_MAX_TEXT_CHARACTERS) {
        return Object.freeze({ status: 'notApplicable' });
      }
      const uri = uriRecord(entry.rawUri);
      if (uri === undefined) return Object.freeze({ status: 'notApplicable' });
      for (const offset of identifierOccurrences(text, identifier)) {
        const position = pointAtTextOffset(text, offset);
        occurrences.push(Object.freeze({
          location: Object.freeze({
            rawUri: entry.rawUri,
            uri,
            point: Object.freeze({ line: position.line, character: position.character }),
          }),
          hit: Object.freeze({
            file: entry.file,
            line: position.line + 1,
            column: position.character + 1,
          }),
        }));
        if (occurrences.length > SCOPED_REFERENCE_MAX_OCCURRENCES) {
          return Object.freeze({ status: 'notApplicable' });
        }
      }
    }

    const verified: MappedReference[] = [];
    for (const occurrence of occurrences) {
      const timeoutMs = callTimeout();
      if (timeoutMs === undefined) return Object.freeze({ status: 'notApplicable' });
      const result = await this.#identity.verifyCandidate(
        context,
        {
          file: occurrence.hit.file,
          line: occurrence.hit.line,
          column: occurrence.hit.column,
        },
        targetAnchors,
        signal,
        timeoutMs,
      );
      if (result.status === 'cancelled') return Object.freeze({ status: 'cancelled' });
      if (result.status === 'mismatched' || result.status === 'unresolved') continue;
      if (result.status !== 'verified') return Object.freeze({ status: 'notApplicable' });
      verified.push(occurrence);
    }
    return Object.freeze({
      status: 'completed',
      candidates: Object.freeze(verified),
      warnings: Object.freeze(['references_scoped_identity_fallback']),
    });
  }

  async #references(
    context: WorkspacePathContext,
    input: ReferenceBridgeParams,
    signal: AbortSignal,
  ): Promise<JsonValue> {
    const warnings = new Set<string>();
    // An explicit timeout is an instruction to give the semantic provider the
    // whole requested budget. Do not spend up to 30 seconds on the optional
    // scoped fallback first and accidentally turn a 90-second request into a
    // 120-second request.
    const scoped = input.timeoutMs === undefined
      ? await this.#scopedCppReferences(context, input, signal)
      : Object.freeze({ status: 'notApplicable' as const });
    if (scoped.status === 'cancelled') return { status: 'cancelled' };
    let mappedCandidates: readonly MappedReference[];
    if (scoped.status === 'completed') {
      mappedCandidates = scoped.candidates ?? [];
      for (const warning of scoped.warnings ?? []) warnings.add(warning);
    } else {
      const invocation = await this.#runtime.invoke(
        context,
        referenceAdapter(this.#host),
        input,
        {
          logicalFile: input.file,
          signal,
          ...(input.timeoutMs === undefined ? {} : { timeoutMs: input.timeoutMs }),
        },
      );
      if (invocation.status !== 'completed') return { status: invocationStatus(invocation) };
      const mapped = await Promise.all(invocation.value.map(async (raw): Promise<MappedReference | undefined> => {
        const location = providerLocation(raw);
        if (location === undefined) {
          warnings.add('reference_candidate_invalid');
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
            ? 'reference_candidate_outside_workspace'
            : 'reference_candidate_invalid');
          return undefined;
        }
        return Object.freeze({
          location,
          hit: Object.freeze({
            file,
            line: location.point.line + 1,
            column: location.point.character + 1,
          }),
        });
      }));
      mappedCandidates = mapped.filter(
        (candidate): candidate is MappedReference => candidate !== undefined,
      );
    }
    const bounded = input.resultStart !== undefined && input.resultEnd !== undefined;
    const collection = bounded
      ? buildCandidateCollection<MappedReference, MappedReference>(mappedCandidates, {
          normalize: (candidate) => candidate,
          logicalPath: (candidate) => candidate.hit.file,
          ...(input.includeGlobs === undefined ? {} : { includeGlobs: input.includeGlobs }),
          ...(input.excludeGlobs === undefined ? {} : { excludeGlobs: input.excludeGlobs }),
          dedupeKey: (candidate) => JSON.stringify([
            candidate.hit.file,
            candidate.hit.line,
            candidate.hit.column,
          ]),
          compare: (left, right) =>
            compareTextOrdinal(left.hit.file, right.hit.file) ||
            left.hit.line - right.hit.line ||
            left.hit.column - right.hit.column,
          resultStart: input.resultStart as number,
          resultEnd: input.resultEnd as number,
        })
      : {
          results: Object.freeze(mappedCandidates),
          available: mappedCandidates.length,
        };
    const candidates = await Promise.all(collection.results.map(async (candidate) => {
      let snippet: string | undefined;
      try {
        snippet = await snippetForReference(this.#host, candidate.location, input.contextLines);
      } catch {
        warnings.add('reference_snippet_unavailable');
      }
      return Object.freeze({
        ...candidate.hit,
        ...(snippet === undefined || snippet.length === 0 ? {} : { snippet }),
      }) satisfies ReferenceHit;
    }));
    return {
      status: 'completed',
      candidates: Object.freeze(candidates),
      ...(bounded ? { available: collection.available } : {}),
      ...(warnings.size === 0
        ? {}
        : { warnings: Object.freeze([...warnings].sort(compareTextOrdinal)) }),
    } as unknown as JsonValue;
  }

  async #diagnosticEntries(
    context: WorkspacePathContext,
    input: DiagnosticsBridgeParams,
  ): Promise<readonly DiagnosticEntry[]> {
    if (input.scope === 'files') {
      const entries = await Promise.all((input.files as readonly string[]).map(async (file) => {
        const resolved = await resolveLogicalPath(context, file, this.#pathAccess);
        const document = await this.#host.openTextDocument(resolved.lexicalAbsolutePath);
        const uri = uriRecord(document.uri);
        const diagnostics = this.#host.getDiagnostics(document.uri);
        if (uri === undefined || !Array.isArray(diagnostics)) {
          throw new TypeError('Diagnostics API returned an invalid file result.');
        }
        return { rawUri: document.uri, uri, diagnostics };
      }));
      return Object.freeze(entries);
    }
    if (input.scope === 'modifiedFiles') {
      const entries: DiagnosticEntry[] = [];
      for (const document of this.#host.getOpenDocuments()) {
        if (!document.isDirty) continue;
        const uri = uriRecord(document.uri);
        if (uri === undefined || await logicalFileForUri(context, uri, this.#pathAccess) === undefined) continue;
        const diagnostics = this.#host.getDiagnostics(document.uri);
        if (Array.isArray(diagnostics)) entries.push({ rawUri: document.uri, uri, diagnostics });
      }
      return Object.freeze(entries);
    }
    const raw = this.#host.getDiagnostics();
    if (!Array.isArray(raw)) throw new TypeError('Diagnostics API returned an invalid workspace result.');
    return Object.freeze(raw.map(diagnosticEntry).filter(
      (entry): entry is DiagnosticEntry => entry !== undefined,
    ));
  }

  async #diagnostics(
    context: WorkspacePathContext,
    input: DiagnosticsBridgeParams,
  ): Promise<JsonValue> {
    try {
      const warnings = new Set<string>();
      const entries = await this.#diagnosticEntries(context, input);
      const candidates: Diagnostic[] = [];
      for (const entry of entries) {
        const file = await logicalFileForUri(context, entry.uri, this.#pathAccess);
        if (file === undefined) continue;
        const mapped = await Promise.all(entry.diagnostics.map((diagnostic) =>
          mapDiagnostic(
            context,
            file,
            diagnostic,
            input.includeRelatedInformation,
            this.#pathAccess,
            warnings,
          )));
        candidates.push(...mapped.filter((candidate): candidate is Diagnostic => candidate !== undefined));
      }
      return {
        status: 'completed',
        candidates: Object.freeze(candidates),
        ...(warnings.size === 0
          ? {}
          : { warnings: Object.freeze([...warnings].sort(compareTextOrdinal)) }),
      } as unknown as JsonValue;
    } catch {
      return { status: 'failed' };
    }
  }

  handle: ReferencesDiagnosticsBridgeHandler = async (context, request, signal) => {
    if (request.method === REFERENCES_BRIDGE_METHOD) {
      const params = parseReferenceParams(request.params);
      return params === undefined ? { status: 'failed' } : this.#references(context, params, signal);
    }
    if (request.method === DIAGNOSTICS_BRIDGE_METHOD) {
      const params = parseDiagnosticsParams(request.params);
      return params === undefined ? { status: 'failed' } : this.#diagnostics(context, params);
    }
    return undefined;
  };
}

export const createReferencesDiagnosticsBridgeHandler = (
  host: ReferencesDiagnosticsProviderHost,
  pathAccess: WorkspacePathAccess = systemWorkspacePathAccess,
  defaultTimeoutMs?: number,
): ReferencesDiagnosticsBridgeHandler =>
  new ReferencesDiagnosticsProviderBridge(host, pathAccess, defaultTimeoutMs).handle;
