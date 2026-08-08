import type { Range, TextChange } from './dto.js';
import {
  systemRuntimePrimitives,
  type RuntimePrimitives,
} from './runtime.js';

export const MEMORY_TEXT_ENCODING = 'utf16-code-units' as const;

export interface NormalizedTextEdit {
  readonly range: Range;
  readonly oldText: string;
  readonly newText: string;
  readonly startOffset: number;
  readonly endOffset: number;
  readonly providerOrdinal: number;
}

export interface NormalizedTextChange {
  readonly kind: 'text';
  readonly file: string;
  readonly edits: readonly NormalizedTextEdit[];
}

interface TextDocumentSnapshotBase {
  readonly file: string;
  readonly internalUri: string;
  readonly rootAlias: string;
  readonly boundaryFingerprint: string;
  readonly documentEpoch: number;
  readonly documentVersion: number;
  readonly memoryContentSha256: string;
  readonly eol: 'lf' | 'crlf';
  readonly encoding: typeof MEMORY_TEXT_ENCODING;
  readonly expectedPostContentSha256: string;
}

export type TextDocumentSnapshot = TextDocumentSnapshotBase & (
  | {
      readonly diskExists: true;
      readonly diskByteSha256: string;
    }
  | {
      readonly diskExists: false;
    }
);

export interface NormalizedWorkspaceEdit {
  readonly textChanges: readonly NormalizedTextChange[];
  readonly targets: readonly TextDocumentSnapshot[];
}

export type TextEditInvariantErrorReason =
  | 'invalidRange'
  | 'oldTextMismatch'
  | 'overlappingEdits';

export class TextEditInvariantError extends Error {
  readonly reason: TextEditInvariantErrorReason;

  constructor(reason: TextEditInvariantErrorReason, message: string) {
    super(message);
    this.name = 'TextEditInvariantError';
    this.reason = reason;
  }
}

const compareNumbers = (left: number, right: number): number => left - right;

export const compareNormalizedTextEdits = (
  left: NormalizedTextEdit,
  right: NormalizedTextEdit,
): number => compareNumbers(left.startOffset, right.startOffset) ||
  compareNumbers(left.endOffset, right.endOffset) ||
  compareNumbers(left.providerOrdinal, right.providerOrdinal);

const assertOffset = (value: number, textLength: number): void => {
  if (!Number.isSafeInteger(value) || value < 0 || value > textLength) {
    throw new TextEditInvariantError('invalidRange', 'Text edit offset is outside its snapshot.');
  }
};

const assertEditShape = (
  text: string,
  edit: NormalizedTextEdit,
  ordinals: Set<number>,
): void => {
  assertOffset(edit.startOffset, text.length);
  assertOffset(edit.endOffset, text.length);
  if (edit.startOffset > edit.endOffset) {
    throw new TextEditInvariantError('invalidRange', 'Text edit start is after its end.');
  }
  if (!Number.isSafeInteger(edit.providerOrdinal) || edit.providerOrdinal < 0 ||
      ordinals.has(edit.providerOrdinal)) {
    throw new TextEditInvariantError('invalidRange', 'Text edit provider ordinal is invalid or duplicated.');
  }
  ordinals.add(edit.providerOrdinal);
  if (text.slice(edit.startOffset, edit.endOffset) !== edit.oldText) {
    throw new TextEditInvariantError('oldTextMismatch', 'Text edit oldText does not match its snapshot.');
  }
};

export const sortAndValidateNormalizedTextEdits = (
  text: string,
  edits: readonly NormalizedTextEdit[],
): readonly NormalizedTextEdit[] => {
  const sorted = [...edits].sort(compareNormalizedTextEdits);
  const ordinals = new Set<number>();
  let activeReplacementEnd = -1;
  for (const edit of sorted) {
    assertEditShape(text, edit, ordinals);
    if (activeReplacementEnd > edit.startOffset) {
      throw new TextEditInvariantError(
        'overlappingEdits',
        'Text edits overlap or an insertion is strictly inside a replacement.',
      );
    }
    if (edit.endOffset > edit.startOffset) {
      activeReplacementEnd = edit.endOffset;
    }
  }
  return Object.freeze(sorted);
};

export const simulateNormalizedTextEdits = (
  text: string,
  edits: readonly NormalizedTextEdit[],
): string => {
  const sorted = sortAndValidateNormalizedTextEdits(text, edits);
  const output: string[] = [];
  let cursor = 0;
  let index = 0;
  while (index < sorted.length) {
    const offset = sorted[index]?.startOffset;
    if (offset === undefined) break;
    output.push(text.slice(cursor, offset));

    while (index < sorted.length) {
      const edit = sorted[index];
      if (edit === undefined || edit.startOffset !== offset || edit.endOffset !== offset) break;
      output.push(edit.newText);
      index += 1;
    }

    const replacement = sorted[index];
    if (replacement !== undefined && replacement.startOffset === offset) {
      output.push(replacement.newText);
      cursor = replacement.endOffset;
      index += 1;
    } else {
      cursor = offset;
    }
  }
  output.push(text.slice(cursor));
  return output.join('');
};

const utf16CodeUnitBytes = (text: string): Uint8Array => {
  const bytes = new Uint8Array(text.length * 2);
  for (let index = 0; index < text.length; index += 1) {
    const codeUnit = text.charCodeAt(index);
    bytes[index * 2] = codeUnit & 0xff;
    bytes[index * 2 + 1] = codeUnit >>> 8;
  }
  return bytes;
};

export const sha256Utf16Text = (
  text: string,
  primitives: RuntimePrimitives = systemRuntimePrimitives,
): string => primitives.sha256Hex(utf16CodeUnitBytes(text));

export const publicTextChangesFromNormalized = (
  normalized: NormalizedWorkspaceEdit,
): readonly TextChange[] => Object.freeze(normalized.textChanges.map((change) => Object.freeze({
  kind: 'text' as const,
  file: change.file,
  edits: Object.freeze(change.edits.map((edit) => Object.freeze({
    range: Object.freeze({ ...edit.range }),
    oldText: edit.oldText,
    newText: edit.newText,
  }))),
})));
