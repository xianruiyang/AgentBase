import type {
  ActionNotPreviewableDetails,
  CodeActionsInput,
  DocumentChangedDetails,
  Range,
} from './dto.js';
import {
  parseNormalizedWorkspaceEdit,
  parseTextDocumentSnapshot,
} from './mutation-bridge.js';
import type {
  NormalizedWorkspaceEdit,
  TextDocumentSnapshot,
} from './mutation.js';
import type { WorkspaceRouteIdentity } from './runtime.js';
import { isWorkspaceId } from './workspace-identity.js';

export const MUTATION_CODE_ACTIONS_BRIDGE_METHOD = 'mutation.codeActions' as const;
export const MUTATION_CODE_ACTION_PREVIEW_BRIDGE_METHOD = 'mutation.codeActionPreview' as const;
export const CODE_ACTION_RESOLVE_LIMIT = 100;
export const CODE_ACTION_RAW_LIMIT = 1_000;

export interface CodeActionsBridgeRequest extends Omit<CodeActionsInput, 'workspaceId'> {
  readonly workspace: WorkspaceRouteIdentity;
  readonly resultStart: number;
  readonly resultEnd: number;
}

export interface CodeActionBridgeCandidate {
  readonly title: string;
  readonly kind?: string;
  readonly preferred: boolean;
  readonly normalizedEdit: NormalizedWorkspaceEdit;
}

export type CodeActionsBridgeResponse =
  | {
      readonly status: 'completed';
      readonly sourceSnapshot: TextDocumentSnapshot;
      readonly candidates: readonly CodeActionBridgeCandidate[];
      readonly available: number;
      readonly warnings?: readonly string[];
    }
  | { readonly status: 'workspaceChanged' }
  | { readonly status: 'pathOutsideWorkspace' }
  | { readonly status: 'documentNotFound' }
  | { readonly status: 'positionOutOfRange' }
  | { readonly status: 'unavailable' | 'notReady' | 'cancelled' | 'timedOut' | 'failed' }
  | ({ readonly status: 'documentChanged' } & DocumentChangedDetails);

export interface CodeActionPreviewBridgeRequest {
  readonly workspace: WorkspaceRouteIdentity;
  readonly sourceSnapshot: TextDocumentSnapshot;
  readonly normalizedEdit: NormalizedWorkspaceEdit;
}

export type CodeActionPreviewBridgeResponse =
  | { readonly status: 'ready' }
  | { readonly status: 'workspaceChanged' }
  | { readonly status: 'pathOutsideWorkspace' }
  | ({ readonly status: 'documentChanged' } & DocumentChangedDetails)
  | ({ readonly status: 'actionNotPreviewable' } & ActionNotPreviewableDetails)
  | { readonly status: 'failed' };

