import { realpath as realpathCallback } from 'node:fs';
import { stat } from 'node:fs/promises';
import path from 'node:path';
import type { Workspace } from './dto.js';
import type { RuntimePrimitives } from './runtime.js';
import type { WorkspaceId } from './workspace-identity.js';

declare const logicalPathBrand: unique symbol;
declare const rootAliasBrand: unique symbol;

export type LogicalPath = string & { readonly [logicalPathBrand]: true };
export type RootAlias = string & { readonly [rootAliasBrand]: true };
export type PathPlatform = 'posix' | 'win32';
export type PathEntryType = 'directory' | 'file' | 'missing' | 'other';

export interface WorkspacePathAccess {
  entryType(absolutePath: string): Promise<PathEntryType>;
  realpath(absolutePath: string): Promise<string>;
}

const realpathNative = (absolutePath: string): Promise<string> =>
  new Promise((resolve, reject) => {
    realpathCallback.native(absolutePath, (error, resolvedPath) => {
      if (error === null) {
        resolve(resolvedPath);
      } else {
        reject(new Error('Filesystem canonicalization failed.'));
      }
    });
  });

export const systemWorkspacePathAccess: WorkspacePathAccess = Object.freeze({
  entryType: async (absolutePath: string): Promise<PathEntryType> => {
    try {
      const metadata = await stat(absolutePath);
      if (metadata.isDirectory()) {
        return 'directory';
      }
      if (metadata.isFile()) {
        return 'file';
      }
      return 'other';
    } catch (error) {
      const code = error !== null && typeof error === 'object' && 'code' in error
        ? (error as { readonly code?: unknown }).code
        : undefined;
      if (code === 'ENOENT' || code === 'ENOTDIR') {
        return 'missing';
      }
      throw new Error('Filesystem metadata lookup failed.');
    }
  },
  realpath: realpathNative,
});

export const hostPathPlatform: PathPlatform = process.platform === 'win32' ? 'win32' : 'posix';

export interface WorkspaceFolderPathInput {
  readonly name: string;
  readonly uriScheme: string;
  readonly lexicalAbsolutePath: string;
}

export interface InternalWorkspaceRoot {
  readonly alias: RootAlias;
  readonly name: string;
  readonly folderIndex: number;
  readonly lexicalAbsolutePath: string;
  readonly canonicalAbsolutePath: string;
  readonly lexicalComparisonKey: string;
  readonly canonicalComparisonKey: string;
}

export interface WorkspacePathContext {
  readonly platform: PathPlatform;
  readonly roots: readonly InternalWorkspaceRoot[];
}

export type WorkspaceBoundaryErrorCode =
  | 'DOCUMENT_NOT_FOUND'
  | 'INVALID_ARGUMENT'
  | 'PATH_OUTSIDE_WORKSPACE'
  | 'ROOT_NOT_FOUND'
  | 'WORKSPACE_UNAVAILABLE';

export class WorkspaceBoundaryError extends Error {
  readonly code: WorkspaceBoundaryErrorCode;

  constructor(code: WorkspaceBoundaryErrorCode, message: string) {
    super(message);
    this.name = 'WorkspaceBoundaryError';
    this.code = code;
  }
}

const fail = (code: WorkspaceBoundaryErrorCode, message: string): never => {
  throw new WorkspaceBoundaryError(code, message);
};

const platformPath = (platform: PathPlatform): path.PlatformPath =>
  platform === 'win32' ? path.win32 : path.posix;

const compareCodePoints = (left: string, right: string): number =>
  left < right ? -1 : left > right ? 1 : 0;

const removeTrailingSeparators = (value: string, pathApi: path.PlatformPath): string => {
  const normalized = pathApi.normalize(value);
  const root = pathApi.parse(normalized).root;
  if (normalized === root) {
    return normalized;
  }
  let end = normalized.length;
  while (end > root.length) {
    const character = normalized[end - 1];
    if (character !== '/' && character !== '\\') {
      break;
    }
    end -= 1;
  }
  return normalized.slice(0, end);
};

export const toPathComparisonKey = (absolutePath: string, platform: PathPlatform): string => {
  const pathApi = platformPath(platform);
  if (!pathApi.isAbsolute(absolutePath)) {
    fail('INVALID_ARGUMENT', 'An internal filesystem path must be absolute.');
  }
  const normalized = removeTrailingSeparators(absolutePath, pathApi);
  return platform === 'win32' ? normalized.replaceAll('/', '\\').toLowerCase() : normalized;
};

