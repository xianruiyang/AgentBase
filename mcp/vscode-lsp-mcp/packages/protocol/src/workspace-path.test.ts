import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {
  WorkspaceBoundaryError,
  createWorkspaceId,
  createWorkspacePathContext,
  logicalPathFromProviderLocation,
  normalizeRootAliasBase,
  parseLogicalPath,
  resolveLogicalPath,
  hostPathPlatform,
  systemWorkspacePathAccess,
  systemRuntimePrimitives,
  toPathComparisonKey,
  toPublicWorkspace,
  type PathEntryType,
  type PathPlatform,
  type WorkspaceBoundaryErrorCode,
  type WorkspaceFolderPathInput,
  type WorkspacePathAccess,
  type WorkspacePathContext,
} from './index.js';

interface Entry {
  readonly realpath: string;
  readonly type: PathEntryType;
}

class FakePathAccess implements WorkspacePathAccess {
  readonly #entries = new Map<string, Entry>();
  readonly #platform: PathPlatform;

  constructor(platform: PathPlatform) {
    this.#platform = platform;
  }

  #key(value: string): string {
    const pathApi = path.win32;
    const normalized = pathApi.normalize(value);
    return this.#platform === 'win32' ? normalized.toLowerCase() : normalized;
  }

  add(value: string, type: Exclude<PathEntryType, 'missing'>, realpath = value): this {
    this.#entries.set(this.#key(value), { realpath, type });
    return this;
  }

  entryType(absolutePath: string): Promise<PathEntryType> {
    return Promise.resolve(this.#entries.get(this.#key(absolutePath))?.type ?? 'missing');
  }

  realpath(absolutePath: string): Promise<string> {
    const entry = this.#entries.get(this.#key(absolutePath));
    if (entry === undefined) {
      return Promise.reject(new Error('ENOENT'));
    }
    return Promise.resolve(entry.realpath);
  }
}

const hashPrimitives = {
  sha256Hex: (input: Uint8Array): string => createHash('sha256').update(input).digest('hex'),
};

const folder = (name: string, lexicalAbsolutePath: string): WorkspaceFolderPathInput => ({
  name,
  uriScheme: 'file',
  lexicalAbsolutePath,
});

const contextFor = (
  folders: readonly WorkspaceFolderPathInput[],
  platform: PathPlatform,
  access: WorkspacePathAccess,
): Promise<WorkspacePathContext> =>
  createWorkspacePathContext(folders, platform, access, hashPrimitives);

const assertThrowsCode = (
  action: () => unknown,
  code: WorkspaceBoundaryErrorCode,
): void => {
  assert.throws(action, (error: unknown) => {
    assert.ok(error instanceof WorkspaceBoundaryError);
    assert.equal(error.code, code);
    return true;
  });
};

const assertRejectsCode = async (
  action: () => Promise<unknown>,
  code: WorkspaceBoundaryErrorCode,
): Promise<void> => {
  await assert.rejects(action, (error: unknown) => {
    assert.ok(error instanceof WorkspaceBoundaryError);
    assert.equal(error.code, code);
    return true;
  });
};

test('alias normalization and collision suffixes are deterministic and index-stable', async () => {
  assert.equal(normalizeRootAliasBase('  My Ｐroject  '), 'my-project');
  assert.equal(normalizeRootAliasBase('...'), 'root');
  assert.equal(normalizeRootAliasBase('A'.repeat(80)).length, 40);

  const access = new FakePathAccess('win32')
    .add('C:\\workspace\\a', 'directory')
    .add('C:\\workspace\\b', 'directory');
  const context = await contextFor(
    [folder('Foo', 'C:\\workspace\\a'), folder('Ｆｏｏ', 'C:\\workspace\\b')],
    'win32',
    access,
  );

  assert.equal(context.roots.length, 2);
  assert.match(context.roots[0]?.alias ?? '', /^foo~[0-9a-f]{8,64}$/u);
  assert.match(context.roots[1]?.alias ?? '', /^foo~[0-9a-f]{8,64}$/u);
  assert.notEqual(context.roots[0]?.alias, context.roots[1]?.alias);
  assert.deepEqual(context.roots.map((root) => root.folderIndex), [0, 1]);
  assert.ok(context.roots.every((root) => root.alias.length <= 64));
});