const asRecord = (value: unknown, label: string): Record<string, unknown> => {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object.`);
  }
  return value as Record<string, unknown>;
};

const exactFields = (
  value: Record<string, unknown>,
  fields: readonly string[],
  label: string,
): void => {
  const allowed = new Set(fields);
  if (Object.keys(value).some((field) => !allowed.has(field))) {
    throw new TypeError(`${label} contains an unknown field.`);
  }
};

const safeInteger = (value: unknown, minimum: number, label: string): number => {
  if (!Number.isSafeInteger(value) || (value as number) < minimum) {
    throw new TypeError(`${label} must be a safe integer at least ${minimum}.`);
  }
  return value as number;
};

const boundedString = (value: unknown, label: string, maximum: number): string => {
  if (typeof value !== 'string' || value.length === 0 || value.length > maximum) {
    throw new TypeError(`${label} must be a bounded non-empty string.`);
  }
  return value;
};

const parseWorkspace = (value: unknown, label: string): WorkspaceRouteIdentity => {
  const record = asRecord(value, label);
  exactFields(record, ['workspaceId', 'generation'], label);
  if (typeof record.workspaceId !== 'string' || !isWorkspaceId(record.workspaceId)) {
    throw new TypeError(`${label}.workspaceId is invalid.`);
  }
  return Object.freeze({
    workspaceId: record.workspaceId,
    generation: safeInteger(record.generation, 1, `${label}.generation`),
  });
};

const parseRange = (value: unknown, label: string): Range => {
  const record = asRecord(value, label);
  exactFields(record, ['startLine', 'startColumn', 'endLine', 'endColumn'], label);
  const parsed = Object.freeze({
    startLine: safeInteger(record.startLine, 1, `${label}.startLine`),
    startColumn: safeInteger(record.startColumn, 1, `${label}.startColumn`),
    endLine: safeInteger(record.endLine, 1, `${label}.endLine`),
    endColumn: safeInteger(record.endColumn, 1, `${label}.endColumn`),
  });
  if (parsed.endLine < parsed.startLine ||
      (parsed.endLine === parsed.startLine && parsed.endColumn < parsed.startColumn)) {
    throw new TypeError(`${label} is reversed.`);
  }
  return parsed;
};

export const parseCodeActionsBridgeRequest = (value: unknown): CodeActionsBridgeRequest => {
  const record = asRecord(value, 'code actions bridge request');
  exactFields(
    record,
    ['workspace', 'file', 'range', 'onlyKinds', 'resultStart', 'resultEnd'],
    'code actions bridge request',
  );
  let onlyKinds: readonly string[] | undefined;
  if (record.onlyKinds !== undefined) {
    if (!Array.isArray(record.onlyKinds) || record.onlyKinds.length === 0 ||
        record.onlyKinds.length > 50 || new Set(record.onlyKinds).size !== record.onlyKinds.length) {
      throw new TypeError('code actions bridge request.onlyKinds is invalid.');
    }
    onlyKinds = Object.freeze(record.onlyKinds.map((kind, index) =>
      boundedString(kind, `onlyKinds[${index}]`, 1_024)));
  }
  const resultStart = safeInteger(record.resultStart, 1, 'resultStart');
  const resultEnd = safeInteger(record.resultEnd, 1, 'resultEnd');
  if (resultEnd < resultStart || resultEnd - resultStart + 1 > 100) {
    throw new TypeError('code actions bridge result window is invalid.');
  }
  return Object.freeze({
    workspace: parseWorkspace(record.workspace, 'code actions bridge request.workspace'),
    file: boundedString(record.file, 'file', 16_384),
    range: parseRange(record.range, 'range'),
    resultStart,
    resultEnd,
    ...(onlyKinds === undefined ? {} : { onlyKinds }),
  });
};

const parseFiles = (value: unknown, label: string): readonly string[] | undefined => {
  if (value === undefined) return undefined;
  if (!Array.isArray(value) || value.length > 100 ||
      value.some((file) => typeof file !== 'string' || file.length === 0)) {
    throw new TypeError(`${label} is invalid.`);
  }
  const files = Object.freeze([...(value as string[])]);
  if (new Set(files).size !== files.length) throw new TypeError(`${label} contains duplicates.`);
  return files;
};

const parseDocumentChanged = (
  record: Record<string, unknown>,
  label: string,
): Extract<CodeActionsBridgeResponse, { readonly status: 'documentChanged' }> => {
  exactFields(record, ['status', 'reason', 'files', 'additionalFiles'], label);
  if (!['content', 'version', 'existence', 'workspace'].includes(record.reason as string)) {
    throw new TypeError(`${label}.reason is invalid.`);
  }
  const files = parseFiles(record.files, `${label}.files`);
  const additionalFiles = record.additionalFiles === undefined
    ? undefined
    : safeInteger(record.additionalFiles, 1, `${label}.additionalFiles`);
  return Object.freeze({
    status: 'documentChanged',
    reason: record.reason as DocumentChangedDetails['reason'],
    ...(files === undefined ? {} : { files }),
    ...(additionalFiles === undefined ? {} : { additionalFiles }),
  });
};

const parseCandidate = (value: unknown, index: number): CodeActionBridgeCandidate => {
  const label = `code actions bridge response.candidates[${index}]`;
  const record = asRecord(value, label);
  exactFields(record, ['title', 'kind', 'preferred', 'normalizedEdit'], label);
  if (typeof record.preferred !== 'boolean') throw new TypeError(`${label}.preferred is invalid.`);
  const kind = record.kind === undefined
    ? undefined
    : boundedString(record.kind, `${label}.kind`, 1_024);
  return Object.freeze({
    title: boundedString(record.title, `${label}.title`, 4_096),
    ...(kind === undefined ? {} : { kind }),
    preferred: record.preferred,
    normalizedEdit: parseNormalizedWorkspaceEdit(record.normalizedEdit, true),
  });
};

const parseWarnings = (value: unknown): readonly string[] | undefined => {
  if (value === undefined) return undefined;
  if (!Array.isArray(value) || value.length === 0 || value.length > 32 ||
      new Set(value).size !== value.length) {
    throw new TypeError('code actions bridge warnings are invalid.');
  }
  return Object.freeze(value.map((warning, index) =>
    boundedString(warning, `warnings[${index}]`, 256)));
};

export const parseCodeActionsBridgeResponse = (value: unknown): CodeActionsBridgeResponse => {
  const record = asRecord(value, 'code actions bridge response');
  if (record.status === 'completed') {
    exactFields(
      record,
      ['status', 'sourceSnapshot', 'candidates', 'available', 'warnings'],
      'code actions bridge response',
    );
    if (!Array.isArray(record.candidates) || record.candidates.length > 100) {
      throw new TypeError('code actions bridge candidates are invalid.');
    }
    const candidates = Object.freeze(record.candidates.map(parseCandidate));
    const available = safeInteger(record.available, 0, 'available');
    if (available < candidates.length) throw new TypeError('available is smaller than candidates.');
    const warnings = parseWarnings(record.warnings);
    return Object.freeze({
      status: 'completed',
      sourceSnapshot: parseTextDocumentSnapshot(record.sourceSnapshot, 'sourceSnapshot'),
      candidates,
      available,
      ...(warnings === undefined ? {} : { warnings }),
    });
  }
  if ([
    'workspaceChanged',
    'pathOutsideWorkspace',
    'documentNotFound',
    'positionOutOfRange',
    'unavailable',
    'notReady',
    'cancelled',
    'timedOut',
    'failed',
  ].includes(record.status as string)) {
    exactFields(record, ['status'], 'code actions bridge response');
    return Object.freeze({
      status: record.status as Exclude<CodeActionsBridgeResponse['status'],
      'completed' | 'documentChanged'>,
    });
  }
  if (record.status === 'documentChanged') {
    return parseDocumentChanged(record, 'code actions bridge response');
  }
  throw new TypeError('code actions bridge response status is invalid.');
};

export const parseCodeActionPreviewBridgeRequest = (
  value: unknown,
): CodeActionPreviewBridgeRequest => {
  const record = asRecord(value, 'code action preview bridge request');
  exactFields(
    record,
    ['workspace', 'sourceSnapshot', 'normalizedEdit'],
    'code action preview bridge request',
  );
  return Object.freeze({
    workspace: parseWorkspace(record.workspace, 'code action preview bridge request.workspace'),
    sourceSnapshot: parseTextDocumentSnapshot(record.sourceSnapshot, 'sourceSnapshot'),
    normalizedEdit: parseNormalizedWorkspaceEdit(record.normalizedEdit, true),
  });
};

export const parseCodeActionPreviewBridgeResponse = (
  value: unknown,
): CodeActionPreviewBridgeResponse => {
  const record = asRecord(value, 'code action preview bridge response');
  if (record.status === 'ready' || record.status === 'workspaceChanged' ||
      record.status === 'pathOutsideWorkspace' || record.status === 'failed') {
    exactFields(record, ['status'], 'code action preview bridge response');
    return Object.freeze({ status: record.status });
  }
  if (record.status === 'documentChanged') {
    return parseDocumentChanged(record, 'code action preview bridge response');
  }
  if (record.status === 'actionNotPreviewable') {
    exactFields(record, ['status', 'reason'], 'code action preview bridge response');
    if (![
      'missingEdit',
      'containsCommand',
      'resourceOperationsUnsupported',
      'unsupportedEdit',
      'cachedActionInvalid',
    ].includes(record.reason as string)) {
      throw new TypeError('code action preview reason is invalid.');
    }
    return Object.freeze({
      status: 'actionNotPreviewable',
      reason: record.reason as ActionNotPreviewableDetails['reason'],
    });
  }
  throw new TypeError('code action preview bridge response status is invalid.');
};
