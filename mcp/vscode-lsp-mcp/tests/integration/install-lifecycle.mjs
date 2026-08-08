import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import {
  appendFile,
  cp,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  stat,
  writeFile,
} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  EXTENSION_ID,
  installRelease,
} from '../../scripts/install-core.mjs';

const componentRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const npmCliPath = process.env.npm_execpath;
assert.ok(npmCliPath, 'npm_execpath is required; run through npm.');
const artifactReportPath = process.env.P7_002_REPORT_PATH;
const temporaryRoot = await mkdtemp(path.join(os.tmpdir(), 'vscode-lsp-mcp-p7-002-'));
const installRoot = path.join(temporaryRoot, 'install');
const configRoot = path.join(temporaryRoot, 'config');
const extensionsDir = path.join(temporaryRoot, 'extensions');
const userDataDir = path.join(temporaryRoot, 'user-data');
const defaultReleaseDir = path.join(componentRoot, 'dist');
const baselineReleaseDir = path.join(defaultReleaseDir, 'p7-002-baseline-fixture');
const upgradeReleaseDir = path.join(defaultReleaseDir, 'p7-002-upgrade-fixture');
const failureReleaseDir = path.join(defaultReleaseDir, 'p7-002-failure-fixture');
const codeRoot = path.join(
  componentRoot,
  '.vscode-test',
  'vscode-win32-x64-archive-1.128.0',
);
const codeExecutable = path.join(codeRoot, 'Code.exe');
const codeBin = path.join(codeRoot, 'bin', 'code.cmd');
const installerPath = path.join(defaultReleaseDir, 'install.mjs');
const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');

const runNpm = (script, environment = {}) => {
  const result = spawnSync(process.execPath, [npmCliPath, 'run', script], {
    cwd: componentRoot,
    env: { ...process.env, ...environment },
    encoding: 'utf8',
    windowsHide: true,
  });
  if (result.error) throw result.error;
  assert.equal(result.status, 0, `${script} failed:\n${result.stdout}\n${result.stderr}`);
};

const commonArguments = [
  '--install-root', installRoot,
  '--config-root', configRoot,
  '--code-cli', codeBin,
  '--extensions-dir', extensionsDir,
  '--user-data-dir', userDataDir,
  '--json',
];

const runInstaller = (command, extra = [], expectedStatus = 0) => {
  const result = spawnSync(process.execPath, [installerPath, command, ...extra, ...commonArguments], {
    cwd: temporaryRoot,
    encoding: 'utf8',
    windowsHide: true,
  });
  if (result.error) throw result.error;
  assert.equal(result.status, expectedStatus, result.stderr || result.stdout);
  const stream = expectedStatus === 0 ? result.stdout : result.stderr;
  return JSON.parse(stream.trim());
};

