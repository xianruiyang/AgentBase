import {
  SYMBOL_KINDS,
  type HierarchySymbol,
  type Range,
  type SymbolKind,
} from './dto.js';

export const HIERARCHY_BRIDGE_METHODS = Object.freeze({
  prepare: 'hierarchy.prepare',
  expand: 'hierarchy.expand',
  release: 'hierarchy.release',
} as const);

export type HierarchyBridgeKind = 'call' | 'type';
export type HierarchyBridgeDirection = 'incoming' | 'outgoing' | 'supertype' | 'subtype';

export interface HierarchyBridgeNode {
  readonly nodeId: string;
  readonly symbol: HierarchySymbol;
  readonly callSites?: readonly Range[];
}

type HierarchyTerminalStatus =
  | 'unavailable'
  | 'notReady'
  | 'cancelled'
  | 'timedOut'
  | 'failed'
  | 'positionOutOfRange';

export type HierarchyPrepareBridgeResponse =
  | {
      readonly status: 'completed';
      readonly traversalId: string;
      readonly nodes: readonly HierarchyBridgeNode[];
      readonly warnings?: readonly string[];
    }
  | { readonly status: HierarchyTerminalStatus };

export type HierarchyExpandBridgeResponse =
  | {
      readonly status: 'completed';
      readonly nodes: readonly HierarchyBridgeNode[];
      readonly warnings?: readonly string[];
    }
  | { readonly status: Exclude<HierarchyTerminalStatus, 'positionOutOfRange'> };

export type HierarchyReleaseBridgeResponse =
  | { readonly status: 'completed' }
  | { readonly status: 'failed' };

const symbolKinds = new Set<string>(SYMBOL_KINDS);
const terminalStatuses = new Set<HierarchyTerminalStatus>([
  'unavailable',
  'notReady',
  'cancelled',
  'timedOut',
  'failed',
  'positionOutOfRange',
]);
const traversalIdPattern = /^h[1-9][0-9]{0,15}$/u;
const nodeIdPattern = /^n[1-9][0-9]{0,15}$/u;

export const isHierarchyTraversalId = (value: unknown): value is string =>
  typeof value === 'string' && traversalIdPattern.test(value);

export const isHierarchyNodeId = (value: unknown): value is string =>
  typeof value === 'string' && nodeIdPattern.test(value);

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
  if (Object.keys(value).some((field) => !allowedSet.has(field))) {
    throw new TypeError(`${label} contains an unknown field.`);
  }
};

const requiredText = (
  value: Record<string, unknown>,
  field: string,
  label: string,
): string => {
  const result = value[field];
  if (typeof result !== 'string' || result.length === 0 || result.length > 4_096) {
    throw new TypeError(`${label}.${field} must be a bounded non-empty string.`);
  }
  return result;
};

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

const parseSymbol = (value: unknown, label: string): HierarchySymbol => {
  const record = asRecord(value, label);
  exactFields(record, ['name', 'kind', 'file', 'line', 'column'], label);
  if (typeof record.kind !== 'string' || !symbolKinds.has(record.kind)) {
    throw new TypeError(`${label}.kind is invalid.`);
  }
  return Object.freeze({
    name: requiredText(record, 'name', label),
    kind: record.kind as SymbolKind,
    file: logicalPath(requiredText(record, 'file', label), `${label}.file`),
    line: positiveInteger(record, 'line', label),
    column: positiveInteger(record, 'column', label),
  });
};

const parseRange = (value: unknown, label: string): Range => {
  const record = asRecord(value, label);
  exactFields(record, ['startLine', 'startColumn', 'endLine', 'endColumn'], label);
  const result = Object.freeze({
    startLine: positiveInteger(record, 'startLine', label),
    startColumn: positiveInteger(record, 'startColumn', label),
    endLine: positiveInteger(record, 'endLine', label),
    endColumn: positiveInteger(record, 'endColumn', label),
  });
  if (result.endLine < result.startLine ||
      (result.endLine === result.startLine && result.endColumn < result.startColumn)) {
    throw new TypeError(`${label} must be ordered and end-exclusive.`);
  }
  return result;
};