export const normalizeRootAliasBase = (name: string): string => {
  let base = name
    .normalize('NFKC')
    .trim()
    .replace(/[A-Z]/gu, (character) => character.toLowerCase())
    .replace(/[^a-z0-9._-]+/gu, '-')
    .replace(/-+/gu, '-')
    .replace(/^[._-]+|[._-]+$/gu, '');
  if (base.length > 40) {
    base = base.slice(0, 40).replace(/[._-]+$/gu, '');
  }
  return base === '' || base === '.' || base === '..' ? 'root' : base;
};

interface RootBeforeAlias {
  readonly name: string;
  readonly folderIndex: number;
  readonly lexicalAbsolutePath: string;
  readonly canonicalAbsolutePath: string;
  readonly lexicalComparisonKey: string;
  readonly canonicalComparisonKey: string;
  readonly aliasBase: string;
}

const aliasForCollision = (
  root: RootBeforeAlias,
  used: Set<string>,
  primitives: Pick<RuntimePrimitives, 'sha256Hex'>,
): RootAlias => {
  const hash = primitives.sha256Hex(new TextEncoder().encode(root.canonicalComparisonKey));
  if (!/^[0-9a-f]{64}$/u.test(hash)) {
    throw new Error('Runtime SHA-256 source must return 64 lowercase hexadecimal characters.');
  }
  for (let suffixLength = 8; suffixLength <= hash.length; suffixLength += 2) {
    const suffix = hash.slice(0, suffixLength);
    const base = root.aliasBase.slice(0, 64 - suffix.length - 1).replace(/[._-]+$/gu, '');
    const candidate = `${base === '' ? 'root' : base}~${suffix}`;
    if (!used.has(candidate)) {
      used.add(candidate);
      return candidate as RootAlias;
    }
  }
  throw new Error('Unable to allocate a unique root alias from the canonical root hash.');
};

const assignAliases = (
  roots: readonly RootBeforeAlias[],
  primitives: Pick<RuntimePrimitives, 'sha256Hex'>,
): readonly RootAlias[] => {
  const groups = new Map<string, RootBeforeAlias[]>();
  for (const root of roots) {
    const group = groups.get(root.aliasBase);
    if (group === undefined) {
      groups.set(root.aliasBase, [root]);
    } else {
      group.push(root);
    }
  }

  const aliases = new Array<RootAlias>(roots.length);
  const used = new Set<string>();
  for (const [base, group] of groups) {
    if (group.length === 1) {
      const root = group[0];
      if (root === undefined || used.has(base)) {
        throw new Error('Root alias allocation invariant failed.');
      }
      used.add(base);
      aliases[root.folderIndex] = base as RootAlias;
    }
  }
  for (const group of groups.values()) {
    if (group.length < 2) {
      continue;
    }
    for (const root of [...group].sort((left, right) =>
      compareCodePoints(left.canonicalComparisonKey, right.canonicalComparisonKey),
    )) {
      aliases[root.folderIndex] = aliasForCollision(root, used, primitives);
    }
  }
  if (aliases.some((alias) => alias === undefined)) {
    throw new Error('Root alias allocation did not cover every workspace folder.');
  }
  return Object.freeze(aliases);
};

const inspectWorkspaceRoot = async (
  access: WorkspacePathAccess,
  lexicalAbsolutePath: string,
): Promise<PathEntryType> => {
  try {
    return await access.entryType(lexicalAbsolutePath);
  } catch {
    throw new WorkspaceBoundaryError(
      'WORKSPACE_UNAVAILABLE',
      'A workspace root could not be inspected safely.',
    );
  }
};

