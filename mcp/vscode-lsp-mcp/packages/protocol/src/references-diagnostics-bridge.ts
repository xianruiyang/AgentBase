import type {
  Diagnostic,
  DiagnosticRelatedInformation,
  DiagnosticSeverity,
  Range,
  ReferenceHit,
  SymbolCandidateVerification,
} from './dto.js';

export const REFERENCES_BRIDGE_METHOD = 'references.get' as const;
export const VERIFY_SYMBOL_CANDIDATES_BRIDGE_METHOD = 'references.verifyCandidates' as const;
export const DIAGNOSTICS_BRIDGE_METHOD = 'diagnostics.get' as const;

type ProviderTerminalStatus =
  | 'unavailable'
  | 'notReady'
  | 'cancelled'
  | 'timedOut'
  | 'failed'
  | 'positionOutOfRange';

export type ReferencesBridgeResponse =
  | {
      readonly status: 'completed';
      readonly candidates: readonly ReferenceHit[];
      readonly available?: number;
      readonly warnings?: readonly string[];
  }
  | { readonly status: ProviderTerminalStatus }
  | {
      readonly status: 'scopedIncomplete';
      readonly reason:
        | 'targetUnresolved'
        | 'scopeBudgetExceeded'
        | 'scopeInvalid'
        | 'scopeUnsupported'
        | 'candidateUnresolved'
        | 'providerUnavailable'
        | 'providerTimedOut'
        | 'providerFailed';
    };

export type VerifySymbolCandidatesBridgeResponse =
  | {
      readonly status: 'completed';
      readonly candidates: readonly SymbolCandidateVerification[];
    }
  | { readonly status: ProviderTerminalStatus };

export type DiagnosticsBridgeResponse =
  | {
      readonly status: 'completed';
      readonly candidates: readonly Diagnostic[];
      readonly warnings?: readonly string[];
    }
  | { readonly status: Exclude<ProviderTerminalStatus, 'positionOutOfRange'> };