const findCodeCliEntry = async () => {
  for (const entry of await readdir(codeRoot, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const candidate = path.join(codeRoot, entry.name, 'resources', 'app', 'out', 'cli.js');
    try {
      if ((await stat(candidate)).isFile()) return candidate;
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error;
    }
  }
  throw new Error('Unable to find the isolated VS Code cli.js entry.');
};

const listExtensions = async () => {
  const cliEntry = await findCodeCliEntry();
  const result = spawnSync(codeExecutable, [
    cliEntry,
    '--list-extensions',
    '--show-versions',
    '--extensions-dir', extensionsDir,
    '--user-data-dir', userDataDir,
  ], {
    encoding: 'utf8',
    env: { ...process.env, ELECTRON_RUN_AS_NODE: '1', VSCODE_DEV: '' },
    windowsHide: true,
  });
  if (result.error) throw result.error;
  assert.equal(result.status, 0, result.stderr);
  return result.stdout.split(/\r?\n/u).map((line) => line.trim().toLowerCase()).filter(Boolean);
};

const installedServerVersion = () => {
  const launcher = path.join(installRoot, 'bin', 'vscode-lsp-mcp.cjs');
  const result = spawnSync(process.execPath, [launcher, '--version'], {
    cwd: temporaryRoot,
    encoding: 'utf8',
    windowsHide: true,
  });
  if (result.error) throw result.error;
  assert.equal(result.status, 0, result.stderr);
  return result.stdout.trim();
};

const writeTamperedSameVersionRelease = async () => {
  const target = path.join(temporaryRoot, 'same-version-conflict-release');
  await cp(upgradeReleaseDir, target, { recursive: true });
  const manifestPath = path.join(target, 'release-manifest.json');
  const manifest = JSON.parse(await readFile(manifestPath, 'utf8'));
  const server = manifest.artifacts.find(({ type }) => type === 'server-zip');
  assert.ok(server);
  const serverPath = path.join(target, server.name);
  await appendFile(serverPath, Buffer.from([0]));
  const bytes = await readFile(serverPath);
  server.bytes = bytes.length;
  server.sha256 = sha256(bytes);
  await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
  const checksums = manifest.artifacts
    .slice()
    .sort((left, right) => left.name.localeCompare(right.name))
    .map((artifact) => `${artifact.sha256}  ${artifact.name}`)
    .join('\n');
  await writeFile(path.join(target, 'checksums.sha256'), `${checksums}\n`, 'utf8');
  return target;
};

let report;
try {
  if (process.env.P7_002_SKIP_RELEASE_BUILD !== '1') {
    runNpm('release:build');
  }
  runNpm('release:build', {
    VSCODE_LSP_MCP_VERSION: '0.1.0',
    VSCODE_LSP_MCP_OUTPUT_DIR: baselineReleaseDir,
  });
  runNpm('release:build', {
    VSCODE_LSP_MCP_VERSION: '0.1.14',
    VSCODE_LSP_MCP_OUTPUT_DIR: upgradeReleaseDir,
  });
  runNpm('release:build', {
    VSCODE_LSP_MCP_VERSION: '0.1.15',
    VSCODE_LSP_MCP_OUTPUT_DIR: failureReleaseDir,
  });

  const firstInstall = runInstaller('install', ['--release-dir', baselineReleaseDir]);
  assert.equal(firstInstall.outcome, 'installed');
  assert.equal(firstInstall.version, '0.1.0');
  const configPath = path.join(configRoot, 'config.json');
  const config = JSON.parse(await readFile(configPath, 'utf8'));
  config.userMarker = 'preserve-across-upgrade';
  await writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`, 'utf8');
  const preservedConfigBytes = await readFile(configPath);
  const preservedConfigHash = sha256(preservedConfigBytes);

  const idempotentInstall = runInstaller('install', ['--release-dir', baselineReleaseDir]);
  assert.equal(idempotentInstall.outcome, 'unchanged');
  assert.equal(sha256(await readFile(configPath)), preservedConfigHash);
  assert.equal(installedServerVersion(), '0.1.0');
  assert.ok((await listExtensions()).includes(`${EXTENSION_ID}@0.1.0`));

  const backupPath = path.join(temporaryRoot, 'backups', 'user-config.json');
  const backup = runInstaller('backup-config', ['--output', backupPath]);
  assert.equal(backup.sha256, preservedConfigHash);
  const changed = { ...config, userMarker: 'changed-before-restore' };
  await writeFile(configPath, `${JSON.stringify(changed, null, 2)}\n`, 'utf8');
  const restored = runInstaller('restore-config', ['--input', backupPath]);
  assert.equal(restored.sha256, preservedConfigHash);
  assert.deepEqual(await readFile(configPath), preservedConfigBytes);

  const upgraded = runInstaller('install', ['--release-dir', upgradeReleaseDir]);
  assert.equal(upgraded.outcome, 'upgraded');
  assert.equal(upgraded.previousVersion, '0.1.0');
  assert.equal(upgraded.version, '0.1.14');
  assert.equal(sha256(await readFile(configPath)), preservedConfigHash);
  assert.equal(installedServerVersion(), '0.1.14');
  assert.ok((await listExtensions()).includes(`${EXTENSION_ID}@0.1.14`));
  assert.deepEqual(
    (await readdir(path.join(installRoot, 'versions'))).sort(),
    ['0.1.14'],
  );
  const installedManifestText = await readFile(
    path.join(installRoot, 'install-manifest.json'),
    'utf8',
  );
  assert.equal(installedManifestText.toLowerCase().includes(componentRoot.toLowerCase()), false);

  const conflictRelease = await writeTamperedSameVersionRelease();
  const conflict = runInstaller(
    'install',
    ['--release-dir', conflictRelease],
    1,
  );
  assert.equal(conflict.error.code, 'VERSION_HASH_CONFLICT');
  assert.equal(installedServerVersion(), '0.1.14');
  assert.equal(sha256(await readFile(configPath)), preservedConfigHash);

  await assert.rejects(
    installRelease({
      releaseDir: failureReleaseDir,
      installRoot,
      configRoot,
      codeCli: codeBin,
      extensionsDir,
      userDataDir,
    }, {
      afterExtensionInstalled: () => {
        throw new Error('injected failure after extension install');
      },
    }),
    /injected failure after extension install/u,
  );
  assert.equal(installedServerVersion(), '0.1.14');
  assert.ok((await listExtensions()).includes(`${EXTENSION_ID}@0.1.14`));
  assert.equal(sha256(await readFile(configPath)), preservedConfigHash);

  await writeFile(path.join(installRoot, 'foreign.txt'), 'foreign install-root file\n', 'utf8');
  await writeFile(path.join(configRoot, 'foreign.txt'), 'foreign config-root file\n', 'utf8');
  const uninstalled = runInstaller('uninstall');
  assert.equal(uninstalled.outcome, 'uninstalled');
  assert.equal(await readFile(path.join(installRoot, 'foreign.txt'), 'utf8'), 'foreign install-root file\n');
  assert.equal(await readFile(path.join(configRoot, 'foreign.txt'), 'utf8'), 'foreign config-root file\n');
  assert.equal(sha256(await readFile(configPath)), preservedConfigHash);
  assert.equal((await listExtensions()).some((entry) => entry.startsWith(`${EXTENSION_ID}@`)), false);
  assert.equal(runInstaller('uninstall').outcome, 'absent');

  const repeatedInstall = runInstaller('install', ['--release-dir', baselineReleaseDir]);
  assert.equal(repeatedInstall.outcome, 'installed');
  assert.equal(installedServerVersion(), '0.1.0');
  assert.ok((await listExtensions()).includes(`${EXTENSION_ID}@0.1.0`));
  const removeConfig = runInstaller('uninstall', ['--remove-config']);
  assert.equal(removeConfig.outcome, 'uninstalled');
  await assert.rejects(readFile(configPath), { code: 'ENOENT' });
  assert.equal(await readFile(path.join(configRoot, 'foreign.txt'), 'utf8'), 'foreign config-root file\n');
  assert.equal(await readFile(path.join(installRoot, 'foreign.txt'), 'utf8'), 'foreign install-root file\n');
  assert.equal(runInstaller('uninstall').outcome, 'absent');

  report = {
    schemaVersion: 1,
    task: 'P7-002',
    vscodeVersion: '1.128.0',
    initialInstall: firstInstall,
    idempotentInstall,
    backup,
    restored,
    upgraded,
    sameVersionConflict: conflict.error.code,
    rollbackPreservedVersion: '0.1.14',
    freshProcessChecks: {
      serverVersionAfterUpgrade: '0.1.14',
      extensionAfterUpgrade: `${EXTENSION_ID}@0.1.14`,
    },
    firstUninstall: uninstalled,
    repeatedInstall,
    removeConfigUninstall: removeConfig,
    secondUninstall: 'absent',
    foreignInstallRootFilePreserved: true,
    foreignConfigRootFilePreserved: true,
    configurationPreservedAcrossUpgrade: true,
    repositoryAbsolutePathInReleaseManifest: false,
  };
  if (artifactReportPath !== undefined) {
    await mkdir(path.dirname(artifactReportPath), { recursive: true });
    await writeFile(artifactReportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  }
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
} finally {
  try {
    const cliEntry = await findCodeCliEntry();
    spawnSync(codeExecutable, [
      cliEntry,
      '--uninstall-extension', EXTENSION_ID,
      '--extensions-dir', extensionsDir,
      '--user-data-dir', userDataDir,
    ], {
      encoding: 'utf8',
      env: { ...process.env, ELECTRON_RUN_AS_NODE: '1', VSCODE_DEV: '' },
      windowsHide: true,
    });
  } catch {
    // The isolated directory is removed below even if the CLI was never available.
  }
  for (const fixtureReleaseDir of [baselineReleaseDir, upgradeReleaseDir, failureReleaseDir]) {
    const relativeFixture = path.relative(defaultReleaseDir, fixtureReleaseDir);
    assert.ok(relativeFixture.length > 0 && !relativeFixture.startsWith('..') &&
      !path.isAbsolute(relativeFixture));
    await rm(fixtureReleaseDir, { recursive: true, force: true });
  }
  const temporaryPrefix = path.resolve(os.tmpdir()).toLowerCase();
  assert.ok(path.resolve(temporaryRoot).toLowerCase().startsWith(`${temporaryPrefix}${path.sep}`));
  await rm(temporaryRoot, { recursive: true, force: true });
}
