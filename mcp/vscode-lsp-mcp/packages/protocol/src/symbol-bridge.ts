import {
  SYMBOL_KINDS,
  type DocumentSymbol,
  type ProviderObservation,
  type Range,
  type SymbolHit,
  type SymbolKind,
} from './dto.js';

export const SYMBOL_BRIDGE_METHODS = Object.freeze({
  workspace: 'symbols.workspace',
  document: 'symbols.document',
} as const);

export type SymbolBridgeMethod =
  (typeof SYMBOL_BRIDGE_METHODS)[keyof typeof SYMBOL_BRIDGE_METHODS];

export type SymbolBridgeResponse<T> =
  | {
      readonly status: 'completed';
      readonly candidates: readonly T[];
      readonly warnings?: readonly string[];
      readonly provider?: ProviderObservation;
    }
  | {
      readonly status: 'unavailable' | 'notReady' | 'cancelled' | 'timedOut' | 'failed';
      readonly provider?: ProviderObservation;
    };

const symbolKindSet = new Set<string>(SYMBOL_KINDS);

const asRecord = (value: unknown, label: string): Record<string, unknown> => {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object.`);
  }
  return value as Record<string, unknown>;
};

const assertExactFields = (
  value: Record<string, unknown>,
  allowed: readonly string[],
  label: string,
): void => {
  const allowedSet = new Set(allowed);
  if (Object.keys(value).some((key) => !allowedSet.has(key))) {
    throw new TypeError(`${label} contains an unknown field.`);
  }
};

const requiredString = (
  value: Record<string, unknown>,
  key: string,
  label: string,
): string => {
  const field = value[key];
  if (typeof field !== 'string' || field.length === 0) {
    throw new TypeError(`${label}.${key} must be a non-empty string.`);
  }
  return field;
};

const optionalString = (
  value: Record<string, unknown>,
  key: string,
  label: string,
): string | undefined => value[key] === undefined
  ? undefined
  : requiredString(value, key, label);

const position = (value: Record<string, unknown>, key: string, label: string): number => {
  const field = value[key];
  if (!Number.isSafeInteger(field) || (field as number) < 1) {
    throw new TypeError(`${label}.${key} must be a positive safe integer.`);
  }
  return field as number;
};

const nonNegativeInteger = (value: unknown, label: string): number => {
  if (!Number.isSafeInteger(value) || (value as number) < 0) {
    throw new TypeError(`${label} must be a non-negative safe integer.`);
  }
  return value as number;
};

const parseProviderObservation = (
  value: unknown,
  responseStatus: SymbolBridgeResponse<unknown>['status'],
): ProviderObservation | undefined => {
  if (value === undefined) return undefined;
  const record = asRecord(value, 'symbol bridge provider observation');
  assertExactFields(record, ['status', 'elapsedMs', 'attempts'], 'symbol bridge provider observation');
  if (record.status !== responseStatus) {
    throw new TypeError('Symbol bridge provider observation status must match the response status.');
  }
  return Object.freeze({
    status: responseStatus,
    elapsedMs: nonNegativeInteger(record.elapsedMs, 'symbol bridge provider observation.elapsedMs'),
    attempts: nonNegativeInteger(record.attempts, 'symbol bridge provider observation.attempts'),
  });
};

const parseRange = (value: unknown, label: string): Range | undefined => {
  if (value === undefined) return undefined;
  const record = asRecord(value, label);
  assertExactFields(record, ['startLine', 'startColumn', 'endLine', 'endColumn'], label);
  const parsed = Object.freeze({
    startLine: position(record, 'startLine', label),
    startColumn: position(record, 'startColumn', label),
    endLine: position(record, 'endLine', label),
    endColumn: position(record, 'endColumn', label),
  });
  if (
    parsed.endLine < parsed.startLine ||
    (parsed.endLine === parsed.startLine && parsed.endColumn < parsed.startColumn)
  ) {
    throw new TypeError(`${label} must be ordered.`);
  }
  return parsed;
};

const symbolKind = (value: Record<string, unknown>, label: string): SymbolKind => {
  const field = value.kind;
  if (typeof field !== 'string' || !symbolKindSet.has(field)) {
    throw new TypeError(`${label}.kind is invalid.`);
  }
  return field as SymbolKind;
};

const logicalPath = (value: string, label: string): string => {
  if (
    value.startsWith('/') ||
    value.includes('\\') ||
    value.includes('\u0000') ||
    /^[A-Za-z][A-Za-z0-9+.-]*:/u.test(value) ||
    value.split('/').some((segment) => segment === '' || segment === '.' || segment === '..')
  ) {
    throw new TypeError(`${label} must be a normalized logical path.`);
  }
  return value;
};

const parseWorkspaceCandidate = (value: unknown, index: number): SymbolHit => {
  const label = `workspace symbol candidate ${index}`;
  const record = asRecord(value, label);
  assertExactFields(
    record,
    ['name', 'kind', 'file', 'line', 'column', 'container', 'snippet'],
    label,
  );
  const container = optionalString(record, 'container', label);
  const snippet = optionalString(record, 'snippet', label);
  return Object.freeze({
    name: requiredString(record, 'name', label),
    kind: symbolKind(record, label),
    file: logicalPath(requiredString(record, 'file', label), `${label}.file`),
    line: position(record, 'line', label),
    column: position(record, 'column', label),
    ...(container === undefined ? {} : { container }),
    ...(snippet === undefined ? {} : { snippet }),
  });
};

const parseDocumentCandidate = (value: unknown, index: number): DocumentSymbol => {
  const label = `document symbol candidate ${index}`;
  const record = asRecord(value, label);
  assertExactFields(record, ['kind', 'path', 'line', 'column', 'range', 'snippet'], label);
  const rawPath = record.path;
  if (!Array.isArray(rawPath) || rawPath.length === 0) {
    throw new TypeError(`${label}.path must be a non-empty array.`);
  }
  const path = Object.freeze(rawPath.map((entry, pathIndex) => {
    if (typeof entry !== 'string' || entry.length === 0) {
      throw new TypeError(`${label}.path[${pathIndex}] must be a non-empty string.`);
    }
    return entry;
  }));
  const snippet = optionalString(record, 'snippet', label);
  const range = parseRange(record.range, `${label}.range`);
  return Object.freeze({
    kind: symbolKind(record, label),
    path,
    line: position(record, 'line', label),
    column: position(record, 'column', label),
    ...(range === undefined ? {} : { range }),
    ...(snippet === undefined ? {} : { snippet }),
  });
};

const parseWarnings = (value: unknown): readonly string[] | undefined => {
  if (value === undefined) return undefined;
  if (!Array.isArray(value) || value.length === 0 || value.length > 100) {
    throw new TypeError('Symbol bridge warnings must be a non-empty bounded array.');
  }
  return Object.freeze(value.map((entry) => {
    if (typeof entry !== 'string' || entry.length === 0 || entry.length > 512) {
      throw new TypeError('Symbol bridge warnings must contain bounded strings.');
    }
    return entry;
  }));
};

const terminalStatuses = new Set([
  'unavailable',
  'notReady',
  'cancelled',
  'timedOut',
  'failed',
]);

const parseResponse = <T>(
  value: unknown,
  parseCandidate: (candidate: unknown, index: number) => T,
): SymbolBridgeResponse<T> => {
  const record = asRecord(value, 'symbol bridge response');
  const status = record.status;
  if (status === 'completed') {
    assertExactFields(record, ['status', 'candidates', 'warnings', 'provider'], 'symbol bridge response');
    if (!Array.isArray(record.candidates)) {
      throw new TypeError('Completed symbol bridge response must contain candidates.');
    }
    const warnings = parseWarnings(record.warnings);
    const provider = parseProviderObservation(record.provider, status);
    return Object.freeze({
      status,
      candidates: Object.freeze(record.candidates.map(parseCandidate)),
      ...(warnings === undefined ? {} : { warnings }),
      ...(provider === undefined ? {} : { provider }),
    });
  }
  if (typeof status !== 'string' || !terminalStatuses.has(status)) {
    throw new TypeError('Symbol bridge response status is invalid.');
  }
  assertExactFields(record, ['status', 'provider'], 'symbol bridge response');
  const provider = parseProviderObservation(record.provider, status as SymbolBridgeResponse<T>['status']);
  return Object.freeze({
    status,
    ...(provider === undefined ? {} : { provider }),
  }) as SymbolBridgeResponse<T>;
};

export const parseWorkspaceSymbolBridgeResponse = (
  value: unknown,
): SymbolBridgeResponse<SymbolHit> => parseResponse(value, parseWorkspaceCandidate);

export const parseDocumentSymbolBridgeResponse = (
  value: unknown,
): SymbolBridgeResponse<DocumentSymbol> => parseResponse(value, parseDocumentCandidate);
