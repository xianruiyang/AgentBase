import type {
  ApplyFailedDetails,
  DocumentChangedDetails,
  EditConflictDetails,
} from './dto.js';
import {
  MEMORY_TEXT_ENCODING,
  type NormalizedTextEdit,
  type NormalizedWorkspaceEdit,
  type TextDocumentSnapshot,
} from './mutation.js';
import type { WorkspaceRouteIdentity } from './runtime.js';
import { isWorkspaceId } from './workspace-identity.js';

export const MUTATION_APPLY_BRIDGE_METHOD = 'mutation.apply' as const;
export const APPLY_ATTEMPT_TTL_MS = 600_000;
export const APPLY_ATTEMPTS_PER_WORKSPACE = 256;

const applyAttemptIdPattern = /^ap_[A-Za-z0-9_-]{22}$/u;
const sha256Pattern = /^[0-9a-f]{64}$/u;

export interface MutationApplyBridgeRequest {
  readonly workspace: WorkspaceRouteIdentity;
  readonly applyAttemptId: string;
  readonly normalizedEdit: NormalizedWorkspaceEdit;
}

export type MutationApplyBridgeResponse =
  | { readonly status: 'applied'; readonly changedFiles: readonly string[] }
  | { readonly status: 'workspaceChanged' }
  | { readonly status: 'pathOutsideWorkspace' }
  | ({ readonly status: 'documentChanged' } & DocumentChangedDetails)
  | ({ readonly status: 'editConflict' } & EditConflictDetails)
  | ({ readonly status: 'applyFailed' } & ApplyFailedDetails);

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
  const expected = new Set(fields);
  if (Object.keys(value).some((field) => !expected.has(field))) {
    throw new TypeError(`${label} contains an unknown field.`);
  }
};

const nonEmptyString = (value: unknown, label: string): string => {
  if (typeof value !== 'string' || value.length === 0) {
    throw new TypeError(`${label} must be a non-empty string.`);
  }
  return value;
};

const safeInteger = (value: unknown, minimum: number, label: string): number => {
  if (!Number.isSafeInteger(value) || (value as number) < minimum) {
    throw new TypeError(`${label} must be a safe integer at least ${minimum}.`);
  }
  return value as number;
};

const parseRange = (value: unknown, label: string): NormalizedTextEdit['range'] => {
  const record = asRecord(value, label);
  exactFields(record, ['startLine', 'startColumn', 'endLine', 'endColumn'], label);
  return Object.freeze({
    startLine: safeInteger(record.startLine, 1, `${label}.startLine`),
    startColumn: safeInteger(record.startColumn, 1, `${label}.startColumn`),
    endLine: safeInteger(record.endLine, 1, `${label}.endLine`),
    endColumn: safeInteger(record.endColumn, 1, `${label}.endColumn`),
  });
};

const parseTextEdit = (value: unknown, label: string): NormalizedTextEdit => {
  const record = asRecord(value, label);
  exactFields(record, [
    'range',
    'oldText',
    'newText',
    'startOffset',
    'endOffset',
    'providerOrdinal',
  ], label);
  return Object.freeze({
    range: parseRange(record.range, `${label}.range`),
    oldText: typeof record.oldText === 'string'
      ? record.oldText
      : (() => { throw new TypeError(`${label}.oldText must be a string.`); })(),
    newText: typeof record.newText === 'string'
      ? record.newText
      : (() => { throw new TypeError(`${label}.newText must be a string.`); })(),
    startOffset: safeInteger(record.startOffset, 0, `${label}.startOffset`),
    endOffset: safeInteger(record.endOffset, 0, `${label}.endOffset`),
    providerOrdinal: safeInteger(record.providerOrdinal, 0, `${label}.providerOrdinal`),
  });
};

const parseTextChange = (value: unknown, index: number) => {
  const label = `normalizedEdit.textChanges[${index}]`;
  const record = asRecord(value, label);
  exactFields(record, ['kind', 'file', 'edits'], label);
  if (record.kind !== 'text' || !Array.isArray(record.edits) || record.edits.length === 0) {
    throw new TypeError(`${label} must be a non-empty text change.`);
  }
  return Object.freeze({
    kind: 'text' as const,
    file: nonEmptyString(record.file, `${label}.file`),
    edits: Object.freeze(record.edits.map((edit, editIndex) =>
      parseTextEdit(edit, `${label}.edits[${editIndex}]`))),
  });
};

