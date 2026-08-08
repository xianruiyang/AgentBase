import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

const componentRoot = path.resolve(import.meta.dirname, '..', '..');
const installer = path.join(componentRoot, 'dist', 'install.mjs');
const root = await mkdtemp(path.join(os.tmpdir(), 'vscode-lsp-mcp-doctor-packaged-'));
const installRoot = path.join(root, 'install');
const configRoot = path.join(root, 'config');
const runtimeRoot = path.join(root, 'runtime');
const packagedVersion = JSON.parse(await readFile(
  path.join(componentRoot, 'dist', 'release-manifest.json'),
  'utf8',
)).version;

const run = (argumentsList) => {
  const result = spawnSync(process.execPath, [installer, ...argumentsList, '--json'], {
    cwd: path.dirname(installer),
    encoding: 'utf8',
    windowsHide: true,
    timeout: 30_000,
    maxBuffer: 1024 * 1024,
  });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stderr, '');
  assert.equal(result.stdout.trim().split(/\r?\n/u).length, 1);
  return JSON.parse(result.stdout);
};

try {
  const common = ['--install-root', installRoot, '--config-root', configRoot];
  const installed = run(['install', ...common, '--skip-extension']);
  assert.equal(installed.outcome, 'installed');

  const doctor = run(['doctor', ...common, '--runtime-root', runtimeRoot]);
  assert.equal(doctor.installation.state, 'installed');
  assert.equal(doctor.installation.version, packagedVersion);
  for (const code of [
    'INSTALL_MANIFEST_VALID',
    'TARGET_MATCH',
    'NODE_VERSION_MATCH',
    'VERSION_IDENTITY_MATCH',
    'SERVER_VERSION_MATCH',
    'CONFIGURATION_VALID',
    'EXTENSION_INSTALL_SKIPPED',
    'NO_REGISTRATIONS',
  ]) {
    assert.ok(doctor.checks.some((check) => check.code === code), `Missing packaged doctor code: ${code}`);
  }
  const log = await readFile(doctor.log.path, 'utf8');
  assert.ok(Buffer.byteLength(log) <= doctor.log.maximumBytes);
  assert.equal(log.includes(componentRoot), false);

  const uninstalled = run(['uninstall', ...common, '--skip-extension', '--remove-config']);
  assert.equal(uninstalled.outcome, 'uninstalled');
  const after = run(['doctor', ...common, '--runtime-root', runtimeRoot]);
  assert.equal(after.installation.state, 'notInstalled');

  const report = {
    schemaVersion: 1,
    task: 'P7-003',
    installedOutcome: installed.outcome,
    doctorStatus: doctor.status,
    installedCodes: doctor.checks.map((check) => check.code),
    uninstallOutcome: uninstalled.outcome,
    afterUninstall: after.installation.state,
    stdoutSingleJson: true,
    logBounded: Buffer.byteLength(log) <= doctor.log.maximumBytes,
    repositoryPathInLog: log.includes(componentRoot),
  };
  if (process.env.P7_003_PACKAGED_REPORT_PATH !== undefined) {
    const reportPath = path.resolve(process.env.P7_003_PACKAGED_REPORT_PATH);
    await mkdir(path.dirname(reportPath), { recursive: true });
    await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`);
  }
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
} finally {
  await rm(root, { recursive: true, force: true });
}