export const createWorkspacePathContext = async (
  folders: readonly WorkspaceFolderPathInput[],
  platform: PathPlatform,
  access: WorkspacePathAccess,
  primitives: Pick<RuntimePrimitives, 'sha256Hex'>,
): Promise<WorkspacePathContext> => {
  if (folders.length === 0) {
    fail('WORKSPACE_UNAVAILABLE', 'A usable workspace requires at least one file root.');
  }
  const pathApi = platformPath(platform);
  const roots: RootBeforeAlias[] = [];
  const canonicalKeys = new Set<string>();

  for (const [folderIndex, folder] of folders.entries()) {
    if (folder.uriScheme !== 'file') {
      fail('WORKSPACE_UNAVAILABLE', 'Every usable workspace root must use the file URI scheme.');
    }
    if (!pathApi.isAbsolute(folder.lexicalAbsolutePath)) {
      fail('WORKSPACE_UNAVAILABLE', 'Every usable workspace root must have an absolute path.');
    }
    const lexicalAbsolutePath = removeTrailingSeparators(folder.lexicalAbsolutePath, pathApi);
    const rootType = await inspectWorkspaceRoot(access, lexicalAbsolutePath);
    if (rootType !== 'directory') {
      fail('WORKSPACE_UNAVAILABLE', 'Every usable workspace root must resolve to a directory.');
    }
    let canonicalAbsolutePath: string;
    try {
      canonicalAbsolutePath = removeTrailingSeparators(
        await access.realpath(lexicalAbsolutePath),
        pathApi,
      );
    } catch {
      throw new WorkspaceBoundaryError(
        'WORKSPACE_UNAVAILABLE',
        'A workspace root could not be resolved safely.',
      );
    }
    if (!pathApi.isAbsolute(canonicalAbsolutePath)) {
      fail('WORKSPACE_UNAVAILABLE', 'A canonical workspace root must be absolute.');
    }
    const canonicalComparisonKey = toPathComparisonKey(canonicalAbsolutePath, platform);
    if (canonicalKeys.has(canonicalComparisonKey)) {
      fail('WORKSPACE_UNAVAILABLE', 'Duplicate canonical workspace roots are not usable.');
    }
    canonicalKeys.add(canonicalComparisonKey);
    roots.push({
      name: folder.name,
      folderIndex,
      lexicalAbsolutePath,
      canonicalAbsolutePath,
      lexicalComparisonKey: toPathComparisonKey(lexicalAbsolutePath, platform),
      canonicalComparisonKey,
      aliasBase: normalizeRootAliasBase(folder.name),
    });
  }

  const aliases = assignAliases(roots, primitives);
  return Object.freeze({
    platform,
    roots: Object.freeze(
      roots.map((root) =>
        Object.freeze({
          alias: aliases[root.folderIndex] as RootAlias,
          name: root.name,
          folderIndex: root.folderIndex,
          lexicalAbsolutePath: root.lexicalAbsolutePath,
          canonicalAbsolutePath: root.canonicalAbsolutePath,
          lexicalComparisonKey: root.lexicalComparisonKey,
          canonicalComparisonKey: root.canonicalComparisonKey,
        }),
      ),
    ),
  });
};

const hasUnpairedSurrogate = (value: string): boolean => {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) {
        return true;
      }
      index += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      return true;
    }
  }
  return false;
};

const windowsDevicePattern =
  /^(?:aux|clock\$|com(?:[1-9¹²³])|con|conin\$|conout\$|lpt(?:[1-9¹²³])|nul|prn)(?:\..*)?$/iu;

const assertLogicalSegments = (value: string, platform: PathPlatform): readonly string[] => {
  if (
    value.length === 0 ||
    value.startsWith('/') ||
    value.endsWith('/') ||
    value.includes('//') ||
    value.includes('\\') ||
    /[\u0000-\u001f\u007f]/u.test(value) ||
    hasUnpairedSurrogate(value) ||
    /^[A-Za-z][A-Za-z0-9+.-]*:/u.test(value)
  ) {
    fail('INVALID_ARGUMENT', 'file must be a normalized relative logical path.');
  }
  const segments = value.split('/');
  for (const segment of segments) {
    if (segment === '' || segment === '.' || segment === '..') {
      fail('INVALID_ARGUMENT', 'file contains a forbidden path segment.');
    }
    if (
      platform === 'win32' &&
      (segment.includes(':') || /[. ]$/u.test(segment) || windowsDevicePattern.test(segment))
    ) {
      fail('INVALID_ARGUMENT', 'file contains a path segment that is unsafe on Windows.');
    }
  }
  return Object.freeze(segments);
};

export interface ParsedLogicalPath {
  readonly logicalPath: LogicalPath;
  readonly relativePath: string;
  readonly root: InternalWorkspaceRoot;
  readonly segments: readonly string[];
}

export const parseLogicalPath = (
  context: WorkspacePathContext,
  value: string,
): ParsedLogicalPath => {
  const allSegments = assertLogicalSegments(value, context.platform);
  let root: InternalWorkspaceRoot;
  let segments: readonly string[];
  if (context.roots.length === 1) {
    const onlyRoot = context.roots[0];
    if (onlyRoot === undefined) {
      throw new Error('Workspace root invariant failed.');
    }
    if (allSegments[0] === onlyRoot.alias) {
      fail('INVALID_ARGUMENT', 'Single-root logical paths must not include the root alias.');
    }
    root = onlyRoot;
    segments = allSegments;
  } else {
    const alias = allSegments[0];
    root = context.roots.find((candidate) => candidate.alias === alias) ??
      fail('ROOT_NOT_FOUND', 'The logical path root alias is not registered.');
    if (allSegments.length < 2) {
      fail('INVALID_ARGUMENT', 'A multi-root logical path must identify a file below its root.');
    }
    segments = Object.freeze(allSegments.slice(1));
  }
  return Object.freeze({
    logicalPath: value as LogicalPath,
    relativePath: segments.join('/'),
    root,
    segments,
  });
};