const parseHash = (value: unknown, label: string): string => {
  if (typeof value !== 'string' || !sha256Pattern.test(value)) {
    throw new TypeError(`${label} must be a lowercase SHA-256 digest.`);
  }
  return value;
};

export const parseTextDocumentSnapshot = (
  value: unknown,
  label = 'snapshot',
): TextDocumentSnapshot => {
  const record = asRecord(value, label);
  const commonFields = [
    'file',
    'internalUri',
    'rootAlias',
    'boundaryFingerprint',
    'documentEpoch',
    'documentVersion',
    'memoryContentSha256',
    'eol',
    'encoding',
    'diskExists',
    'expectedPostContentSha256',
  ];
  exactFields(
    record,
    record.diskExists === true ? [...commonFields, 'diskByteSha256'] : commonFields,
    label,
  );
  if (record.eol !== 'lf' && record.eol !== 'crlf') {
    throw new TypeError(`${label}.eol is invalid.`);
  }
  if (record.encoding !== MEMORY_TEXT_ENCODING || typeof record.diskExists !== 'boolean') {
    throw new TypeError(`${label} has an invalid encoding or disk state.`);
  }
  const base = {
    file: nonEmptyString(record.file, `${label}.file`),
    internalUri: nonEmptyString(record.internalUri, `${label}.internalUri`),
    rootAlias: nonEmptyString(record.rootAlias, `${label}.rootAlias`),
    boundaryFingerprint: parseHash(record.boundaryFingerprint, `${label}.boundaryFingerprint`),
    documentEpoch: safeInteger(record.documentEpoch, 1, `${label}.documentEpoch`),
    documentVersion: safeInteger(record.documentVersion, 0, `${label}.documentVersion`),
    memoryContentSha256: parseHash(record.memoryContentSha256, `${label}.memoryContentSha256`),
    eol: record.eol,
    encoding: MEMORY_TEXT_ENCODING,
    expectedPostContentSha256: parseHash(
      record.expectedPostContentSha256,
      `${label}.expectedPostContentSha256`,
    ),
  } as const;
  return record.diskExists
    ? Object.freeze({
        ...base,
        diskExists: true as const,
        diskByteSha256: parseHash(record.diskByteSha256, `${label}.diskByteSha256`),
      })
    : Object.freeze({ ...base, diskExists: false as const });
};

export const parseNormalizedWorkspaceEdit = (
  value: unknown,
  requireNonEmpty = false,
): NormalizedWorkspaceEdit => {
  const record = asRecord(value, 'normalizedEdit');
  exactFields(record, ['textChanges', 'targets'], 'normalizedEdit');
  if (!Array.isArray(record.textChanges) || !Array.isArray(record.targets) ||
      (requireNonEmpty && record.textChanges.length === 0) ||
      record.textChanges.length !== record.targets.length) {
    throw new TypeError('normalizedEdit must contain aligned changes and targets.');
  }
  const textChanges = Object.freeze(record.textChanges.map(parseTextChange));
  const targets = Object.freeze(record.targets.map((target, index) =>
    parseTextDocumentSnapshot(target, `normalizedEdit.targets[${index}]`)));
  const files = new Set<string>();
  for (let index = 0; index < textChanges.length; index += 1) {
    const change = textChanges[index]!;
    const target = targets[index]!;
    if (change.file !== target.file || files.has(change.file)) {
      throw new TypeError('normalizedEdit targets are misaligned or duplicated.');
    }
    files.add(change.file);
  }
  return Object.freeze({ textChanges, targets });
};