test('unusable roots and duplicate canonical roots fail closed', async () => {
  const access = new FakePathAccess('win32')
    .add('C:\\lexical\\a', 'directory', 'C:\\canonical\\shared')
    .add('C:\\lexical\\b', 'directory', 'C:\\canonical\\shared');

  await assertRejectsCode(() => contextFor([], 'win32', access), 'WORKSPACE_UNAVAILABLE');
  await assertRejectsCode(
    () =>
      contextFor(
        [{ name: 'virtual', uriScheme: 'untitled', lexicalAbsolutePath: 'C:\\virtual' }],
        'win32',
        access,
      ),
    'WORKSPACE_UNAVAILABLE',
  );
  await assertRejectsCode(
    () => contextFor([folder('a', 'C:\\lexical\\a'), folder('b', 'C:\\lexical\\b')], 'win32', access),
    'WORKSPACE_UNAVAILABLE',
  );
});

test('single-root logical and lexical paths round-trip without exposing the alias', async () => {
  const access = new FakePathAccess('win32')
    .add('C:\\workspace', 'directory')
    .add('C:\\workspace\\src\\main.ts', 'file');
  const context = await contextFor([folder('Demo', 'C:\\workspace')], 'win32', access);
  const resolved = await resolveLogicalPath(context, 'src/main.ts', access);
  const reversed = await logicalPathFromProviderLocation(
    context,
    { uriScheme: 'file', lexicalAbsolutePath: 'C:\\workspace\\src\\main.ts' },
    access,
  );

  assert.equal(resolved.lexicalAbsolutePath, 'C:\\workspace\\src\\main.ts');
  assert.equal(resolved.canonicalVerificationPath, 'C:\\workspace\\src\\main.ts');
  assert.equal(resolved.exists, true);
  assert.equal(reversed.logicalPath, 'src/main.ts');
  assertThrowsCode(() => parseLogicalPath(context, 'demo/src/main.ts'), 'INVALID_ARGUMENT');

  const publicWorkspace = toPublicWorkspace(
    createWorkspaceId(systemRuntimePrimitives),
    'Demo workspace',
    context,
  );
  assert.deepEqual(publicWorkspace.roots, ['demo']);
  assert.equal(JSON.stringify(publicWorkspace).includes('C:\\workspace'), false);
  assert.equal(JSON.stringify(publicWorkspace).includes('canonical'), false);
});

test('multi-root paths select exact aliases and reverse-map to the matching root', async () => {
  const access = new FakePathAccess('win32')
    .add('C:\\workspace\\app', 'directory')
    .add('C:\\workspace\\lib', 'directory')
    .add('C:\\workspace\\app\\src\\main.ts', 'file')
    .add('C:\\workspace\\lib\\src\\index.ts', 'file');
  const context = await contextFor(
    [folder('App', 'C:\\workspace\\app'), folder('Library', 'C:\\workspace\\lib')],
    'win32',
    access,
  );

  assert.equal(
    (await resolveLogicalPath(context, 'app/src/main.ts', access)).lexicalAbsolutePath,
    'C:\\workspace\\app\\src\\main.ts',
  );
  assert.equal(
    (
      await logicalPathFromProviderLocation(
        context,
        { uriScheme: 'file', lexicalAbsolutePath: 'C:\\workspace\\lib\\src\\index.ts' },
        access,
      )
    ).logicalPath,
    'library/src/index.ts',
  );
  assertThrowsCode(() => parseLogicalPath(context, 'missing/src/main.ts'), 'ROOT_NOT_FOUND');
  assertThrowsCode(() => parseLogicalPath(context, 'app'), 'INVALID_ARGUMENT');
});

