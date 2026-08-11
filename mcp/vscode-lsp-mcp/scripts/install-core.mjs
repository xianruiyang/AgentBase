import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import {
  chmod,
  copyFile,
  lstat,
  mkdir,
  open,
  readFile,
  readdir,
  realpath,
  rename,
  rm,
  rmdir,
  stat,
  writeFile,
} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import yauzl from 'yauzl';

export const COMPONENT_ID = 'vscode-lsp-mcp';
export const EXTENSION_ID = 'simplechat.vscode-lsp-mcp-companion';
export const INSTALL_MANIFEST_NAME = 'install-manifest.json';
const SERVER_ARCHIVE_ROOT = 'vscode-lsp-mcp-server';
const maximumConfigurationBytes = 1024 * 1024;
const managedRootEntries = Object.freeze([
  '.staging',
  'bin',
  'versions',
  INSTALL_MANIFEST_NAME,
]);

export class InstallError extends Error {
  constructor(code, message, options) {
    super(message, options);
    this.name = 'InstallError';
    this.code = code;
  }
}

const fail = (code, message, options) => {
  throw new InstallError(code, message, options);
};

const pathExists = async (candidate) => stat(candidate).then(() => true, (error) => {
  if (error?.code === 'ENOENT') return false;
  throw error;
});

const readJson = async (filePath, code = 'INVALID_JSON') => {
  try {
    return JSON.parse(await readFile(filePath, 'utf8'));
  } catch (error) {
    fail(code, `Unable to read valid JSON: ${filePath}`, { cause: error });
  }
};

const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');
const normalizeSlash = (value) => value.replaceAll('\\', '/');

const parseVersion = (value) => {
  const match = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$/u.exec(value);
  if (match === null) fail('INVALID_VERSION', `Invalid semantic version: ${value}`);
  return match.slice(1, 4).map(Number);
};

export const currentTarget = (platform = process.platform, architecture = process.arch) =>
  `${platform}-${architecture}`;

export const defaultRoots = ({
  platform = process.platform,
  environment = process.env,
  homeDirectory = os.homedir(),
} = {}) => {
  if (platform === 'win32') {
    const dataBase = environment.LOCALAPPDATA ?? path.join(homeDirectory, 'AppData', 'Local');
    const configBase = environment.APPDATA ?? path.join(homeDirectory, 'AppData', 'Roaming');
    return {
      installRoot: path.join(dataBase, 'SimpleChat', COMPONENT_ID),
      configRoot: path.join(configBase, 'SimpleChat', COMPONENT_ID),
    };
  }
  return {
    installRoot: path.join(
      environment.XDG_DATA_HOME ?? path.join(homeDirectory, '.local', 'share'),
      'simplechat',
      COMPONENT_ID,
    ),
    configRoot: path.join(
      environment.XDG_CONFIG_HOME ?? path.join(homeDirectory, '.config'),
      'simplechat',
      COMPONENT_ID,
    ),
  };
};

const isInside = (parent, candidate) => {
  const relative = path.relative(parent, candidate);
  return relative.length === 0 || (!relative.startsWith('..') && !path.isAbsolute(relative));
};

export const assertSeparatedRoots = (installRootValue, configRootValue) => {
  const installRoot = path.resolve(installRootValue);
  const configRoot = path.resolve(configRootValue);
  if (isInside(installRoot, configRoot) || isInside(configRoot, installRoot)) {
    fail('UNSAFE_ROOTS', 'Install and configuration roots must be disjoint.');
  }
  return { installRoot, configRoot };
};

export const assertSafeManagedRoot = (candidate, label = 'managed root') => {
  const resolved = path.resolve(candidate);
  const parsed = path.parse(resolved);
  if (resolved === parsed.root || resolved === path.resolve(os.homedir())) {
    fail('UNSAFE_ROOT', `Refusing to use ${label}: ${resolved}`);
  }
  return resolved;
};

export const assertNoSymlinkComponents = async (candidate) => {
  const resolved = path.resolve(candidate);
  const parsed = path.parse(resolved);
  const segments = path.relative(parsed.root, resolved).split(path.sep).filter(Boolean);
  let current = parsed.root;
  for (const segment of segments) {
    current = path.join(current, segment);
    let info;
    try {
      info = await lstat(current);
    } catch (error) {
      if (error?.code === 'ENOENT') break;
      throw error;
    }
    if (info.isSymbolicLink()) {
      fail('UNSAFE_SYMLINK', `Managed path contains a symlink or junction: ${current}`);
    }
  }
};