export const parseMutationApplyBridgeRequest = (value: unknown): MutationApplyBridgeRequest => {
  const record = asRecord(value, 'mutation apply bridge request');
  exactFields(record, ['workspace', 'applyAttemptId', 'normalizedEdit'], 'mutation apply bridge request');
  const workspace = asRecord(record.workspace, 'mutation apply bridge request.workspace');
  exactFields(workspace, ['workspaceId', 'generation'], 'mutation apply bridge request.workspace');
  if (typeof workspace.workspaceId !== 'string' || !isWorkspaceId(workspace.workspaceId) ||
      typeof record.applyAttemptId !== 'string' || !applyAttemptIdPattern.test(record.applyAttemptId)) {
    throw new TypeError('Mutation apply bridge identity is invalid.');
  }
  return Object.freeze({
    workspace: Object.freeze({
      workspaceId: workspace.workspaceId,
      generation: safeInteger(workspace.generation, 1, 'workspace.generation'),
    }),
    applyAttemptId: record.applyAttemptId,
    normalizedEdit: parseNormalizedWorkspaceEdit(record.normalizedEdit, true),
  });
};

const parseFiles = (value: unknown, label: string, required: boolean): readonly string[] | undefined => {
  if (value === undefined && !required) return undefined;
  if (!Array.isArray(value) || (required && value.length === 0) || value.length > 100 ||
      value.some((file) => typeof file !== 'string' || file.length === 0)) {
    throw new TypeError(`${label} is invalid.`);
  }
  const files = Object.freeze((value as string[]).map((file) => file));
  if (new Set(files).size !== files.length) throw new TypeError(`${label} contains duplicates.`);
  return files;
};

const parseAdditionalFiles = (value: unknown, label: string): number | undefined =>
  value === undefined ? undefined : safeInteger(value, 1, label);

export const parseMutationApplyBridgeResponse = (value: unknown): MutationApplyBridgeResponse => {
  const record = asRecord(value, 'mutation apply bridge response');
  if (record.status === 'applied') {
    exactFields(record, ['status', 'changedFiles'], 'mutation apply bridge response');
    const changedFiles = parseFiles(record.changedFiles, 'changedFiles', true)!;
    return Object.freeze({ status: 'applied', changedFiles });
  }
  if (record.status === 'workspaceChanged' || record.status === 'pathOutsideWorkspace') {
    exactFields(record, ['status'], 'mutation apply bridge response');
    return Object.freeze({ status: record.status });
  }
  if (record.status === 'documentChanged') {
    exactFields(record, ['status', 'reason', 'files', 'additionalFiles'], 'mutation apply bridge response');
    if (!['content', 'version', 'existence', 'workspace'].includes(record.reason as string)) {
      throw new TypeError('documentChanged reason is invalid.');
    }
    const files = parseFiles(record.files, 'documentChanged.files', false);
    const additionalFiles = parseAdditionalFiles(record.additionalFiles, 'documentChanged.additionalFiles');
    return Object.freeze({
      status: 'documentChanged',
      reason: record.reason as DocumentChangedDetails['reason'],
      ...(files === undefined ? {} : { files }),
      ...(additionalFiles === undefined ? {} : { additionalFiles }),
    });
  }
  if (record.status === 'editConflict') {
    exactFields(record, ['status', 'reason', 'files', 'additionalFiles'], 'mutation apply bridge response');
    if (![
      'overlappingEdits',
      'rangeOutOfBounds',
      'unsupportedEdit',
      'ambiguousOperationOrder',
    ].includes(record.reason as string)) {
      throw new TypeError('editConflict reason is invalid.');
    }
    const files = parseFiles(record.files, 'editConflict.files', false);
    const additionalFiles = parseAdditionalFiles(record.additionalFiles, 'editConflict.additionalFiles');
    return Object.freeze({
      status: 'editConflict',
      reason: record.reason as EditConflictDetails['reason'],
      ...(files === undefined ? {} : { files }),
      ...(additionalFiles === undefined ? {} : { additionalFiles }),
    });
  }
  if (record.status === 'applyFailed') {
    exactFields(record, ['status', 'stage', 'outcome'], 'mutation apply bridge response');
    const valid = (record.stage === 'apply' &&
      (record.outcome === 'notApplied' || record.outcome === 'unknown')) ||
      (record.stage === 'readback' && record.outcome === 'postconditionFailed');
    if (!valid) throw new TypeError('applyFailed stage/outcome is invalid.');
    return Object.freeze({
      status: 'applyFailed',
      stage: record.stage as ApplyFailedDetails['stage'],
      outcome: record.outcome as ApplyFailedDetails['outcome'],
    });
  }
  throw new TypeError('Mutation apply bridge response status is invalid.');
};
