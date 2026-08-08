import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdir, mkdtemp, rm, stat, symlink } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {
  InstallError,
  assertNoSymlinkComponents,
  assertSafeManagedRoot,
  assertSeparatedRoots,
  defaultRoots,
  isZipSymlink,
  orderLocatedCodeCliPaths,
  validateZipEntryName,
} from '../../scripts/install-core.mjs';
import { parseArguments } from '../../scripts/install.mjs';

test('default install and configuration roots stay separate on every supported host family', () => {
  const environment = {
    LOCALAPPDATA: 'C:\\Users\\sample\\AppData\\Local',
    APPDATA: 'C:\\Users\\sample\\AppData\\Roaming',
    XDG_DATA_HOME: '/home/sample/.data',
    XDG_CONFIG_HOME: '/home/sample/.config-custom',
  };
  const windows = defaultRoots({ platform: 'win32', environment, homeDirectory: 'C:\\Users\\sample' });
  const linux = defaultRoots({ platform: 'linux', environment, homeDirectory: '/home/sample' });
  const mac = defaultRoots({ platform: 'darwin', environment, homeDirectory: '/Users/sample' });
  assert.notEqual(windows.installRoot, windows.configRoot);
  assert.deepEqual(linux, mac);
  assert.doesNotThrow(() => assertSeparatedRoots(windows.installRoot, windows.configRoot));
  assert.doesNotThrow(() => assertSeparatedRoots(linux.installRoot, linux.configRoot));
});

test('Windows Code CLI discovery prefers executable launchers over the extensionless shell script', () => {
  const located = [
    'C:\\Program Files\\Microsoft VS Code\\bin\\code',
    'C:\\Program Files\\Microsoft VS Code\\bin\\code.cmd',
    'C:\\Program Files\\Microsoft VS Code\\bin\\code.exe',
  ];
  assert.deepEqual(orderLocatedCodeCliPaths(located, 'win32'), [located[1], located[2], located[0]]);
  assert.deepEqual(orderLocatedCodeCliPaths(located, 'linux'), located);
});

test('managed roots reject filesystem/home roots and overlapping configuration', () => {
  assert.throws(() => assertSafeManagedRoot(path.parse(process.cwd()).root), InstallError);
  assert.throws(() => assertSafeManagedRoot(os.homedir()), InstallError);
  assert.throws(
    () => assertSeparatedRoots(path.join(os.tmpdir(), 'install'), path.join(os.tmpdir(), 'install', 'config')),
    { code: 'UNSAFE_ROOTS' },
  );
});

test('server ZIP entry validation rejects traversal, absolute paths, backslashes, and extra roots', () => {
  assert.deepEqual(
    validateZipEntryName('vscode-lsp-mcp-server/dist/cli.js'),
    ['vscode-lsp-mcp-server', 'dist', 'cli.js'],
  );
  for (const value of [
    '../escape',
    '/absolute/file',
    'C:/absolute/file',
    'vscode-lsp-mcp-server/../escape',
    'vscode-lsp-mcp-server\\dist\\cli.js',
    'other-root/file',
  ]) {
    assert.throws(() => validateZipEntryName(value), { code: 'UNSAFE_ARCHIVE' });
  }
  assert.equal(isZipSymlink({ externalFileAttributes: (0o120777 << 16) >>> 0 }), true);
  assert.equal(isZipSymlink({ externalFileAttributes: (0o100644 << 16) >>> 0 }), false);
});

test('managed path checks reject symlink and junction components', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'vscode-lsp-mcp-install-security-'));
  const real = path.join(root, 'real');
  const link = path.join(root, 'link');
  try {
    await mkdir(real);
    await symlink(real, link, process.platform === 'win32' ? 'junction' : 'dir');
    await assert.rejects(assertNoSymlinkComponents(path.join(link, 'child')), {
      code: 'UNSAFE_SYMLINK',
    });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('installer argument parser is strict and non-interactive', () => {
  assert.deepEqual(parseArguments([
    'install',
    '--release-dir',
    'release',
    '--skip-extension',
    '--json',
  ]), {
    command: 'install',
    options: {
      'release-dir': 'release',
      'skip-extension': true,
      json: true,
    },
  });
  assert.throws(() => parseArguments(['install', '--unknown']), { code: 'INVALID_ARGUMENT' });
  assert.throws(() => parseArguments(['install', '--release-dir']), { code: 'MISSING_ARGUMENT' });
  assert.deepEqual(parseArguments([
    'doctor',
    '--workspace-id',
    'workspace-id',
    '--file',
    'root/src/example.ts',
    '--json',
  ]), {
    command: 'doctor',
    options: {
      'workspace-id': 'workspace-id',
      file: 'root/src/example.ts',
      json: true,
    },
  });
});

test('doctor CLI keeps stdout to one machine-readable result and writes diagnostics to a file', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'vscode-lsp-mcp-doctor-cli-'));
  try {
    const result = spawnSync(process.execPath, [
      path.join(process.cwd(), 'scripts', 'install.mjs'),
      'doctor',
      '--install-root',
      path.join(root, 'install'),
      '--config-root',
      path.join(root, 'config'),
      '--runtime-root',
      path.join(root, 'runtime'),
      '--json',
    ], {
      cwd: process.cwd(),
      encoding: 'utf8',
      windowsHide: true,
    });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stderr, '');
    const lines = result.stdout.trim().split(/\r?\n/u);
    assert.equal(lines.length, 1);
    const report = JSON.parse(lines[0]);
    assert.equal(report.kind, 'doctor');
    assert.equal(report.installation.state, 'notInstalled');
    assert.equal((await stat(report.log.path)).isFile(), true);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
