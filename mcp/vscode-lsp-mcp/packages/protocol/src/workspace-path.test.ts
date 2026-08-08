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
    const pathApi = this.#platform === 'win32' ? path.win32 : path.posix;
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

  const access = new FakePathAccess('posix')
    .add('/workspace/a', 'directory')
    .add('/workspace/b', 'directory');
  const context = await contextFor(
    [folder('Foo', '/workspace/a'), folder('Ｆｏｏ', '/workspace/b')],
    'posix',
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
  const access = new FakePathAccess('posix')
    .add('/lexical/a', 'directory', '/canonical/shared')
    .add('/lexical/b', 'directory', '/canonical/shared');

  await assertRejectsCode(() => contextFor([], 'posix', access), 'WORKSPACE_UNAVAILABLE');
  await assertRejectsCode(
    () =>
      contextFor(
        [{ name: 'virtual', uriScheme: 'untitled', lexicalAbsolutePath: '/virtual' }],
        'posix',
        access,
      ),
    'WORKSPACE_UNAVAILABLE',
  );
  await assertRejectsCode(
    () => contextFor([folder('a', '/lexical/a'), folder('b', '/lexical/b')], 'posix', access),
    'WORKSPACE_UNAVAILABLE',
  );
});

test('single-root logical and lexical paths round-trip without exposing the alias', async () => {
  const access = new FakePathAccess('posix')
    .add('/workspace', 'directory')
    .add('/workspace/src/main.ts', 'file');
  const context = await contextFor([folder('Demo', '/workspace')], 'posix', access);
  const resolved = await resolveLogicalPath(context, 'src/main.ts', access);
  const reversed = await logicalPathFromProviderLocation(
    context,
    { uriScheme: 'file', lexicalAbsolutePath: '/workspace/src/main.ts' },
    access,
  );

  assert.equal(resolved.lexicalAbsolutePath, '/workspace/src/main.ts');
  assert.equal(resolved.canonicalVerificationPath, '/workspace/src/main.ts');
  assert.equal(resolved.exists, true);
  assert.equal(reversed.logicalPath, 'src/main.ts');
  assertThrowsCode(() => parseLogicalPath(context, 'demo/src/main.ts'), 'INVALID_ARGUMENT');

  const publicWorkspace = toPublicWorkspace(
    createWorkspaceId(systemRuntimePrimitives),
    'Demo workspace',
    context,
  );
  assert.deepEqual(publicWorkspace.roots, ['demo']);
  assert.equal(JSON.stringify(publicWorkspace).includes('/workspace'), false);
  assert.equal(JSON.stringify(publicWorkspace).includes('canonical'), false);
});

test('multi-root paths select exact aliases and reverse-map to the matching root', async () => {
  const access = new FakePathAccess('posix')
    .add('/workspace/app', 'directory')
    .add('/workspace/lib', 'directory')
    .add('/workspace/app/src/main.ts', 'file')
    .add('/workspace/lib/src/index.ts', 'file');
  const context = await contextFor(
    [folder('App', '/workspace/app'), folder('Library', '/workspace/lib')],
    'posix',
    access,
  );

  assert.equal(
    (await resolveLogicalPath(context, 'app/src/main.ts', access)).lexicalAbsolutePath,
    '/workspace/app/src/main.ts',
  );
  assert.equal(
    (
      await logicalPathFromProviderLocation(
        context,
        { uriScheme: 'file', lexicalAbsolutePath: '/workspace/lib/src/index.ts' },
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
    toPathComparisonKey('C:/WORK/Root/', 'win32'),
    toPathComparisonKey('c:\\work\\root', 'win32'),
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
  const access = new FakePathAccess('posix')
    .add('/one', 'directory')
    .add('/two', 'directory')
    .add('/one/inside-link.ts', 'file', '/one/actual.ts')
    .add('/one/escape-link.ts', 'file', '/two/secret.ts');
  const context = await contextFor(
    [folder('One', '/one'), folder('Two', '/two')],
    'posix',
    access,
  );

  assert.equal(
    (await resolveLogicalPath(context, 'one/inside-link.ts', access)).canonicalVerificationPath,
    '/one/actual.ts',
  );
  await assertRejectsCode(
    () => resolveLogicalPath(context, 'one/escape-link.ts', access),
    'PATH_OUTSIDE_WORKSPACE',
  );
});

test('root symlinks and nested roots reverse-map through the most specific canonical root', async () => {
  const rootLinkAccess = new FakePathAccess('posix')
    .add('/lexical/root', 'directory', '/real/root')
    .add('/lexical/root/src/a.ts', 'file', '/real/root/src/a.ts')
    .add('/real/root/src/a.ts', 'file');
  const rootLinkContext = await contextFor(
    [folder('Linked', '/lexical/root')],
    'posix',
    rootLinkAccess,
  );
  assert.equal(
    (
      await logicalPathFromProviderLocation(
        rootLinkContext,
        { uriScheme: 'file', lexicalAbsolutePath: '/real/root/src/a.ts' },
        rootLinkAccess,
      )
    ).logicalPath,
    'src/a.ts',
  );

  const nestedAccess = new FakePathAccess('posix')
    .add('/work', 'directory')
    .add('/work/packages/app', 'directory')
    .add('/work/packages/app/src/main.ts', 'file');
  const nestedContext = await contextFor(
    [folder('Outer', '/work'), folder('App', '/work/packages/app')],
    'posix',
    nestedAccess,
  );
  const mapped = await logicalPathFromProviderLocation(
    nestedContext,
    { uriScheme: 'file', lexicalAbsolutePath: '/work/packages/app/src/main.ts' },
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
  const access = new FakePathAccess('posix')
    .add('/root', 'directory')
    .add('/root/new', 'directory')
    .add('/root/out', 'directory', '/outside');
  const context = await contextFor([folder('Root', '/root')], 'posix', access);

  const missing = await resolveLogicalPath(context, 'new/deep/file.ts', access, {
    allowMissing: true,
  });
  assert.equal(missing.exists, false);
  assert.equal(missing.lexicalAbsolutePath, '/root/new/deep/file.ts');
  assert.equal(missing.canonicalVerificationPath, '/root/new');
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
  const access = new FakePathAccess('posix')
    .add('/workspace', 'directory')
    .add('/outside/secret.ts', 'file')
    .add('/outside/link-in.ts', 'file', '/workspace/inside.ts');
  const context = await contextFor([folder('Workspace', '/workspace')], 'posix', access);

  await assert.rejects(
    () =>
      logicalPathFromProviderLocation(
        context,
        { uriScheme: 'file', lexicalAbsolutePath: '/outside/secret.ts' },
        access,
      ),
    (error: unknown) => {
      assert.ok(error instanceof WorkspaceBoundaryError);
      assert.equal(error.code, 'PATH_OUTSIDE_WORKSPACE');
      assert.equal(error.message.includes('/outside'), false);
      assert.equal(error.message.includes('secret.ts'), false);
      return true;
    },
  );
  await assertRejectsCode(
    () =>
      logicalPathFromProviderLocation(
        context,
        { uriScheme: 'untitled', lexicalAbsolutePath: '/outside/secret.ts' },
        access,
      ),
    'PATH_OUTSIDE_WORKSPACE',
  );
  await assertRejectsCode(
    () =>
      logicalPathFromProviderLocation(
        context,
        { uriScheme: 'file', lexicalAbsolutePath: '/outside/link-in.ts' },
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
  assert.equal(hostPathPlatform, process.platform === 'win32' ? 'win32' : 'posix');
});