export const realPathMatchesManagedLocation = ({
  candidate,
  actual,
  canonicalParent,
  platform = process.platform,
}) => {
  const pathApi = platform === 'win32' ? path.win32 : path.posix;
  const expected = pathApi.resolve(candidate);
  const resolvedActual = pathApi.resolve(actual);
  if (platform !== 'win32') return resolvedActual === expected;
  return pathApi.dirname(resolvedActual).toLowerCase() ===
    pathApi.resolve(canonicalParent).toLowerCase();
};

const assertRealPathMatches = async (candidate) => {
  const expected = path.resolve(candidate);
  await assertNoSymlinkComponents(expected);
  const [actual, canonicalParent] = await Promise.all([
    realpath(expected),
    realpath(path.dirname(expected)),
  ]);
  // Windows realpath expands 8.3 aliases. The component check above rejects
  // links and junctions, so the canonical parent is the stable boundary.
  if (!realPathMatchesManagedLocation({ candidate: expected, actual, canonicalParent })) {
    fail('UNSAFE_REPARSE_POINT', `Managed path resolves outside its canonical parent: ${candidate}`);
  }
};

export const validateZipEntryName = (entryName) => {
  if (entryName.includes('\\')) fail('UNSAFE_ARCHIVE', `ZIP entry uses backslashes: ${entryName}`);
  if (path.posix.isAbsolute(entryName) || path.win32.isAbsolute(entryName)) {
    fail('UNSAFE_ARCHIVE', `ZIP entry is absolute: ${entryName}`);
  }
  const segments = entryName.split('/');
  const effective = segments.filter((segment) => segment.length > 0);
  if (effective.length === 0 || effective.some((segment) => segment === '.' || segment === '..')) {
    fail('UNSAFE_ARCHIVE', `ZIP entry contains an unsafe segment: ${entryName}`);
  }
  if (effective[0] !== SERVER_ARCHIVE_ROOT) {
    fail('UNSAFE_ARCHIVE', `ZIP entry is outside ${SERVER_ARCHIVE_ROOT}: ${entryName}`);
  }
  return effective;
};

export const isZipSymlink = (entry) => {
  const unixMode = (entry.externalFileAttributes >>> 16) & 0xffff;
  return (unixMode & 0o170000) === 0o120000;
};

const parseChecksums = (text) => {
  const result = new Map();
  for (const line of text.split(/\r?\n/u)) {
    if (line.trim().length === 0) continue;
    const match = /^([0-9a-f]{64})[ ]{2}([^/\\]+)$/u.exec(line);
    if (match === null || result.has(match[2])) {
      fail('INVALID_CHECKSUMS', `Invalid checksum line: ${line}`);
    }
    result.set(match[2], match[1]);
  }
  return result;
};

export const validateNodeEngine = (engine) => {
  const match = /^>=(\d+)\.(\d+)\.(\d+) <(\d+)$/u.exec(engine);
  if (match === null) fail('UNSUPPORTED_NODE_ENGINE', `Unsupported Node engine expression: ${engine}`);
  const current = process.versions.node.split('.').slice(0, 3).map(Number);
  const minimum = match.slice(1, 4).map(Number);
  const maximumMajor = Number(match[4]);
  const atLeastMinimum = current[0] > minimum[0] ||
    (current[0] === minimum[0] && current[1] > minimum[1]) ||
    (current[0] === minimum[0] && current[1] === minimum[1] && current[2] >= minimum[2]);
  if (!atLeastMinimum || current[0] >= maximumMajor) {
    fail('NODE_VERSION_MISMATCH', `Node ${process.versions.node} does not satisfy ${engine}.`);
  }
};