test('Windows logical syntax and comparison reject ambiguous filesystem spellings', async () => {
  const access = new FakePathAccess('win32')
    .add('C:\\Work\\Root', 'directory', 'c:\\work\\root')
    .add('C:\\Work\\Root\\src\\File.ts', 'file', 'c:\\work\\root\\src\\File.ts');
  const context = await contextFor([folder('Project', 'C:\\Work\\Root')], 'win32', access);

  const resolved = await resolveLogicalPath(context, 'src/File.ts', access);
  assert.equal(resolved.lexicalAbsolutePath, 'C:\\Work\\Root\\src\\File.ts');
  assert.equal(
    (
      await logicalPathFromProviderLocation(
        context,
        { uriScheme: 'file', lexicalAbsolutePath: 'c:/WORK/ROOT/src/File.ts' },
        access,
      )
    ).logicalPath,
    'src/File.ts',
  );
  assert.equal(
    toPathComparisonKey('C:/WORK/Root/'),
    toPathComparisonKey('c:\\work\\root'),
  );

  for (const invalid of [
    '',
    '/absolute',
    '//server/share/file.ts',
    'trailing/',
    'double//slash',
    'back\\slash',
    '../escape',
    'dot/./file',
    'C:/absolute.ts',
    'file:/uri.ts',
    'dir/stream:ads',
    'dir/CON.txt',
    'dir/COM¹.log',
    'dir/LPT³',
    'dir/nul',
    'dir/trailing.',
    'dir/trailing ',
    `dir/${String.fromCharCode(0)}bad`,
    `dir/${String.fromCharCode(0xd800)}bad`,
  ]) {
    assertThrowsCode(() => parseLogicalPath(context, invalid), 'INVALID_ARGUMENT');
  }
});

test('canonical containment accepts internal links and rejects cross-root escapes', async () => {
  const access = new FakePathAccess('win32')
    .add('C:\\one', 'directory')
    .add('C:\\two', 'directory')
    .add('C:\\one\\inside-link.ts', 'file', 'C:\\one\\actual.ts')
    .add('C:\\one\\escape-link.ts', 'file', 'C:\\two\\secret.ts');
  const context = await contextFor(
    [folder('One', 'C:\\one'), folder('Two', 'C:\\two')],
    'win32',
    access,
  );

  assert.equal(
    (await resolveLogicalPath(context, 'one/inside-link.ts', access)).canonicalVerificationPath,
    'C:\\one\\actual.ts',
  );
  await assertRejectsCode(
    () => resolveLogicalPath(context, 'one/escape-link.ts', access),
    'PATH_OUTSIDE_WORKSPACE',
  );
});

test('root symlinks and nested roots reverse-map through the most specific canonical root', async () => {
  const rootLinkAccess = new FakePathAccess('win32')
    .add('C:\\lexical\\root', 'directory', 'C:\\real\\root')
    .add('C:\\lexical\\root\\src\\a.ts', 'file', 'C:\\real\\root\\src\\a.ts')
    .add('C:\\real\\root\\src\\a.ts', 'file');
  const rootLinkContext = await contextFor(
    [folder('Linked', 'C:\\lexical\\root')],
    'win32',
    rootLinkAccess,
  );
  assert.equal(
    (
      await logicalPathFromProviderLocation(
        rootLinkContext,
        { uriScheme: 'file', lexicalAbsolutePath: 'C:\\real\\root\\src\\a.ts' },
        rootLinkAccess,
      )
    ).logicalPath,
    'src/a.ts',
  );

  const nestedAccess = new FakePathAccess('win32')
    .add('C:\\work', 'directory')
    .add('C:\\work\\packages\\app', 'directory')
    .add('C:\\work\\packages\\app\\src\\main.ts', 'file');
  const nestedContext = await contextFor(
    [folder('Outer', 'C:\\work'), folder('App', 'C:\\work\\packages\\app')],
    'win32',
    nestedAccess,
  );
  const mapped = await logicalPathFromProviderLocation(
    nestedContext,
    { uriScheme: 'file', lexicalAbsolutePath: 'C:\\work\\packages\\app\\src\\main.ts' },
    nestedAccess,
  );
  assert.equal(mapped.logicalPath, 'app/src/main.ts');
  assert.equal(mapped.rootAlias, 'app');
});

