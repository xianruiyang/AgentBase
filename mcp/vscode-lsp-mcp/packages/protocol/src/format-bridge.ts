import type {
  DocumentChangedDetails,
  EditConflictDetails,
  FormatPreviewInput,
  FormattingOptions,
  Range,
} from './dto.js';
import { parseNormalizedWorkspaceEdit } from './mutation-bridge.js';
import type { NormalizedWorkspaceEdit } from './mutation.js';
import type { WorkspaceRouteIdentity } from './runtime.js';
import { isWorkspaceId } from './workspace-identity.js';

export const MUTATION_FORMAT_PREVIEW_BRIDGE_METHOD = 'mutation.formatPreview' as const;

export interface FormatPreviewBridgeRequest extends Omit<FormatPreviewInput, 'workspaceId'> {
  readonly workspace: WorkspaceRouteIdentity;
}

export type FormatPreviewBridgeResponse =
  | { readonly status: 'completed'; readonly normalizedEdit: NormalizedWorkspaceEdit }
  | { readonly status: 'workspaceChanged' }
  | { readonly status: 'pathOutsideWorkspace' }
  | { readonly status: 'documentNotFound' }
  | { readonly status: 'positionOutOfRange' }
  | { readonly status: 'unavailable' | 'notReady' | 'cancelled' | 'timedOut' | 'failed' }
  | ({ readonly status: 'documentChanged' } & DocumentChangedDetails)
  | ({ readonly status: 'editConflict' } & EditConflictDetails);

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

const parseWorkspace = (value: unknown): WorkspaceRouteIdentity => {
  const record = asRecord(value, 'format preview bridge request.workspace');
  exactFields(record, ['workspaceId', 'generation'], 'format preview bridge request.workspace');
  if (typeof record.workspaceId !== 'string' || !isWorkspaceId(record.workspaceId)) {
    throw new TypeError('Format preview workspace identity is invalid.');
  }
  return Object.freeze({
    workspaceId: record.workspaceId,
    generation: safeInteger(record.generation, 1, 'workspace.generation'),
  });
};

const parseRange = (value: unknown): Range => {
  const record = asRecord(value, 'format preview bridge request.range');
  exactFields(
    record,
    ['startLine', 'startColumn', 'endLine', 'endColumn'],
    'format preview bridge request.range',
  );
  const parsed = Object.freeze({
    startLine: safeInteger(record.startLine, 1, 'range.startLine'),
    startColumn: safeInteger(record.startColumn, 1, 'range.startColumn'),
    endLine: safeInteger(record.endLine, 1, 'range.endLine'),
    endColumn: safeInteger(record.endColumn, 1, 'range.endColumn'),
  });
  if (parsed.endLine < parsed.startLine ||
      (parsed.endLine === parsed.startLine && parsed.endColumn < parsed.startColumn)) {
    throw new TypeError('Format preview range is reversed.');
  }
  return parsed;
};

const parseOptions = (value: unknown): FormattingOptions => {
  const record = asRecord(value, 'format preview bridge request.options');
  exactFields(record, ['tabSize', 'insertSpaces'], 'format preview bridge request.options');
  if (Object.keys(record).length === 0 ||
      (record.tabSize !== undefined &&
        (!Number.isSafeInteger(record.tabSize) || (record.tabSize as number) < 1 ||
          (record.tabSize as number) > 32)) ||
      (record.insertSpaces !== undefined && typeof record.insertSpaces !== 'boolean')) {
    throw new TypeError('Format preview options are invalid.');
  }
  return Object.freeze({
    ...(record.tabSize === undefined ? {} : { tabSize: record.tabSize as number }),
    ...(record.insertSpaces === undefined ? {} : { insertSpaces: record.insertSpaces as boolean }),
  });
};

export const parseFormatPreviewBridgeRequest = (value: unknown): FormatPreviewBridgeRequest => {
  const record = asRecord(value, 'format preview bridge request');
  exactFields(
    record,
    ['workspace', 'file', 'range', 'options'],
    'format preview bridge request',
  );
  return Object.freeze({
    workspace: parseWorkspace(record.workspace),
    file: boundedString(record.file, 'file', 16_384),
    ...(record.range === undefined ? {} : { range: parseRange(record.range) }),
    ...(record.options === undefined ? {} : { options: parseOptions(record.options) }),
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

const parseAdditionalFiles = (value: unknown, label: string): number | undefined =>
  value === undefined ? undefined : safeInteger(value, 1, label);

export const parseFormatPreviewBridgeResponse = (value: unknown): FormatPreviewBridgeResponse => {
  const record = asRecord(value, 'format preview bridge response');
  if (record.status === 'completed') {
    exactFields(record, ['status', 'normalizedEdit'], 'format preview bridge response');
    return Object.freeze({
      status: 'completed',
      normalizedEdit: parseNormalizedWorkspaceEdit(record.normalizedEdit),
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
    exactFields(record, ['status'], 'format preview bridge response');
    return Object.freeze({
      status: record.status as Exclude<FormatPreviewBridgeResponse['status'],
      'completed' | 'documentChanged' | 'editConflict'>,
    });
  }
  if (record.status === 'documentChanged') {
    exactFields(
      record,
      ['status', 'reason', 'files', 'additionalFiles'],
      'format preview bridge response',
    );
    if (!['content', 'version', 'existence', 'workspace'].includes(record.reason as string)) {
      throw new TypeError('Format documentChanged reason is invalid.');
    }
    const files = parseFiles(record.files, 'documentChanged.files');
    const additionalFiles = parseAdditionalFiles(
      record.additionalFiles,
      'documentChanged.additionalFiles',
    );
    return Object.freeze({
      status: 'documentChanged',
      reason: record.reason as DocumentChangedDetails['reason'],
      ...(files === undefined ? {} : { files }),
      ...(additionalFiles === undefined ? {} : { additionalFiles }),
    });
  }
  if (record.status === 'editConflict') {
    exactFields(
      record,
      ['status', 'reason', 'files', 'additionalFiles'],
      'format preview bridge response',
    );
    if (![
      'overlappingEdits',
      'rangeOutOfBounds',
      'unsupportedEdit',
      'ambiguousOperationOrder',
    ].includes(record.reason as string)) {
      throw new TypeError('Format editConflict reason is invalid.');
    }
    const files = parseFiles(record.files, 'editConflict.files');
    const additionalFiles = parseAdditionalFiles(record.additionalFiles, 'editConflict.additionalFiles');
    return Object.freeze({
      status: 'editConflict',
      reason: record.reason as EditConflictDetails['reason'],
      ...(files === undefined ? {} : { files }),
      ...(additionalFiles === undefined ? {} : { additionalFiles }),
    });
  }
  throw new TypeError('Format preview bridge response status is invalid.');
};
