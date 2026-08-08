import type {
  DocumentChangedDetails,
  EditConflictDetails,
  RenamePreviewInput,
} from './dto.js';
import {
  parseNormalizedWorkspaceEdit,
} from './mutation-bridge.js';
import type { NormalizedWorkspaceEdit } from './mutation.js';
import type { WorkspaceRouteIdentity } from './runtime.js';
import { isWorkspaceId } from './workspace-identity.js';
import { isSupportedLogicalGlob } from './collection.js';

export const MUTATION_RENAME_PREVIEW_BRIDGE_METHOD = 'mutation.renamePreview' as const;

export interface RenamePreviewBridgeRequest extends Omit<
  RenamePreviewInput,
  'workspaceId'
> {
  readonly workspace: WorkspaceRouteIdentity;
}

export type RenamePrepareRejectionReason = 'invalidResult' | 'notRenameable';

export type RenameIdentityRejectionReason =
  | 'targetUnresolved'
  | 'editUnresolved'
  | 'mismatchedSymbol'
  | 'textMismatch'
  | 'budgetExceeded'
  | 'providerFailed'
  | 'providerTimedOut';

export interface RenameIdentityRejectionDetails {
  readonly reason: RenameIdentityRejectionReason;
  readonly checkedEdits: number;
  readonly totalEdits: number;
  readonly files?: readonly string[];
  readonly additionalFiles?: number;
}

export type RenamePreviewBridgeResponse =
  | { readonly status: 'completed'; readonly normalizedEdit: NormalizedWorkspaceEdit }
  | {
      readonly status: 'scopeRejected';
      readonly files: readonly string[];
      readonly additionalFiles?: number;
      readonly totalFiles: number;
    }
  | { readonly status: 'workspaceChanged' }
  | { readonly status: 'pathOutsideWorkspace' }
  | { readonly status: 'documentNotFound' }
  | { readonly status: 'positionOutOfRange' }
  | { readonly status: 'unavailable' | 'notReady' | 'cancelled' | 'timedOut' | 'failed' | 'noEdits' }
  | { readonly status: 'prepareRejected'; readonly reason: RenamePrepareRejectionReason }
  | ({ readonly status: 'identityRejected' } & RenameIdentityRejectionDetails)
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

const nonEmptyString = (value: unknown, label: string, maximum?: number): string => {
  if (typeof value !== 'string' || value.length === 0 ||
      (maximum !== undefined && value.length > maximum)) {
    throw new TypeError(`${label} must be a bounded non-empty string.`);
  }
  return value;
};

const safeInteger = (value: unknown, minimum: number, label: string): number => {
  if (!Number.isSafeInteger(value) || (value as number) < minimum) {
    throw new TypeError(`${label} must be a safe integer at least ${minimum}.`);
  }
  return value as number;
};

const logicalGlobs = (
  value: unknown,
  label: string,
  required: boolean,
): readonly string[] | undefined => {
  if (value === undefined && !required) return undefined;
  if (!Array.isArray(value) || value.length < 1 || value.length > 20 ||
      value.some((pattern) => typeof pattern !== 'string' || pattern.length === 0 ||
        !isSupportedLogicalGlob(pattern))) {
    throw new TypeError(`${label} must contain 1 through 20 supported logical globs.`);
  }
  return Object.freeze([...(value as string[])]);
};

const parseWorkspace = (value: unknown): WorkspaceRouteIdentity => {
  const workspace = asRecord(value, 'rename preview bridge request.workspace');
  exactFields(workspace, ['workspaceId', 'generation'], 'rename preview bridge request.workspace');
  if (typeof workspace.workspaceId !== 'string' || !isWorkspaceId(workspace.workspaceId)) {
    throw new TypeError('Rename preview workspace identity is invalid.');
  }
  return Object.freeze({
    workspaceId: workspace.workspaceId,
    generation: safeInteger(workspace.generation, 1, 'workspace.generation'),
  });
};