export const loadRelease = async (releaseDirectory, expectedTarget = currentTarget()) => {
  const releaseDir = path.resolve(releaseDirectory);
  await assertNoSymlinkComponents(releaseDir);
  const manifest = await readJson(path.join(releaseDir, 'release-manifest.json'), 'INVALID_RELEASE');
  if (manifest.schemaVersion !== 1 || manifest.component !== COMPONENT_ID) {
    fail('INVALID_RELEASE', 'Release manifest identity is invalid.');
  }
  if (!/^\^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$/u.test(manifest.vscodeEngine) ||
      !/^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$/u.test(manifest.mcpSdkVersion)) {
    fail('INVALID_RELEASE', 'Release runtime compatibility metadata is invalid.');
  }
  parseVersion(manifest.version);
  if (manifest.target !== expectedTarget) {
    fail('TARGET_MISMATCH', `Release target ${manifest.target} does not match ${expectedTarget}.`);
  }
  validateNodeEngine(manifest.nodeEngine);
  const versions = Object.values(manifest.packages ?? {});
  if (versions.length !== 4 || versions.some((version) => version !== manifest.version)) {
    fail('VERSION_MISMATCH', 'Release package versions are not unified.');
  }
  const byType = new Map();
  for (const artifact of manifest.artifacts ?? []) {
    if (
      typeof artifact.type !== 'string' ||
      typeof artifact.name !== 'string' ||
      path.basename(artifact.name) !== artifact.name ||
      !/^[0-9a-f]{64}$/u.test(artifact.sha256)
    ) {
      fail('INVALID_RELEASE', 'Release artifact metadata is invalid.');
    }
    byType.set(artifact.type, artifact);
  }
  const extension = byType.get('extension-vsix');
  const server = byType.get('server-zip');
  if (extension === undefined || server === undefined) {
    fail('INVALID_RELEASE', 'Release is missing the VSIX or server ZIP.');
  }
  const checksums = parseChecksums(await readFile(path.join(releaseDir, 'checksums.sha256'), 'utf8'));
  for (const artifact of manifest.artifacts) {
    if (checksums.get(artifact.name) !== artifact.sha256) {
      fail('CHECKSUM_MISMATCH', `Checksum manifest mismatch for ${artifact.name}.`);
    }
    const bytes = await readFile(path.join(releaseDir, artifact.name));
    if (bytes.length !== artifact.bytes || sha256(bytes) !== artifact.sha256) {
      fail('CHECKSUM_MISMATCH', `Artifact checksum mismatch for ${artifact.name}.`);
    }
  }
  return Object.freeze({
    releaseDir,
    manifest,
    extension,
    server,
    extensionPath: path.join(releaseDir, extension.name),
    serverPath: path.join(releaseDir, server.name),
  });
};

const openZip = async (archivePath) => {
  const bytes = await readFile(archivePath);
  return new Promise((resolve, reject) => {
    yauzl.fromBuffer(bytes, { lazyEntries: true }, (error, zip) => {
      if (error) reject(error);
      else resolve(zip);
    });
  });
};

export const extractServerArchive = async (archivePath, destination) => {
  await mkdir(destination, { recursive: true });
  await assertRealPathMatches(destination);
  const zip = await openZip(archivePath);
  const written = [];
  await new Promise((resolve, reject) => {
    let settled = false;
    const rejectOnce = (error) => {
      if (settled) return;
      settled = true;
      zip.close();
      reject(error);
    };
    zip.once('error', rejectOnce);
    zip.once('end', () => {
      if (!settled) {
        settled = true;
        resolve();
      }
    });
    zip.on('entry', (entry) => {
      let segments;
      try {
        segments = validateZipEntryName(entry.fileName);
        if (isZipSymlink(entry)) fail('UNSAFE_ARCHIVE', `ZIP symlink is forbidden: ${entry.fileName}`);
      } catch (error) {
        rejectOnce(error);
        return;
      }
      const target = path.join(destination, ...segments);
      if (!isInside(destination, target)) {
        rejectOnce(new InstallError('UNSAFE_ARCHIVE', `ZIP entry escaped staging: ${entry.fileName}`));
        return;
      }
      if (entry.fileName.endsWith('/')) {
        mkdir(target, { recursive: true }).then(() => zip.readEntry(), rejectOnce);
        return;
      }
      zip.openReadStream(entry, (error, stream) => {
        if (error) {
          rejectOnce(error);
          return;
        }
        const chunks = [];
        stream.on('data', (chunk) => chunks.push(chunk));
        stream.once('error', rejectOnce);
        stream.once('end', () => {
          mkdir(path.dirname(target), { recursive: true })
            .then(() => writeFile(target, Buffer.concat(chunks), { flag: 'wx' }))
            .then(() => {
              written.push(normalizeSlash(path.relative(destination, target)));
              zip.readEntry();
            }, rejectOnce);
        });
      });
    });
    zip.readEntry();
  });
  const required = [
    `${SERVER_ARCHIVE_ROOT}/package.json`,
    `${SERVER_ARCHIVE_ROOT}/versions.json`,
    `${SERVER_ARCHIVE_ROOT}/dist/cli.js`,
    `${SERVER_ARCHIVE_ROOT}/bin/vscode-lsp-mcp`,
    `${SERVER_ARCHIVE_ROOT}/bin/vscode-lsp-mcp.cmd`,
    `${SERVER_ARCHIVE_ROOT}/node_modules/@simplechat/vscode-lsp-mcp-win32-security/build/Release/win32_security.node`,
  ];
  for (const relative of required) {
    if (!written.includes(relative)) fail('INVALID_RELEASE', `Server ZIP is missing ${relative}.`);
  }
  return path.join(destination, SERVER_ARCHIVE_ROOT);
};

