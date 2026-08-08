import type {
  Collection,
  GlobFilterInput,
  ResultWindowInput,
} from './dto.js';

const DEFAULT_WINDOW_SIZE = 20;
const MAX_WINDOW_SIZE = 100;

const assertResultWindow = (
  window: ResultWindowInput,
): { readonly start: number; readonly end: number } => {
  const start = window.resultStart ?? 1;
  const end = window.resultEnd ?? start + DEFAULT_WINDOW_SIZE - 1;
  if (!Number.isSafeInteger(start) || start < 1 || !Number.isSafeInteger(end) || end < 1) {
    throw new RangeError('Result window bounds must be positive safe integers.');
  }
  if (end < start) {
    throw new RangeError('resultEnd must not precede resultStart.');
  }
  if (end - start + 1 > MAX_WINDOW_SIZE) {
    throw new RangeError(`Result window must contain at most ${MAX_WINDOW_SIZE} items.`);
  }
  return { start, end };
};

export const applyResultWindow = <T>(
  candidates: readonly T[],
  window: ResultWindowInput = {},
  warnings: readonly string[] = [],
): Collection<T> => {
  const { start, end } = assertResultWindow(window);
  const frozenWarnings = warnings.length === 0 ? undefined : Object.freeze([...warnings]);
  return Object.freeze({
    results: Object.freeze(candidates.slice(start - 1, end)),
    available: candidates.length,
    ...(frozenWarnings === undefined ? {} : { warnings: frozenWarnings }),
  });
};

const escapeRegularExpressionCharacter = (character: string): string =>
  /[\\^$.*+?()[\]{}|]/u.test(character) ? `\\${character}` : character;

const compileLogicalGlob = (pattern: string): RegExp => {
  if (
    pattern.length === 0 ||
    pattern.includes('\\') ||
    pattern.includes('\u0000') ||
    /[{}()]/u.test(pattern) ||
    pattern.includes('***')
  ) {
    throw new TypeError('Unsupported logical glob.');
  }

  let expression = '^';
  for (let index = 0; index < pattern.length; index += 1) {
    const character = pattern[index] as string;
    if (character === '*') {
      if (pattern[index + 1] === '*') {
        if (pattern[index + 2] === '/') {
          expression += '(?:.*/)?';
          index += 2;
        } else {
          expression += '.*';
          index += 1;
        }
      } else {
        expression += '[^/]*';
      }
      continue;
    }
    if (character === '?') {
      expression += '[^/]';
      continue;
    }
    if (character === '[') {
      const close = pattern.indexOf(']', index + 1);
      if (close < 0) {
        throw new TypeError('Malformed logical glob character class.');
      }
      const raw = pattern.slice(index + 1, close);
      if (raw.length === 0 || raw.includes('[') || raw.includes('/')) {
        throw new TypeError('Malformed logical glob character class.');
      }
      const negated = raw.startsWith('!') || raw.startsWith('^');
      const body = negated ? raw.slice(1) : raw;
      if (body.length === 0) {
        throw new TypeError('Malformed logical glob character class.');
      }
      const escapedBody = body
        .replaceAll('\\', '\\\\')
        .replaceAll(']', '\\]')
        .replace(/^\^/u, '\\^');
      expression += `(?=[^/])[${negated ? '^' : ''}${escapedBody}]`;
      index = close;
      continue;
    }
    if (character === ']') {
      throw new TypeError('Malformed logical glob character class.');
    }
    expression += escapeRegularExpressionCharacter(character);
  }
  expression += '$';
  try {
    return new RegExp(expression, 'u');
  } catch {
    throw new TypeError('Malformed logical glob character class.');
  }
};

export const isSupportedLogicalGlob = (pattern: string): boolean => {
  try {
    compileLogicalGlob(pattern);
    return true;
  } catch {
    return false;
  }
};

const assertLogicalPath = (logicalPath: string): void => {
  if (logicalPath.length === 0 || logicalPath.includes('\\') || logicalPath.includes('\u0000')) {
    throw new TypeError('Logical paths must be non-empty and use forward slashes.');
  }
};

