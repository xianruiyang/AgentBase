import type {
  HoverInfo,
  LocationInfo,
  SignatureInfo,
  SignatureParameter,
} from './dto.js';

export const SYMBOL_INFO_BRIDGE_METHOD = 'symbol.info' as const;

export interface SignatureInfoBridgeCandidate extends SignatureInfo {
  readonly activeSignature: boolean;
}

export type SymbolInfoBridgeCandidate =
  | HoverInfo
  | LocationInfo
  | SignatureInfoBridgeCandidate;

export type SymbolInfoBridgeResponse =
  | {
      readonly status: 'completed';
      readonly candidates: readonly SymbolInfoBridgeCandidate[];
      readonly warnings?: readonly string[];
    }
  | {
      readonly status:
        | 'unavailable'
        | 'notReady'
        | 'cancelled'
        | 'timedOut'
        | 'failed'
        | 'positionOutOfRange';
    };

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

const optionalIndex = (
  value: Record<string, unknown>,
  field: string,
  label: string,
): number | undefined => {
  const result = value[field];
  if (result === undefined) return undefined;
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

const parseParameter = (value: unknown, index: number): SignatureParameter => {
  const label = `signature parameter ${index}`;
  const record = asRecord(value, label);
  exactFields(record, ['label', 'documentation'], label);
  const documentation = optionalString(record, 'documentation', label);
  return Object.freeze({
    label: requiredString(record, 'label', label),
    ...(documentation === undefined ? {} : { documentation }),
  });
};

const parseCandidate = (value: unknown, index: number): SymbolInfoBridgeCandidate => {
  const label = `symbol info candidate ${index}`;
  const record = asRecord(value, label);
  const type = record.type;
  if (type === 'hover') {
    exactFields(record, ['type', 'text'], label);
    return Object.freeze({ type, text: requiredString(record, 'text', label) });
  }
  if (
    type === 'declaration' ||
    type === 'definition' ||
    type === 'typeDefinition' ||
    type === 'implementation'
  ) {
    exactFields(record, ['type', 'file', 'line', 'column', 'snippet'], label);
    const snippet = optionalString(record, 'snippet', label);
    return Object.freeze({
      type,
      file: logicalPath(requiredString(record, 'file', label), `${label}.file`),
      line: positiveInteger(record, 'line', label),
      column: positiveInteger(record, 'column', label),
      ...(snippet === undefined ? {} : { snippet }),
    });
  }
  if (type === 'signatureHelp') {
    exactFields(
      record,
      ['type', 'label', 'activeSignature', 'activeParameter', 'documentation', 'parameters'],
      label,
    );
    if (typeof record.activeSignature !== 'boolean') {
      throw new TypeError(`${label}.activeSignature must be boolean.`);
    }
    const activeParameter = optionalIndex(record, 'activeParameter', label);
    const documentation = optionalString(record, 'documentation', label);
    let parameters: readonly SignatureParameter[] | undefined;
    if (record.parameters !== undefined) {
      if (!Array.isArray(record.parameters) || record.parameters.length === 0) {
        throw new TypeError(`${label}.parameters must be a non-empty array.`);
      }
      parameters = Object.freeze(record.parameters.map(parseParameter));
    }
    return Object.freeze({
      type,
      label: requiredString(record, 'label', label),
      activeSignature: record.activeSignature,
      ...(activeParameter === undefined ? {} : { activeParameter }),
      ...(documentation === undefined ? {} : { documentation }),
      ...(parameters === undefined ? {} : { parameters }),
    });
  }
  throw new TypeError(`${label}.type is invalid.`);
};

const warnings = (value: unknown): readonly string[] | undefined => {
  if (value === undefined) return undefined;
  if (!Array.isArray(value) || value.length === 0 || value.length > 100) {
    throw new TypeError('Symbol info warnings must be a non-empty bounded array.');
  }
  return Object.freeze(value.map((entry) => {
    if (typeof entry !== 'string' || entry.length === 0 || entry.length > 512) {
      throw new TypeError('Symbol info warnings must contain bounded strings.');
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
  'positionOutOfRange',
]);

export const parseSymbolInfoBridgeResponse = (value: unknown): SymbolInfoBridgeResponse => {
  const record = asRecord(value, 'symbol info bridge response');
  const status = record.status;
  if (status === 'completed') {
    exactFields(record, ['status', 'candidates', 'warnings'], 'symbol info bridge response');
    if (!Array.isArray(record.candidates)) {
      throw new TypeError('Completed symbol info bridge response must contain candidates.');
    }
    const parsedWarnings = warnings(record.warnings);
    return Object.freeze({
      status,
      candidates: Object.freeze(record.candidates.map(parseCandidate)),
      ...(parsedWarnings === undefined ? {} : { warnings: parsedWarnings }),
    });
  }
  if (typeof status !== 'string' || !terminalStatuses.has(status)) {
    throw new TypeError('Symbol info bridge response status is invalid.');
  }
  exactFields(record, ['status'], 'symbol info bridge response');
  return Object.freeze({ status }) as SymbolInfoBridgeResponse;
};
