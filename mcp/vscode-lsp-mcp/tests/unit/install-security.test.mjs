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
  parseCodeLauncherCliRelativePath,
  realPathMatchesManagedLocation,
  validateZipEntryName,
} from '../../scripts/install-core.mjs';
import { parseArguments } from '../../scripts/install.mjs';

test('default install and configuration roots are Windows-only and stay separate', () => {
  const environment = {
    LOCALAPPDATA: 'C:\\Users\\sample\\AppData\\Local',
    APPDATA: 'C:\\Users\\sample\\AppData\\Roaming',
  };
  const windows = defaultRoots({ platform: 'win32', environment, homeDirectory: 'C:\\Users\\sample' });
  assert.notEqual(windows.installRoot, windows.configRoot);
  assert.doesNotThrow(() => assertSeparatedRoots(windows.installRoot, windows.configRoot));
  assert.throws(() => defaultRoots({ platform: 'unsupported', environment }), {
    code: 'UNSUPPORTED_PLATFORM',
  });
});

test('Windows Code CLI discovery prefers executable launchers over the extensionless shell script', () => {
  const located = [
    'C:\\Program Files\\Microsoft VS Code\\bin\\code',
    'C:\\Program Files\\Microsoft VS Code\\bin\\code.cmd',
    'C:\\Program Files\\Microsoft VS Code\\bin\\code.exe',
  ];
  assert.deepEqual(orderLocatedCodeCliPaths(located, 'win32'), [located[1], located[2], located[0]]);
  assert.throws(() => orderLocatedCodeCliPaths(located, 'unsupported'), {
    code: 'UNSUPPORTED_PLATFORM',
  });
});

test('Windows Code launcher selects its active version without executing the command script', () => {
  const launcher = [
    '@echo off',
    'setlocal',
    '"%~dp0..\\Code.exe" "%~dp0..\\110a328ea5\\resources\\app\\out\\cli.js" %*',
    'endlocal',
  ].join('\r\n');
  assert.equal(
    parseCodeLauncherCliRelativePath(launcher),
    '110a328ea5\\resources\\app\\out\\cli.js',
  );
  assert.equal(parseCodeLauncherCliRelativePath(`${launcher}\r\n${launcher}`), undefined);
  assert.equal(
    parseCodeLauncherCliRelativePath('"%~dp0..\\Code.exe" "%~dp0..\\..\\escape\\resources\\app\\out\\cli.js" %*'),
    undefined,
  );
});

test('managed roots reject filesystem/home roots and overlapping configuration', () => {
  assert.throws(() => assertSafeManagedRoot(path.parse(process.cwd()).root), InstallError);
  assert.throws(() => assertSafeManagedRoot(os.homedir()), InstallError);
  assert.throws(
    () => assertSeparatedRoots(path.join(os.tmpdir(), 'install'), path.join(os.tmpdir(), 'install', 'config')),
    { code: 'UNSAFE_ROOTS' },
  );
});

test('Windows managed paths accept 8.3 ancestors but reject an escaped canonical parent', () => {
  const candidate = 'C:\\Users\\RUNNER~1\\AppData\\Local\\Temp\\fixture\\config';
  const canonicalParent = 'C:\\Users\\runneradmin\\AppData\\Local\\Temp\\fixture';
  assert.equal(realPathMatchesManagedLocation({
    candidate,
    actual: path.win32.join(canonicalParent, 'config'),
    canonicalParent,
    platform: 'win32',
  }), true);
  assert.equal(realPathMatchesManagedLocation({
    candidate,
    actual: 'C:\\outside\\config',
    canonicalParent,
    platform: 'win32',
  }), false);
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