test('Windows junction targets use native realpath and cannot escape the workspace', {
  skip: process.platform !== 'win32',
}, async () => {
  const scratch = await mkdtemp(path.join(tmpdir(), 'vscode-lsp-mcp-junction-'));
  const rootPath = path.join(scratch, 'root');
  const outsidePath = path.join(scratch, 'outside');
  try {
    await Promise.all([
      mkdir(rootPath),
      mkdir(outsidePath),
    ]);
    await writeFile(path.join(outsidePath, 'secret.ts'), 'export const secret = true;');
    await symlink(outsidePath, path.join(rootPath, 'escape'), 'junction');
    const context = await createWorkspacePathContext(
      [folder('Root', rootPath)],
      'win32',
      systemWorkspacePathAccess,
      systemRuntimePrimitives,
    );
    await assertRejectsCode(
      () => resolveLogicalPath(context, 'escape/secret.ts', systemWorkspacePathAccess),
      'PATH_OUTSIDE_WORKSPACE',
    );
  } finally {
    await rm(scratch, { force: true, recursive: true });
  }
});

test('missing create targets validate their nearest existing parent canonically', async () => {
  const access = new FakePathAccess('win32')
    .add('C:\\root', 'directory')
    .add('C:\\root\\new', 'directory')
    .add('C:\\root\\out', 'directory', 'C:\\outside');
  const context = await contextFor([folder('Root', 'C:\\root')], 'win32', access);

  const missing = await resolveLogicalPath(context, 'new/deep/file.ts', access, {
    allowMissing: true,
  });
  assert.equal(missing.exists, false);
  assert.equal(missing.lexicalAbsolutePath, 'C:\\root\\new\\deep\\file.ts');
  assert.equal(missing.canonicalVerificationPath, 'C:\\root\\new');
  await assertRejectsCode(
    () => resolveLogicalPath(context, 'out/file.ts', access, { allowMissing: true }),
    'PATH_OUTSIDE_WORKSPACE',
  );
  await assertRejectsCode(
    () => resolveLogicalPath(context, 'new/deep/file.ts', access),
    'DOCUMENT_NOT_FOUND',
  );
});

test('provider errors remain safe and never echo physical paths', async () => {
  const access = new FakePathAccess('win32')
    .add('C:\\workspace', 'directory')
    .add('C:\\outside\\secret.ts', 'file')
    .add('C:\\outside\\link-in.ts', 'file', 'C:\\workspace\\inside.ts');
  const context = await contextFor([folder('Workspace', 'C:\\workspace')], 'win32', access);

  await assert.rejects(
    () =>
      logicalPathFromProviderLocation(
        context,
        { uriScheme: 'file', lexicalAbsolutePath: 'C:\\outside\\secret.ts' },
        access,
      ),
    (error: unknown) => {
      assert.ok(error instanceof WorkspaceBoundaryError);
      assert.equal(error.code, 'PATH_OUTSIDE_WORKSPACE');
      assert.equal(error.message.includes('C:\\outside'), false);
      assert.equal(error.message.includes('secret.ts'), false);
      return true;
    },
  );
  await assertRejectsCode(
    () =>
      logicalPathFromProviderLocation(
        context,
        { uriScheme: 'untitled', lexicalAbsolutePath: 'C:\\outside\\secret.ts' },
        access,
      ),
    'PATH_OUTSIDE_WORKSPACE',
  );
  await assertRejectsCode(
    () =>
      logicalPathFromProviderLocation(
        context,
        { uriScheme: 'file', lexicalAbsolutePath: 'C:\\outside\\link-in.ts' },
        access,
      ),
    'PATH_OUTSIDE_WORKSPACE',
  );
});

test('the shared Node adapter performs host stat and native canonicalization', async () => {
  const currentDirectory = process.cwd();
  assert.equal(await systemWorkspacePathAccess.entryType(currentDirectory), 'directory');
  const canonical = await systemWorkspacePathAccess.realpath(currentDirectory);
  assert.equal(path.isAbsolute(canonical), true);
  assert.equal(hostPathPlatform, 'win32');
});