const relativeWithin = (
  rootComparisonKey: string,
  targetComparisonKey: string,
  platform: PathPlatform,
  allowEqual: boolean,
): string | undefined => {
  const pathApi = platformPath(platform);
  const relative = pathApi.relative(rootComparisonKey, targetComparisonKey);
  if (relative === '') {
    return allowEqual ? '' : undefined;
  }
  if (
    pathApi.isAbsolute(relative) ||
    relative === '..' ||
    relative.startsWith(`..${pathApi.sep}`)
  ) {
    return undefined;
  }
  return relative;
};

const safeRealpath = async (
  access: WorkspacePathAccess,
  absolutePath: string,
): Promise<string> => {
  try {
    return await access.realpath(absolutePath);
  } catch {
    return fail('DOCUMENT_NOT_FOUND', 'The requested document could not be resolved.');
  }
};

const safeEntryType = async (
  access: WorkspacePathAccess,
  absolutePath: string,
): Promise<PathEntryType> => {
  try {
    return await access.entryType(absolutePath);
  } catch {
    return fail('DOCUMENT_NOT_FOUND', 'The requested document could not be inspected.');
  }
};

export interface ResolveLogicalPathOptions {
  readonly allowMissing?: boolean;
}

export interface InternalResolvedWorkspacePath {
  readonly canonicalVerificationPath: string;
  readonly exists: boolean;
  readonly lexicalAbsolutePath: string;
  readonly logicalPath: LogicalPath;
  readonly root: InternalWorkspaceRoot;
}

export const resolveLogicalPath = async (
  context: WorkspacePathContext,
  value: string,
  access: WorkspacePathAccess,
  options: ResolveLogicalPathOptions = {},
): Promise<InternalResolvedWorkspacePath> => {
  const parsed = parseLogicalPath(context, value);
  const pathApi = platformPath(context.platform);
  const lexicalAbsolutePath = pathApi.resolve(
    parsed.root.lexicalAbsolutePath,
    ...parsed.segments,
  );
  const lexicalKey = toPathComparisonKey(lexicalAbsolutePath, context.platform);
  if (
    relativeWithin(parsed.root.lexicalComparisonKey, lexicalKey, context.platform, false) ===
    undefined
  ) {
    fail('PATH_OUTSIDE_WORKSPACE', 'The requested path is outside the selected workspace root.');
  }

  const entryType = await safeEntryType(access, lexicalAbsolutePath);
  if (entryType !== 'missing' && entryType !== 'file') {
    fail('DOCUMENT_NOT_FOUND', 'The requested path is not a document.');
  }

  let canonicalVerificationPath: string;
  if (entryType === 'file') {
    canonicalVerificationPath = removeTrailingSeparators(
      await safeRealpath(access, lexicalAbsolutePath),
      pathApi,
    );
    const canonicalKey = toPathComparisonKey(canonicalVerificationPath, context.platform);
    if (
      relativeWithin(
        parsed.root.canonicalComparisonKey,
        canonicalKey,
        context.platform,
        false,
      ) === undefined
    ) {
      fail('PATH_OUTSIDE_WORKSPACE', 'The requested path resolves outside the selected root.');
    }
  } else {
    if (options.allowMissing !== true) {
      fail('DOCUMENT_NOT_FOUND', 'The requested document does not exist.');
    }
    let parent = pathApi.dirname(lexicalAbsolutePath);
    while ((await safeEntryType(access, parent)) === 'missing') {
      const next = pathApi.dirname(parent);
      if (next === parent) {
        fail('DOCUMENT_NOT_FOUND', 'No existing parent directory could be resolved.');
      }
      parent = next;
    }
    if ((await safeEntryType(access, parent)) !== 'directory') {
      fail('DOCUMENT_NOT_FOUND', 'The nearest existing parent is not a directory.');
    }
    canonicalVerificationPath = removeTrailingSeparators(
      await safeRealpath(access, parent),
      pathApi,
    );
    const canonicalKey = toPathComparisonKey(canonicalVerificationPath, context.platform);
    if (
      relativeWithin(
        parsed.root.canonicalComparisonKey,
        canonicalKey,
        context.platform,
        true,
      ) === undefined
    ) {
      fail('PATH_OUTSIDE_WORKSPACE', 'The requested path parent resolves outside the selected root.');
    }
  }

  return Object.freeze({
    canonicalVerificationPath,
    exists: entryType === 'file',
    lexicalAbsolutePath,
    logicalPath: parsed.logicalPath,
    root: parsed.root,
  });
};