const parseNode = (value: unknown, index: number): HierarchyBridgeNode => {
  const label = `hierarchy node ${index}`;
  const record = asRecord(value, label);
  exactFields(record, ['nodeId', 'symbol', 'callSites'], label);
  if (!isHierarchyNodeId(record.nodeId)) {
    throw new TypeError(`${label}.nodeId is invalid.`);
  }
  let callSites: readonly Range[] | undefined;
  if (record.callSites !== undefined) {
    if (!Array.isArray(record.callSites) || record.callSites.length === 0 ||
        record.callSites.length > 5_000) {
      throw new TypeError(`${label}.callSites must be a non-empty bounded array.`);
    }
    callSites = Object.freeze(record.callSites.map((range, rangeIndex) =>
      parseRange(range, `${label}.callSites[${rangeIndex}]`)));
  }
  return Object.freeze({
    nodeId: record.nodeId,
    symbol: parseSymbol(record.symbol, `${label}.symbol`),
    ...(callSites === undefined ? {} : { callSites }),
  });
};

const parseWarnings = (value: unknown): readonly string[] | undefined => {
  if (value === undefined) return undefined;
  if (!Array.isArray(value) || value.length === 0 || value.length > 100) {
    throw new TypeError('Hierarchy bridge warnings must be a non-empty bounded array.');
  }
  return Object.freeze(value.map((warning) => {
    if (typeof warning !== 'string' || warning.length === 0 || warning.length > 512) {
      throw new TypeError('Hierarchy bridge warnings must contain bounded strings.');
    }
    return warning;
  }));
};

const parseTerminal = (
  record: Record<string, unknown>,
  allowPositionOutOfRange: boolean,
  label: string,
): { readonly status: HierarchyTerminalStatus } => {
  const status = record.status;
  if (typeof status !== 'string' || !terminalStatuses.has(status as HierarchyTerminalStatus) ||
      (!allowPositionOutOfRange && status === 'positionOutOfRange')) {
    throw new TypeError(`${label}.status is invalid.`);
  }
  exactFields(record, ['status'], label);
  return Object.freeze({ status: status as HierarchyTerminalStatus });
};

const parseNodes = (value: unknown, label: string): readonly HierarchyBridgeNode[] => {
  if (!Array.isArray(value) || value.length > 5_000) {
    throw new TypeError(`${label} must be a bounded array.`);
  }
  const nodes = Object.freeze(value.map(parseNode));
  if (new Set(nodes.map((node) => node.nodeId)).size !== nodes.length) {
    throw new TypeError(`${label} contains duplicate node IDs.`);
  }
  return nodes;
};

export const parseHierarchyPrepareBridgeResponse = (
  value: unknown,
): HierarchyPrepareBridgeResponse => {
  const label = 'hierarchy prepare bridge response';
  const record = asRecord(value, label);
  if (record.status !== 'completed') return parseTerminal(record, true, label);
  exactFields(record, ['status', 'traversalId', 'nodes', 'warnings'], label);
  if (!isHierarchyTraversalId(record.traversalId)) {
    throw new TypeError(`${label}.traversalId is invalid.`);
  }
  const nodes = parseNodes(record.nodes, `${label}.nodes`);
  if (nodes.some((node) => node.callSites !== undefined)) {
    throw new TypeError(`${label} root nodes cannot contain call sites.`);
  }
  const warnings = parseWarnings(record.warnings);
  return Object.freeze({
    status: 'completed',
    traversalId: record.traversalId,
    nodes,
    ...(warnings === undefined ? {} : { warnings }),
  });
};

export const parseHierarchyExpandBridgeResponse = (
  value: unknown,
): HierarchyExpandBridgeResponse => {
  const label = 'hierarchy expand bridge response';
  const record = asRecord(value, label);
  if (record.status !== 'completed') {
    return parseTerminal(record, false, label) as HierarchyExpandBridgeResponse;
  }
  exactFields(record, ['status', 'nodes', 'warnings'], label);
  const warnings = parseWarnings(record.warnings);
  return Object.freeze({
    status: 'completed',
    nodes: parseNodes(record.nodes, `${label}.nodes`),
    ...(warnings === undefined ? {} : { warnings }),
  });
};

export const parseHierarchyReleaseBridgeResponse = (
  value: unknown,
): HierarchyReleaseBridgeResponse => {
  const label = 'hierarchy release bridge response';
  const record = asRecord(value, label);
  if (record.status !== 'completed' && record.status !== 'failed') {
    throw new TypeError(`${label}.status is invalid.`);
  }
  exactFields(record, ['status'], label);
  return Object.freeze({ status: record.status });
};