const atomicWrite = async (filePath, bytes) => {
  await mkdir(path.dirname(filePath), { recursive: true });
  const temporary = `${filePath}.tmp-${process.pid}-${randomUUID()}`;
  const handle = await open(temporary, 'wx', 0o600);
  try {
    await handle.writeFile(bytes);
    await handle.sync();
  } finally {
    await handle.close();
  }
  try {
    await rename(temporary, filePath);
  } catch (error) {
    await rm(temporary, { force: true });
    throw error;
  }
};

const atomicWriteJson = (filePath, value) =>
  atomicWrite(filePath, Buffer.from(`${JSON.stringify(value, null, 2)}\n`, 'utf8'));

const loadInstalledManifest = async (installRoot) => {
  const filePath = path.join(installRoot, INSTALL_MANIFEST_NAME);
  if (!await pathExists(filePath)) return undefined;
  const manifest = await readJson(filePath, 'INVALID_INSTALL_STATE');
  if (manifest.schemaVersion !== 1 || manifest.component !== COMPONENT_ID) {
    fail('INVALID_INSTALL_STATE', 'Installed manifest identity is invalid.');
  }
  parseVersion(manifest.version);
  return manifest;
};

const defaultConfig = Object.freeze({
  schemaVersion: 1,
  commandPolicy: {
    commands: [],
    tasks: [],
  },
});

const ensureConfiguration = async (configRoot) => {
  await assertNoSymlinkComponents(configRoot);
  await mkdir(configRoot, { recursive: true });
  await assertRealPathMatches(configRoot);
  const configPath = path.join(configRoot, 'config.json');
  if (await pathExists(configPath)) {
    await readJson(configPath, 'INVALID_CONFIGURATION');
    return { path: configPath, created: false };
  }
  try {
    await writeFile(configPath, `${JSON.stringify(defaultConfig, null, 2)}\n`, {
      encoding: 'utf8',
      flag: 'wx',
      mode: 0o600,
    });
    return { path: configPath, created: true };
  } catch (error) {
    if (error?.code !== 'EEXIST') throw error;
    await readJson(configPath, 'INVALID_CONFIGURATION');
    return { path: configPath, created: false };
  }
};

const launcherSource = `'use strict';
const { spawn } = require('node:child_process');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const installRoot = path.resolve(__dirname, '..');
const manifest = JSON.parse(readFileSync(path.join(installRoot, '${INSTALL_MANIFEST_NAME}'), 'utf8'));
if (manifest.schemaVersion !== 1 || manifest.component !== '${COMPONENT_ID}' || !/^(?:0|[1-9]\\d*)\\.(?:0|[1-9]\\d*)\\.(?:0|[1-9]\\d*)(?:-[0-9A-Za-z.-]+)?$/.test(manifest.version)) {
  throw new Error('Invalid vscode-lsp-mcp install manifest.');
}
const entry = path.join(installRoot, 'versions', manifest.version, 'server', 'dist', 'cli.js');
const child = spawn(process.execPath, [entry, ...process.argv.slice(2)], { stdio: 'inherit' });
child.once('error', (error) => { console.error(error.message); process.exitCode = 1; });
child.once('exit', (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  else process.exitCode = code ?? 1;
});
`;

const ensureLaunchers = async (installRoot) => {
  const binRoot = path.join(installRoot, 'bin');
  await mkdir(binRoot, { recursive: true });
  const files = {
    'vscode-lsp-mcp.cjs': launcherSource,
    'vscode-lsp-mcp.cmd': '@echo off\r\nnode "%~dp0vscode-lsp-mcp.cjs" %*\r\n',
    'vscode-lsp-mcp': '#!/usr/bin/env sh\nSCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexec node "$SCRIPT_DIR/vscode-lsp-mcp.cjs" "$@"\n',
  };
  for (const [name, contents] of Object.entries(files)) {
    await atomicWrite(path.join(binRoot, name), Buffer.from(contents, 'utf8'));
  }
  await chmod(path.join(binRoot, 'vscode-lsp-mcp'), 0o755);
};

export const orderLocatedCodeCliPaths = (candidates, platform = process.platform) => {
  if (platform !== 'win32') return [...candidates];
  const executablePriority = (candidate) => {
    switch (path.extname(candidate).toLowerCase()) {
      case '.cmd': return 0;
      case '.bat': return 1;
      case '.exe': return 2;
      case '.com': return 3;
      default: return 4;
    }
  };
  return candidates
    .map((candidate, index) => ({ candidate, index }))
    .sort((left, right) =>
      executablePriority(left.candidate) - executablePriority(right.candidate) || left.index - right.index)
    .map(({ candidate }) => candidate);
};