export interface ProviderFileLocation {
  readonly lexicalAbsolutePath: string;
  readonly uriScheme: string;
}

export interface ProviderLogicalPath {
  readonly logicalPath: LogicalPath;
  readonly rootAlias: RootAlias;
}

interface ProviderRootCandidate {
  readonly canonicalDepth: number;
  readonly canonicalLength: number;
  readonly relativePath: string;
  readonly root: InternalWorkspaceRoot;
}

const pathDepth = (value: string, pathApi: path.PlatformPath): number =>
  value.split(pathApi.sep).filter((segment) => segment !== '').length;

export const logicalPathFromProviderLocation = async (
  context: WorkspacePathContext,
  location: ProviderFileLocation,
  access: WorkspacePathAccess,
): Promise<ProviderLogicalPath> => {
  if (location.uriScheme !== 'file') {
    fail('PATH_OUTSIDE_WORKSPACE', 'Provider location is not a local workspace file.');
  }
  const pathApi = platformPath(context.platform);
  if (!pathApi.isAbsolute(location.lexicalAbsolutePath)) {
    fail('PATH_OUTSIDE_WORKSPACE', 'Provider location is not an absolute file path.');
  }
  const lexicalAbsolutePath = removeTrailingSeparators(location.lexicalAbsolutePath, pathApi);
  if (await safeEntryType(access, lexicalAbsolutePath) !== 'file') {
    fail('DOCUMENT_NOT_FOUND', 'Provider location does not identify an existing document.');
  }
  const canonicalAbsolutePath = removeTrailingSeparators(
    await safeRealpath(access, lexicalAbsolutePath),
    pathApi,
  );
  const lexicalKey = toPathComparisonKey(lexicalAbsolutePath, context.platform);
  const canonicalKey = toPathComparisonKey(canonicalAbsolutePath, context.platform);
  const candidates: ProviderRootCandidate[] = [];

  for (const root of context.roots) {
    const canonicalContained = relativeWithin(
      root.canonicalComparisonKey,
      canonicalKey,
      context.platform,
      false,
    );
    if (canonicalContained === undefined) {
      continue;
    }
    const lexicalContained = relativeWithin(
      root.lexicalComparisonKey,
      lexicalKey,
      context.platform,
      false,
    );
    const canonicalRelative = pathApi.relative(
      root.canonicalAbsolutePath,
      canonicalAbsolutePath,
    );
    const lexicalRelative = lexicalContained === undefined
      ? undefined
      : pathApi.relative(root.lexicalAbsolutePath, lexicalAbsolutePath);
    if (lexicalRelative === undefined && lexicalKey !== canonicalKey) {
      continue;
    }
    candidates.push({
      canonicalDepth: pathDepth(root.canonicalComparisonKey, pathApi),
      canonicalLength: root.canonicalComparisonKey.length,
      relativePath: lexicalRelative ?? canonicalRelative,
      root,
    });
  }
  const selected = candidates.sort(
    (left, right) =>
      right.canonicalDepth - left.canonicalDepth ||
      right.canonicalLength - left.canonicalLength ||
      compareCodePoints(left.root.alias, right.root.alias),
  )[0] ?? fail('PATH_OUTSIDE_WORKSPACE', 'Provider location resolves outside the workspace.');
  const relativePath = selected.relativePath.split(pathApi.sep).join('/');
  const logical = context.roots.length === 1
    ? relativePath
    : `${selected.root.alias}/${relativePath}`;
  const reparsed = parseLogicalPath(context, logical);
  return Object.freeze({ logicalPath: reparsed.logicalPath, rootAlias: selected.root.alias });
};

export const publicRootAliases = (context: WorkspacePathContext): readonly string[] =>
  Object.freeze(context.roots.map((root) => root.alias));

export const toPublicWorkspace = (
  workspaceId: WorkspaceId,
  name: string,
  context: WorkspacePathContext,
): Workspace => {
  if (name.length === 0) {
    throw new TypeError('Workspace name must not be empty.');
  }
  return Object.freeze({ workspaceId, name, roots: publicRootAliases(context) });
};