export const parseRenamePreviewBridgeRequest = (value: unknown): RenamePreviewBridgeRequest => {
  const record = asRecord(value, 'rename preview bridge request');
  exactFields(
    record,
    [
      'workspace',
      'file',
      'line',
      'column',
      'newName',
      'includeGlobs',
      'excludeGlobs',
      'timeoutMs',
    ],
    'rename preview bridge request',
  );
  const excludeGlobs = logicalGlobs(record.excludeGlobs, 'excludeGlobs', false);
  const timeoutMs = record.timeoutMs === undefined
    ? undefined
    : safeInteger(record.timeoutMs, 1_000, 'timeoutMs');
  if (timeoutMs !== undefined && timeoutMs > 90_000) {
    throw new TypeError('timeoutMs must not exceed 90000.');
  }
  return Object.freeze({
    workspace: parseWorkspace(record.workspace),
    file: nonEmptyString(record.file, 'file'),
    line: safeInteger(record.line, 1, 'line'),
    column: safeInteger(record.column, 1, 'column'),
    newName: nonEmptyString(record.newName, 'newName', 1_000),
    includeGlobs: logicalGlobs(record.includeGlobs, 'includeGlobs', true)!,
    ...(excludeGlobs === undefined ? {} : { excludeGlobs }),
    ...(timeoutMs === undefined ? {} : { timeoutMs }),
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

const additionalFiles = (value: unknown, label: string): number | undefined =>
  value === undefined ? undefined : safeInteger(value, 1, label);

export const parseRenamePreviewBridgeResponse = (value: unknown): RenamePreviewBridgeResponse => {
  const record = asRecord(value, 'rename preview bridge response');
  if (record.status === 'completed') {
    exactFields(record, ['status', 'normalizedEdit'], 'rename preview bridge response');
    return Object.freeze({
      status: 'completed',
      normalizedEdit: parseNormalizedWorkspaceEdit(record.normalizedEdit),
    });
  }
  if (record.status === 'scopeRejected') {
    exactFields(
      record,
      ['status', 'files', 'additionalFiles', 'totalFiles'],
      'rename preview bridge response',
    );
    const files = parseFiles(record.files, 'scopeRejected.files');
    if (files === undefined || files.length === 0) {
      throw new TypeError('scopeRejected.files must contain at least one file.');
    }
    const extra = additionalFiles(record.additionalFiles, 'scopeRejected.additionalFiles');
    const totalFiles = safeInteger(record.totalFiles, 1, 'scopeRejected.totalFiles');
    if (files.length + (extra ?? 0) > totalFiles) {
      throw new TypeError('scopeRejected out-of-scope file count exceeds totalFiles.');
    }
    return Object.freeze({
      status: 'scopeRejected',
      files,
      ...(extra === undefined ? {} : { additionalFiles: extra }),
      totalFiles,
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
    'noEdits',
  ].includes(record.status as string)) {
    exactFields(record, ['status'], 'rename preview bridge response');
    return Object.freeze({
      status: record.status as Exclude<RenamePreviewBridgeResponse['status'],
      'completed' | 'scopeRejected' | 'prepareRejected' | 'identityRejected' |
      'documentChanged' | 'editConflict'>,
    });
  }
  if (record.status === 'prepareRejected') {
    exactFields(record, ['status', 'reason'], 'rename preview bridge response');
    if (record.reason !== 'invalidResult' && record.reason !== 'notRenameable') {
      throw new TypeError('Rename prepare rejection reason is invalid.');
    }
    return Object.freeze({ status: 'prepareRejected', reason: record.reason });
  }
  if (record.status === 'identityRejected') {
    exactFields(
      record,
      ['status', 'reason', 'checkedEdits', 'totalEdits', 'files', 'additionalFiles'],
      'rename preview bridge response',
    );
    if (![
      'targetUnresolved',
      'editUnresolved',
      'mismatchedSymbol',
      'textMismatch',
      'budgetExceeded',
      'providerFailed',
      'providerTimedOut',
    ].includes(record.reason as string)) {
      throw new TypeError('Rename identity rejection reason is invalid.');
    }
    const checkedEdits = safeInteger(record.checkedEdits, 0, 'identityRejected.checkedEdits');
    const totalEdits = safeInteger(record.totalEdits, 1, 'identityRejected.totalEdits');
    if (checkedEdits > totalEdits) {
      throw new TypeError('Rename identity checkedEdits exceeds totalEdits.');
    }
    const files = parseFiles(record.files, 'identityRejected.files');
    const extra = additionalFiles(record.additionalFiles, 'identityRejected.additionalFiles');
    return Object.freeze({
      status: 'identityRejected',
      reason: record.reason as RenameIdentityRejectionReason,
      checkedEdits,
      totalEdits,
      ...(files === undefined ? {} : { files }),
      ...(extra === undefined ? {} : { additionalFiles: extra }),
    });
  }
  if (record.status === 'documentChanged') {
    exactFields(record, ['status', 'reason', 'files', 'additionalFiles'], 'rename preview bridge response');
    if (!['content', 'version', 'existence', 'workspace'].includes(record.reason as string)) {
      throw new TypeError('Rename documentChanged reason is invalid.');
    }
    const files = parseFiles(record.files, 'documentChanged.files');
    const extra = additionalFiles(record.additionalFiles, 'documentChanged.additionalFiles');
    return Object.freeze({
      status: 'documentChanged',
      reason: record.reason as DocumentChangedDetails['reason'],
      ...(files === undefined ? {} : { files }),
      ...(extra === undefined ? {} : { additionalFiles: extra }),
    });
  }
  if (record.status === 'editConflict') {
    exactFields(record, ['status', 'reason', 'files', 'additionalFiles'], 'rename preview bridge response');
    if (![
      'overlappingEdits',
      'rangeOutOfBounds',
      'unsupportedEdit',
      'ambiguousOperationOrder',
    ].includes(record.reason as string)) {
      throw new TypeError('Rename editConflict reason is invalid.');
    }
    const files = parseFiles(record.files, 'editConflict.files');
    const extra = additionalFiles(record.additionalFiles, 'editConflict.additionalFiles');
    return Object.freeze({
      status: 'editConflict',
      reason: record.reason as EditConflictDetails['reason'],
      ...(files === undefined ? {} : { files }),
      ...(extra === undefined ? {} : { additionalFiles: extra }),
    });
  }
  throw new TypeError('Rename preview bridge response status is invalid.');
};