const deriveCodeExecutable = async (candidate) => {
  const findCliEntry = async (productRoot) => {
    const direct = path.join(productRoot, 'resources', 'app', 'out', 'cli.js');
    if (await pathExists(direct)) return direct;
    const matches = [];
    for (const entry of await readdir(productRoot, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      const nested = path.join(productRoot, entry.name, 'resources', 'app', 'out', 'cli.js');
      if (await pathExists(nested)) matches.push(nested);
    }
    if (matches.length !== 1) {
      fail('CODE_CLI_UNSUPPORTED', `Cannot uniquely locate VS Code cli.js under ${productRoot}.`);
    }
    return matches[0];
  };
  const deriveFromPath = async (resolved) => {
    if (!await pathExists(resolved)) return undefined;
    if (process.platform === 'win32' && /\.(?:cmd|bat)$/iu.test(resolved)) {
      const productRoot = path.resolve(path.dirname(resolved), '..');
      const codeExe = path.join(productRoot, 'Code.exe');
      if (await pathExists(codeExe)) {
        const cliEntry = await findCliEntry(productRoot);
        return {
          command: codeExe,
          prefixArguments: [cliEntry],
          environment: { ELECTRON_RUN_AS_NODE: '1', VSCODE_DEV: '' },
        };
      }
      fail('CODE_CLI_UNSUPPORTED', `Cannot derive Code.exe from ${resolved}.`);
    }
    if (process.platform === 'win32' && path.basename(resolved).toLowerCase() === 'code.exe') {
      const cliEntry = await findCliEntry(path.dirname(resolved));
      return {
        command: resolved,
        prefixArguments: [cliEntry],
        environment: { ELECTRON_RUN_AS_NODE: '1', VSCODE_DEV: '' },
      };
    }
    return { command: resolved, prefixArguments: [], environment: {} };
  };
  if (path.isAbsolute(candidate) || candidate.includes('/') || candidate.includes('\\')) {
    const resolved = await deriveFromPath(path.resolve(candidate));
    if (resolved === undefined) fail('CODE_CLI_NOT_FOUND', `VS Code CLI does not exist: ${candidate}`);
    return resolved;
  }
  const locator = process.platform === 'win32'
    ? spawnSync('where.exe', [candidate], { encoding: 'utf8', windowsHide: true })
    : spawnSync('which', [candidate], { encoding: 'utf8' });
  if (locator.error || locator.status !== 0) fail('CODE_CLI_NOT_FOUND', `VS Code CLI was not found: ${candidate}`);
  const locatedPaths = locator.stdout.split(/\r?\n/u).map((value) => value.trim()).filter(Boolean);
  for (const line of orderLocatedCodeCliPaths(locatedPaths)) {
    const resolved = await deriveFromPath(line);
    if (resolved !== undefined) return resolved;
  }
  fail('CODE_CLI_NOT_FOUND', `VS Code CLI was not found: ${candidate}`);
};

const codeCommonArguments = (options) => [
  ...(options.extensionsDir === undefined ? [] : ['--extensions-dir', path.resolve(options.extensionsDir)]),
  ...(options.userDataDir === undefined ? [] : ['--user-data-dir', path.resolve(options.userDataDir)]),
];

const runCode = async (options, argumentsList) => {
  const launch = await deriveCodeExecutable(options.codeCli ?? process.env.CODE_CLI ?? 'code');
  const result = spawnSync(launch.command, [
    ...launch.prefixArguments,
    ...argumentsList,
    ...codeCommonArguments(options),
  ], {
    encoding: 'utf8',
    env: { ...process.env, ...launch.environment },
    windowsHide: true,
  });
  if (result.error || result.status !== 0) {
    fail(
      'CODE_CLI_FAILED',
      `VS Code CLI failed: ${(result.stderr || result.stdout || result.error?.message || 'unknown error').trim().slice(0, 1000)}`,
      { cause: result.error },
    );
  }
  return result.stdout;
};

const listInstalledExtensions = async (options) => {
  const output = await runCode(options, ['--list-extensions', '--show-versions']);
  return output.split(/\r?\n/u).map((line) => line.trim().toLowerCase()).filter(Boolean);
};

export const getExtensionInstallationStatus = async (inputOptions) => {
  const options = normalizeOptions(inputOptions);
  const entries = await listInstalledExtensions(options);
  const prefix = `${EXTENSION_ID}@`.toLowerCase();
  const selected = entries.find((entry) => entry === EXTENSION_ID || entry.startsWith(prefix));
  return Object.freeze({
    installed: selected !== undefined,
    ...(selected?.startsWith(prefix) === true ? { version: selected.slice(prefix.length) } : {}),
  });
};

const ensureExtensionInstalled = async (options, vsixPath, version) => {
  const expected = `${EXTENSION_ID}@${version}`.toLowerCase();
  const installed = await listInstalledExtensions(options);
  if (installed.includes(expected)) return false;
  await runCode(options, ['--install-extension', vsixPath, '--force']);
  const after = await listInstalledExtensions(options);
  if (!after.includes(expected)) fail('EXTENSION_INSTALL_FAILED', `VS Code did not report ${expected} after install.`);
  return true;
};

const uninstallExtensionIfPresent = async (options) => {
  const installed = await listInstalledExtensions(options);
  if (!installed.some((entry) => entry === EXTENSION_ID || entry.startsWith(`${EXTENSION_ID}@`))) return false;
  await runCode(options, ['--uninstall-extension', EXTENSION_ID]);
  const after = await listInstalledExtensions(options);
  if (after.some((entry) => entry === EXTENSION_ID || entry.startsWith(`${EXTENSION_ID}@`))) {
    fail('EXTENSION_UNINSTALL_FAILED', `VS Code still reports ${EXTENSION_ID} after uninstall.`);
  }
  return true;
};

const validateStagedServer = async (serverRoot, version) => {
  const manifest = await readJson(path.join(serverRoot, 'package.json'), 'INVALID_RELEASE');
  const versions = await readJson(path.join(serverRoot, 'versions.json'), 'INVALID_RELEASE');
  if (manifest.version !== version || Object.values(versions).some((value) => value !== version)) {
    fail('VERSION_MISMATCH', 'Staged server versions do not match the release.');
  }
  const result = spawnSync(process.execPath, [path.join(serverRoot, 'dist', 'cli.js'), '--version'], {
    cwd: serverRoot,
    encoding: 'utf8',
    windowsHide: true,
  });
  if (result.error || result.status !== 0 || result.stdout.trim() !== version) {
    fail('SERVER_VALIDATION_FAILED', `Staged server did not report ${version}.`);
  }
};

const installedIdentityMatches = (installed, release) =>
  installed.version === release.manifest.version &&
  installed.target === release.manifest.target &&
  installed.vscodeEngine === release.manifest.vscodeEngine &&
  installed.mcpSdkVersion === release.manifest.mcpSdkVersion &&
  installed.artifacts?.server?.sha256 === release.server.sha256 &&
  installed.artifacts?.extension?.sha256 === release.extension.sha256;

const installedVersionDirectory = (installRoot, version) =>
  path.join(installRoot, 'versions', version);

const rollbackExtension = async ({ options, installed }) => {
  if (options.skipExtension === true) return;
  if (installed?.extension?.installed === true) {
    const previousVsix = path.join(
      installedVersionDirectory(options.installRoot, installed.version),
      'extension.vsix',
    );
    if (!await pathExists(previousVsix)) fail('ROLLBACK_FAILED', 'Previous VSIX is missing.');
    await ensureExtensionInstalled(options, previousVsix, installed.version);
  } else {
    await uninstallExtensionIfPresent(options);
  }
};

const normalizeOptions = (options) => {
  const roots = defaultRoots();
  const separated = assertSeparatedRoots(
    options.installRoot ?? roots.installRoot,
    options.configRoot ?? roots.configRoot,
  );
  return {
    ...options,
    installRoot: assertSafeManagedRoot(separated.installRoot, 'install root'),
    configRoot: assertSafeManagedRoot(separated.configRoot, 'configuration root'),
  };
};

export const installRelease = async (inputOptions, hooks = {}) => {
  const options = normalizeOptions(inputOptions);
  await Promise.all([
    assertNoSymlinkComponents(options.installRoot),
    assertNoSymlinkComponents(options.configRoot),
    ...managedRootEntries.map((name) => assertNoSymlinkComponents(path.join(options.installRoot, name))),
  ]);
  const release = await loadRelease(options.releaseDir);
  const existing = await loadInstalledManifest(options.installRoot);
  if (existing?.version === release.manifest.version && !installedIdentityMatches(existing, release)) {
    fail('VERSION_HASH_CONFLICT', `Version ${existing.version} is already installed with different bytes.`);
  }
  const configuration = await ensureConfiguration(options.configRoot);
  await mkdir(options.installRoot, { recursive: true });
  await assertRealPathMatches(options.installRoot);
  if (existing !== undefined && installedIdentityMatches(existing, release)) {
    await ensureLaunchers(options.installRoot);
    if (options.skipExtension !== true) {
      await ensureExtensionInstalled(options, release.extensionPath, release.manifest.version);
    }
    return {
      ok: true,
      outcome: 'unchanged',
      version: existing.version,
      configPreserved: true,
    };
  }

  const stagingRoot = path.join(options.installRoot, '.staging');
  const staging = path.join(stagingRoot, randomUUID());
  const extractedRoot = path.join(staging, 'extracted');
  const stagedVersion = path.join(staging, 'version');
  const targetVersion = installedVersionDirectory(options.installRoot, release.manifest.version);
  let promoted = false;
  let committed = false;
  let extensionChanged = false;
  try {
    await mkdir(staging, { recursive: true });
    const stagedServer = await extractServerArchive(release.serverPath, extractedRoot);
    await validateStagedServer(stagedServer, release.manifest.version);
    await mkdir(stagedVersion, { recursive: true });
    await rename(stagedServer, path.join(stagedVersion, 'server'));
    await copyFile(release.extensionPath, path.join(stagedVersion, 'extension.vsix'));
    await atomicWriteJson(path.join(stagedVersion, 'release.json'), {
      schemaVersion: 1,
      version: release.manifest.version,
      target: release.manifest.target,
      vscodeEngine: release.manifest.vscodeEngine,
      mcpSdkVersion: release.manifest.mcpSdkVersion,
      serverSha256: release.server.sha256,
      extensionSha256: release.extension.sha256,
    });
    if (options.skipExtension !== true) {
      extensionChanged = await ensureExtensionInstalled(
        options,
        release.extensionPath,
        release.manifest.version,
      );
    }
    await hooks.afterExtensionInstalled?.({ release, existing });
    if (await pathExists(targetVersion)) {
      fail('VERSION_DIRECTORY_EXISTS', `Unmanaged version directory already exists: ${targetVersion}`);
    }
    await mkdir(path.dirname(targetVersion), { recursive: true });
    await rename(stagedVersion, targetVersion);
    promoted = true;
    await ensureLaunchers(options.installRoot);
    const installed = {
      schemaVersion: 1,
      component: COMPONENT_ID,
      version: release.manifest.version,
      target: release.manifest.target,
      nodeEngine: release.manifest.nodeEngine,
      vscodeEngine: release.manifest.vscodeEngine,
      mcpSdkVersion: release.manifest.mcpSdkVersion,
      artifacts: {
        server: { name: release.server.name, sha256: release.server.sha256 },
        extension: { name: release.extension.name, sha256: release.extension.sha256 },
      },
      extension: {
        id: EXTENSION_ID,
        version: release.manifest.version,
        installed: options.skipExtension !== true,
      },
      config: {
        file: 'config.json',
        createdByInstaller: existing?.config?.createdByInstaller === true || configuration.created,
      },
      managedRootEntries,
    };
    await atomicWriteJson(path.join(options.installRoot, INSTALL_MANIFEST_NAME), installed);
    committed = true;
    const versionsRoot = path.join(options.installRoot, 'versions');
    for (const entry of await readdir(versionsRoot, { withFileTypes: true })) {
      if (entry.name !== installed.version) {
        await rm(path.join(versionsRoot, entry.name), { recursive: true, force: true }).catch(() => undefined);
      }
    }
    return {
      ok: true,
      outcome: existing === undefined ? 'installed' : 'upgraded',
      version: installed.version,
      previousVersion: existing?.version ?? null,
      configPreserved: !configuration.created || existing === undefined,
    };
  } catch (error) {
    if (!committed) {
      if (promoted) await rm(targetVersion, { recursive: true, force: true }).catch(() => undefined);
      if (extensionChanged) {
        try {
          await rollbackExtension({ options, installed: existing });
        } catch (rollbackError) {
          fail('ROLLBACK_FAILED', 'Install failed and extension rollback also failed.', {
            cause: new AggregateError([error, rollbackError]),
          });
        }
      }
      if (existing === undefined) await rm(path.join(options.installRoot, 'bin'), { recursive: true, force: true });
    }
    throw error;
  } finally {
    await rm(staging, { recursive: true, force: true });
    await rmdir(stagingRoot).catch((error) => {
      if (!['ENOENT', 'ENOTEMPTY'].includes(error?.code)) throw error;
    });
  }
};

export const getInstallStatus = async (inputOptions) => {
  const options = normalizeOptions(inputOptions);
  await assertNoSymlinkComponents(options.installRoot);
  const installed = await loadInstalledManifest(options.installRoot);
  if (installed === undefined) return { ok: true, installed: false };
  const serverEntry = path.join(
    installedVersionDirectory(options.installRoot, installed.version),
    'server',
    'dist',
    'cli.js',
  );
  return {
    ok: true,
    installed: true,
    version: installed.version,
    target: installed.target,
    serverPresent: await pathExists(serverEntry),
    extension: installed.extension,
  };
};

const removeManagedEntry = async (installRoot, name) => {
  assert.ok(managedRootEntries.includes(name));
  const target = path.join(installRoot, name);
  if (!await pathExists(target)) return;
  await assertNoSymlinkComponents(target);
  await rm(target, { recursive: true, force: true });
};

export const uninstallRelease = async (inputOptions) => {
  const options = normalizeOptions(inputOptions);
  await Promise.all([
    assertNoSymlinkComponents(options.installRoot),
    assertNoSymlinkComponents(options.configRoot),
  ]);
  const installed = await loadInstalledManifest(options.installRoot);
  if (installed === undefined) {
    return { ok: true, outcome: 'absent', configPreserved: true };
  }
  if (options.skipExtension !== true) await uninstallExtensionIfPresent(options);
  for (const name of managedRootEntries) await removeManagedEntry(options.installRoot, name);
  if (options.removeConfig === true) {
    await rm(path.join(options.configRoot, 'config.json'), { force: true });
    await rmdir(options.configRoot).catch((error) => {
      if (!['ENOENT', 'ENOTEMPTY'].includes(error?.code)) throw error;
    });
  }
  await rmdir(options.installRoot).catch((error) => {
    if (!['ENOENT', 'ENOTEMPTY'].includes(error?.code)) throw error;
  });
  return {
    ok: true,
    outcome: 'uninstalled',
    version: installed.version,
    configPreserved: options.removeConfig !== true,
  };
};

const readConfigBytes = async (filePath) => {
  const info = await stat(filePath);
  if (info.size > maximumConfigurationBytes) fail('CONFIG_TOO_LARGE', 'Configuration exceeds 1 MiB.');
  const bytes = await readFile(filePath);
  try {
    const value = JSON.parse(bytes.toString('utf8'));
    if (value === null || typeof value !== 'object' || Array.isArray(value) || value.schemaVersion !== 1) {
      fail('INVALID_CONFIGURATION', 'Configuration must be a schemaVersion 1 object.');
    }
  } catch (error) {
    if (error instanceof InstallError) throw error;
    fail('INVALID_CONFIGURATION', 'Configuration is not valid JSON.', { cause: error });
  }
  return bytes;
};

export const backupConfiguration = async (inputOptions) => {
  const options = normalizeOptions(inputOptions);
  if (options.output === undefined) fail('MISSING_ARGUMENT', 'backup-config requires --output.');
  const source = path.join(options.configRoot, 'config.json');
  const output = path.resolve(options.output);
  if (source === output) fail('UNSAFE_BACKUP', 'Backup output cannot replace the active configuration.');
  if (isInside(options.installRoot, output)) {
    fail('UNSAFE_BACKUP', 'Backup output cannot be inside the managed install root.');
  }
  await assertNoSymlinkComponents(path.dirname(output));
  const bytes = await readConfigBytes(source);
  await atomicWrite(output, bytes);
  return { ok: true, outcome: 'backed-up', sha256: sha256(bytes), bytes: bytes.length };
};

export const restoreConfiguration = async (inputOptions) => {
  const options = normalizeOptions(inputOptions);
  if (options.input === undefined) fail('MISSING_ARGUMENT', 'restore-config requires --input.');
  const source = path.resolve(options.input);
  await assertNoSymlinkComponents(source);
  const bytes = await readConfigBytes(source);
  await assertNoSymlinkComponents(options.configRoot);
  await mkdir(options.configRoot, { recursive: true });
  await assertRealPathMatches(options.configRoot);
  const target = path.join(options.configRoot, 'config.json');
  let previousBackup = null;
  if (await pathExists(target)) {
    const previous = await readConfigBytes(target);
    const backupRoot = path.join(options.configRoot, 'backups');
    await mkdir(backupRoot, { recursive: true });
    previousBackup = path.join(backupRoot, `config-${sha256(previous)}.json`);
    if (!await pathExists(previousBackup)) await atomicWrite(previousBackup, previous);
  }
  await atomicWrite(target, bytes);
  return {
    ok: true,
    outcome: 'restored',
    sha256: sha256(bytes),
    previousBackup: previousBackup === null ? null : normalizeSlash(path.relative(options.configRoot, previousBackup)),
  };
};