const compileGlobs = (patterns: readonly string[] | undefined): readonly RegExp[] =>
  Object.freeze((patterns ?? []).map(compileLogicalGlob));

const matchesCompiledGlobs = (logicalPath: string, patterns: readonly RegExp[]): boolean =>
  patterns.some((pattern) => pattern.test(logicalPath));

export const matchesLogicalGlobs = (
  logicalPath: string,
  filters: GlobFilterInput = {},
): boolean => {
  assertLogicalPath(logicalPath);
  const includes = compileGlobs(filters.includeGlobs);
  const excludes = compileGlobs(filters.excludeGlobs);
  return (includes.length === 0 || matchesCompiledGlobs(logicalPath, includes)) &&
    !matchesCompiledGlobs(logicalPath, excludes);
};

export const compareTextOrdinal = (left: string, right: string): number =>
  left < right ? -1 : left > right ? 1 : 0;

export interface CandidateCollectionOptions<TSource, TCandidate>
  extends ResultWindowInput, GlobFilterInput {
  readonly normalize: (source: TSource, sourceIndex: number) => TCandidate | undefined;
  readonly filter?: (candidate: TCandidate) => boolean;
  readonly logicalPath?: (candidate: TCandidate) => string;
  readonly dedupeKey: (candidate: TCandidate) => string;
  readonly compare?: (left: TCandidate, right: TCandidate) => number;
  readonly warnings?: readonly string[];
}

export const buildCandidateCollection = <TSource, TCandidate>(
  sources: readonly TSource[],
  options: CandidateCollectionOptions<TSource, TCandidate>,
): Collection<TCandidate> => {
  const includes = compileGlobs(options.includeGlobs);
  const excludes = compileGlobs(options.excludeGlobs);
  const hasGlobFilters = includes.length > 0 || excludes.length > 0;
  if (hasGlobFilters && options.logicalPath === undefined) {
    throw new TypeError('A logicalPath selector is required when glob filters are present.');
  }

  const seen = new Set<string>();
  const candidates: Array<{ readonly candidate: TCandidate; readonly ordinal: number }> = [];
  for (const [sourceIndex, source] of sources.entries()) {
    const candidate = options.normalize(source, sourceIndex);
    if (candidate === undefined || (options.filter !== undefined && !options.filter(candidate))) {
      continue;
    }
    if (hasGlobFilters) {
      const logicalPath = (options.logicalPath as (value: TCandidate) => string)(candidate);
      assertLogicalPath(logicalPath);
      if (
        (includes.length > 0 && !matchesCompiledGlobs(logicalPath, includes)) ||
        matchesCompiledGlobs(logicalPath, excludes)
      ) {
        continue;
      }
    }
    const key = options.dedupeKey(candidate);
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    candidates.push({ candidate, ordinal: candidates.length });
  }

  if (options.compare !== undefined) {
    candidates.sort((left, right) =>
      (options.compare as (a: TCandidate, b: TCandidate) => number)(left.candidate, right.candidate) ||
      left.ordinal - right.ordinal);
  }
  return applyResultWindow(
    candidates.map(({ candidate }) => candidate),
    options,
    options.warnings,
  );
};

export const contextSnippetForLine = (
  text: string,
  line: number,
  contextLines: number,
): string | undefined => {
  if (!Number.isSafeInteger(line) || line < 1) {
    throw new RangeError('line must be a positive safe integer.');
  }
  if (!Number.isSafeInteger(contextLines) || contextLines < 0 || contextLines > 5) {
    throw new RangeError('contextLines must be an integer from 0 through 5.');
  }
  const lines = text.replaceAll('\r\n', '\n').replaceAll('\r', '\n').split('\n');
  if (line > lines.length) {
    throw new RangeError('line exceeds the document line count.');
  }
  if (contextLines === 0) {
    return undefined;
  }
  const hitIndex = line - 1;
  return lines
    .slice(Math.max(0, hitIndex - contextLines), Math.min(lines.length, hitIndex + contextLines + 1))
    .join('\n');
};