const asRecord = (value: unknown, label: string): Record<string, unknown> => {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object.`);
  }
  return value as Record<string, unknown>;
};

const exactFields = (
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
  field: string,
  label: string,
): string => {
  const result = value[field];
  if (typeof result !== 'string' || result.length === 0) {
    throw new TypeError(`${label}.${field} must be a non-empty string.`);
  }
  return result;
};

const optionalString = (
  value: Record<string, unknown>,
  field: string,
  label: string,
): string | undefined => value[field] === undefined
  ? undefined
  : requiredString(value, field, label);

const positiveInteger = (
  value: Record<string, unknown>,
  field: string,
  label: string,
): number => {
  const result = value[field];
  if (!Number.isSafeInteger(result) || (result as number) < 1) {
    throw new TypeError(`${label}.${field} must be a positive safe integer.`);
  }
  return result as number;
};

const nonNegativeInteger = (
  value: Record<string, unknown>,
  field: string,
  label: string,
): number => {
  const result = value[field];
  if (!Number.isSafeInteger(result) || (result as number) < 0) {
    throw new TypeError(`${label}.${field} must be a non-negative safe integer.`);
  }
  return result as number;
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

const parseRange = (value: unknown, label: string): Range => {
  const record = asRecord(value, label);
  exactFields(record, ['startLine', 'startColumn', 'endLine', 'endColumn'], label);
  const range = Object.freeze({
    startLine: positiveInteger(record, 'startLine', label),
    startColumn: positiveInteger(record, 'startColumn', label),
    endLine: positiveInteger(record, 'endLine', label),
    endColumn: positiveInteger(record, 'endColumn', label),
  });
  if (range.endLine < range.startLine ||
      (range.endLine === range.startLine && range.endColumn < range.startColumn)) {
    throw new TypeError(`${label} must be ordered and end-exclusive.`);
  }
  return range;
};

const parseReference = (value: unknown, index: number): ReferenceHit => {
  const label = `reference candidate ${index}`;
  const record = asRecord(value, label);
  exactFields(record, ['file', 'line', 'column', 'snippet'], label);
  const snippet = optionalString(record, 'snippet', label);
  return Object.freeze({
    file: logicalPath(requiredString(record, 'file', label), `${label}.file`),
    line: positiveInteger(record, 'line', label),
    column: positiveInteger(record, 'column', label),
    ...(snippet === undefined ? {} : { snippet }),
  });
};

const candidateVerificationStatuses = new Set<SymbolCandidateVerification['status']>([
  'verified',
  'mismatched',
  'unresolved',
  'positionOutOfRange',
]);

const parseSymbolCandidateVerification = (
  value: unknown,
  index: number,
): SymbolCandidateVerification => {
  const label = `symbol candidate verification ${index}`;
  const record = asRecord(value, label);
  exactFields(record, ['file', 'line', 'column', 'status'], label);
  if (typeof record.status !== 'string' ||
      !candidateVerificationStatuses.has(record.status as SymbolCandidateVerification['status'])) {
    throw new TypeError(`${label}.status is invalid.`);
  }
  return Object.freeze({
    file: logicalPath(requiredString(record, 'file', label), `${label}.file`),
    line: positiveInteger(record, 'line', label),
    column: positiveInteger(record, 'column', label),
    status: record.status as SymbolCandidateVerification['status'],
  });
};

const diagnosticSeverities = new Set<DiagnosticSeverity>([
  'error',
  'warning',
  'information',
  'hint',
]);

const parseRelatedInformation = (
  value: unknown,
  index: number,
): DiagnosticRelatedInformation => {
  const label = `diagnostic related information ${index}`;
  const record = asRecord(value, label);
  exactFields(record, ['file', 'range', 'message'], label);
  return Object.freeze({
    file: logicalPath(requiredString(record, 'file', label), `${label}.file`),
    range: parseRange(record.range, `${label}.range`),
    message: requiredString(record, 'message', label),
  });
};

const parseDiagnostic = (value: unknown, index: number): Diagnostic => {
  const label = `diagnostic candidate ${index}`;
  const record = asRecord(value, label);
  exactFields(
    record,
    ['file', 'range', 'severity', 'message', 'code', 'source', 'tags', 'relatedInformation'],
    label,
  );
  if (typeof record.severity !== 'string' ||
      !diagnosticSeverities.has(record.severity as DiagnosticSeverity)) {
    throw new TypeError(`${label}.severity is invalid.`);
  }
  let code: string | number | undefined;
  if (record.code !== undefined) {
    if (typeof record.code === 'string' && record.code.length > 0) {
      code = record.code;
    } else if (Number.isSafeInteger(record.code)) {
      code = record.code as number;
    } else {
      throw new TypeError(`${label}.code must be a non-empty string or safe integer.`);
    }
  }
  let tags: readonly ('unnecessary' | 'deprecated')[] | undefined;
  if (record.tags !== undefined) {
    if (!Array.isArray(record.tags) || record.tags.length === 0 ||
        new Set(record.tags).size !== record.tags.length ||
        record.tags.some((tag) => tag !== 'unnecessary' && tag !== 'deprecated')) {
      throw new TypeError(`${label}.tags is invalid.`);
    }
    tags = Object.freeze([...record.tags]) as readonly ('unnecessary' | 'deprecated')[];
  }
  let relatedInformation: readonly DiagnosticRelatedInformation[] | undefined;
  if (record.relatedInformation !== undefined) {
    if (!Array.isArray(record.relatedInformation) || record.relatedInformation.length === 0) {
      throw new TypeError(`${label}.relatedInformation must be a non-empty array.`);
    }
    relatedInformation = Object.freeze(record.relatedInformation.map(parseRelatedInformation));
  }
  const source = optionalString(record, 'source', label);
  return Object.freeze({
    file: logicalPath(requiredString(record, 'file', label), `${label}.file`),
    range: parseRange(record.range, `${label}.range`),
    severity: record.severity as DiagnosticSeverity,
    message: requiredString(record, 'message', label),
    ...(code === undefined ? {} : { code }),
    ...(source === undefined ? {} : { source }),
    ...(tags === undefined ? {} : { tags }),
    ...(relatedInformation === undefined ? {} : { relatedInformation }),
  });
};

const warnings = (value: unknown): readonly string[] | undefined => {
  if (value === undefined) return undefined;
  if (!Array.isArray(value) || value.length === 0 || value.length > 100) {
    throw new TypeError('Bridge warnings must be a non-empty bounded array.');
  }
  return Object.freeze(value.map((entry) => {
    if (typeof entry !== 'string' || entry.length === 0 || entry.length > 512) {
      throw new TypeError('Bridge warnings must contain bounded strings.');
    }
    return entry;
  }));
};

const terminalStatuses = new Set<ProviderTerminalStatus>([
  'unavailable',
  'notReady',
  'cancelled',
  'timedOut',
  'failed',
  'positionOutOfRange',
]);

const scopedIncompleteReasons = new Set<Extract<ReferencesBridgeResponse, {
  readonly status: 'scopedIncomplete';
}>['reason']>([
  'targetUnresolved',
  'scopeBudgetExceeded',
  'scopeInvalid',
  'scopeUnsupported',
  'candidateUnresolved',
  'providerUnavailable',
  'providerTimedOut',
  'providerFailed',
]);

const parseResponse = <T>(
  value: unknown,
  label: string,
  parseCandidate: (candidate: unknown, index: number) => T,
  allowPositionOutOfRange: boolean,
  allowAvailable = false,
): { readonly status: 'completed'; readonly candidates: readonly T[]; readonly available?: number; readonly warnings?: readonly string[] } |
  { readonly status: ProviderTerminalStatus } => {
  const record = asRecord(value, label);
  if (record.status === 'completed') {
    exactFields(record, allowAvailable
      ? ['status', 'candidates', 'available', 'warnings']
      : ['status', 'candidates', 'warnings'], label);
    if (!Array.isArray(record.candidates)) {
      throw new TypeError(`${label}.candidates must be an array.`);
    }
    const parsedCandidates = Object.freeze(record.candidates.map(parseCandidate));
    const available = record.available === undefined
      ? undefined
      : nonNegativeInteger(record, 'available', label);
    if (available !== undefined && parsedCandidates.length > available) {
      throw new TypeError(`${label}.available must cover every returned candidate.`);
    }
    const parsedWarnings = warnings(record.warnings);
    return Object.freeze({
      status: 'completed',
      candidates: parsedCandidates,
      ...(available === undefined ? {} : { available }),
      ...(parsedWarnings === undefined ? {} : { warnings: parsedWarnings }),
    });
  }
  if (typeof record.status !== 'string' ||
      !terminalStatuses.has(record.status as ProviderTerminalStatus) ||
      (!allowPositionOutOfRange && record.status === 'positionOutOfRange')) {
    throw new TypeError(`${label}.status is invalid.`);
  }
  exactFields(record, ['status'], label);
  return Object.freeze({ status: record.status as ProviderTerminalStatus });
};

export const parseReferencesBridgeResponse = (value: unknown): ReferencesBridgeResponse => {
  const record = asRecord(value, 'references bridge response');
  if (record.status === 'scopedIncomplete') {
    exactFields(record, ['status', 'reason'], 'references bridge response');
    if (typeof record.reason !== 'string' ||
        !scopedIncompleteReasons.has(record.reason as Extract<ReferencesBridgeResponse, {
          readonly status: 'scopedIncomplete';
        }>['reason'])) {
      throw new TypeError('references bridge response.reason is invalid.');
    }
    return Object.freeze({
      status: 'scopedIncomplete' as const,
      reason: record.reason as Extract<ReferencesBridgeResponse, {
        readonly status: 'scopedIncomplete';
      }>['reason'],
    });
  }
  return parseResponse(value, 'references bridge response', parseReference, true, true);
};

export const parseVerifySymbolCandidatesBridgeResponse = (
  value: unknown,
): VerifySymbolCandidatesBridgeResponse =>
  parseResponse(
    value,
    'symbol candidates bridge response',
    parseSymbolCandidateVerification,
    true,
  ) as VerifySymbolCandidatesBridgeResponse;

export const parseDiagnosticsBridgeResponse = (value: unknown): DiagnosticsBridgeResponse =>
  parseResponse(value, 'diagnostics bridge response', parseDiagnostic, false) as DiagnosticsBridgeResponse;
