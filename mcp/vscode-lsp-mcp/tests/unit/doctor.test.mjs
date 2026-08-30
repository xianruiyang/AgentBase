import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {
  BridgeTransportError,
  IPC_PROTOCOL_VERSION,
  REGISTRY_VERSION,
  createInstanceId,
  createRegistrationSecrets,
  createWorkspaceId,
  systemRuntimePrimitives,
} from '../../packages/protocol/dist/index.js';
import { defaultRuntimeRoot, runDoctor } from '../../scripts/doctor-core.mjs';

const sha256 = (value) => createHash('sha256').update(value).digest('hex');

const createInstalledFixture = async (root, version = '0.1.0') => {
  const installRoot = path.join(root, 'install');
  const configRoot = path.join(root, 'config');
  const versionRoot = path.join(installRoot, 'versions', version);
  const serverRoot = path.join(versionRoot, 'server');
  const extensionBytes = Buffer.from('fixture-vsix');
  const extensionSha256 = sha256(extensionBytes);
  const serverSha256 = sha256('fixture-server-archive');
  await Promise.all([
    mkdir(path.join(serverRoot, 'dist'), { recursive: true }),
    mkdir(path.join(installRoot, 'bin'), { recursive: true }),
    mkdir(configRoot, { recursive: true }),
  ]);
  const manifest = {
    schemaVersion: 1,
    component: 'vscode-lsp-mcp',
    version,
    target: `${process.platform}-${process.arch}`,
    nodeEngine: '>=22.9.0 <27',
    vscodeEngine: '^1.125.0',
    mcpSdkVersion: '1.29.0',
    artifacts: {
      server: { name: `server-${version}.zip`, sha256: serverSha256 },
      extension: { name: `extension-${version}.vsix`, sha256: extensionSha256 },
    },
    extension: { id: 'simplechat.vscode-lsp-mcp-companion', version, installed: true },
    config: { file: 'config.json', createdByInstaller: true },
    managedRootEntries: ['.staging', 'bin', 'versions', 'install-manifest.json'],
  };
  await Promise.all([
    writeFile(path.join(installRoot, 'install-manifest.json'), `${JSON.stringify(manifest)}\n`),
    writeFile(path.join(serverRoot, 'package.json'), `${JSON.stringify({ version })}\n`),
    writeFile(path.join(serverRoot, 'versions.json'), `${JSON.stringify({ server: version, protocol: version })}\n`),
    writeFile(path.join(serverRoot, 'dist', 'cli.js'), `process.stdout.write(${JSON.stringify(version)});\n`),
    writeFile(path.join(versionRoot, 'release.json'), `${JSON.stringify({
      schemaVersion: 1,
      version,
      target: manifest.target,
      vscodeEngine: manifest.vscodeEngine,
      mcpSdkVersion: manifest.mcpSdkVersion,
      serverSha256,
      extensionSha256,
    })}\n`),
    writeFile(path.join(versionRoot, 'extension.vsix'), extensionBytes),
    writeFile(path.join(installRoot, 'bin', 'vscode-lsp-mcp.cjs'), 'fixture'),
    writeFile(path.join(installRoot, 'bin', 'vscode-lsp-mcp.cmd'), 'fixture'),
    writeFile(path.join(configRoot, 'config.json'), `${JSON.stringify({ schemaVersion: 1 })}\n`),
  ]);
  return { installRoot, configRoot, manifest, versionRoot };
};

const createRuntime = async (root) => {
  const runtimeRoot = path.join(root, 'runtime');
  await Promise.all([
    mkdir(path.join(runtimeRoot, 'registrations'), { recursive: true, mode: 0o700 }),
    mkdir(path.join(runtimeRoot, 'quarantine'), { recursive: true, mode: 0o700 }),
  ]);
  return runtimeRoot;
};

const usableRecord = (label, updatedAt, endpoint = {
  kind: 'namedPipe', address: `\\\\.\\pipe\\vscode-lsp-mcp-test-${label}`,
}) => {
  const secrets = createRegistrationSecrets(systemRuntimePrimitives);
  return {
    registryVersion: REGISTRY_VERSION,
    protocolVersion: IPC_PROTOCOL_VERSION,
    kind: 'usable',
    instanceId: createInstanceId(systemRuntimePrimitives),
    workspaceId: createWorkspaceId(systemRuntimePrimitives),
    workspaceGeneration: 1,
    recordNonce: secrets.recordNonce,
    workspaceName: `Workspace ${label}`,
    extensionHostPid: process.pid,
    activationStartedAt: updatedAt - 1_000,
    publishedAt: updatedAt - 500,
    updatedAt,
    endpoint,
    authToken: secrets.authToken,
    rootsFingerprint: sha256(label),
    roots: [{
      alias: label,
      folderName: label,
      folderIndex: 0,
      lexicalRoot: `D:\\${label}`,
      canonicalRoot: `D:\\${label}`,
      lexicalComparisonKey: `d:\\${label}`,
      canonicalComparisonKey: `d:\\${label}`,
    }],
    vscodeVersion: '1.128.0',
  };
};

const writeRecord = async (runtimeRoot, record) => {
  const filePath = path.join(runtimeRoot, 'registrations', `${record.instanceId}.json`);
  await writeFile(filePath, `${JSON.stringify(record)}\n`, { mode: 0o600 });
  return filePath;
};

const injected = (now, overrides = {}) => ({
  platform: process.platform,
  architecture: process.arch,
  environment: process.env,
  now: () => now,
  verifyWindowsRegistryFile: () => true,
  getExtensionInstallationStatus: async () => ({ installed: true, version: '0.1.0' }),
  validateServerVersion: () => true,
  ...overrides,
});

test('doctor derives the bounded Windows runtime root and rejects other platforms', () => {
  assert.equal(
    defaultRuntimeRoot({ platform: 'win32', environment: { LOCALAPPDATA: 'C:\\Users\\sample\\AppData\\Local' } }),
    'C:\\Users\\sample\\AppData\\Local\\vscode-lsp-mcp\\run',
  );
  assert.throws(() => defaultRuntimeRoot({ platform: 'unsupported', environment: {} }), {
    code: 'RUNTIME_ROOT_UNAVAILABLE',
  });
});

test('doctor reports a missing install and writes a bounded redacted log', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'vlm-doctor-missing-'));
  try {
    const options = {
      installRoot: path.join(root, 'install'),
      configRoot: path.join(root, 'config'),
      runtimeRoot: path.join(root, 'runtime'),
    };
    const report = await runDoctor(options, injected(Date.now()));
    assert.equal(report.installation.state, 'notInstalled');
    assert.ok(report.checks.some((check) => check.code === 'INSTALL_NOT_FOUND'));
    assert.ok(report.log.bytes <= report.log.maximumBytes);
    const log = await readFile(report.log.path, 'utf8');
    assert.equal(log.includes(root), false);
    assert.equal(log.includes('authToken'), false);
    assert.equal(log.includes('endpoint'), false);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('doctor validates installed identity and distinguishes a missing VS Code extension', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'vlm-doctor-install-'));
  try {
    const fixture = await createInstalledFixture(root);
    const runtimeRoot = await createRuntime(root);
    const report = await runDoctor(
      { ...fixture, runtimeRoot },
      injected(Date.now(), { getExtensionInstallationStatus: async () => ({ installed: false }) }),
    );
    for (const code of ['INSTALL_MANIFEST_VALID', 'VERSION_IDENTITY_MATCH', 'SERVER_VERSION_MATCH']) {
      assert.ok(report.checks.some((check) => check.code === code), code);
    }
    assert.ok(report.checks.some((check) => check.code === 'EXTENSION_NOT_INSTALLED'));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('doctor leaves malformed registrations in place and never quarantines during inspection', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'vlm-doctor-readonly-'));
  try {
    const fixture = await createInstalledFixture(root);
    const runtimeRoot = await createRuntime(root);
    const invalidPath = path.join(runtimeRoot, 'registrations', 'invalid.json');
    await Promise.all([
      writeFile(invalidPath, '{"authToken":"do-not-log"}', { mode: 0o600 }),
      writeFile(
        path.join(runtimeRoot, 'registrations', 'version-mismatch.json'),
        '{"registryVersion":1,"protocolVersion":"1.0"}',
        { mode: 0o600 },
      ),
    ]);
    const report = await runDoctor({ ...fixture, runtimeRoot }, injected(Date.now()));
    assert.ok(report.checks.some((check) => check.code === 'INVALID_REGISTRATION'));
    assert.ok(report.checks.some((check) => check.code === 'REGISTRATION_VERSION_MISMATCH'));
    assert.equal((await readFile(invalidPath, 'utf8')).includes('do-not-log'), true);
    assert.equal((await readdir(path.join(runtimeRoot, 'quarantine'))).length, 0);
    assert.equal((await readFile(report.log.path, 'utf8')).includes('do-not-log'), false);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('doctor rotates only its bounded managed logs and preserves foreign files', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'vlm-doctor-rotation-'));
  try {
    const fixture = await createInstalledFixture(root);
    const runtimeRoot = await createRuntime(root);
    const logRoot = path.join(fixture.configRoot, 'logs');
    await mkdir(logRoot);
    await Promise.all([
      ...Array.from({ length: 6 }, (_, index) =>
        writeFile(path.join(logRoot, `doctor-2020-0${index}.jsonl`), '{}\n')),
      writeFile(path.join(logRoot, 'foreign.log'), 'preserve'),
    ]);
    await runDoctor({ ...fixture, runtimeRoot }, injected(Date.now()));
    const entries = await readdir(logRoot);
    assert.equal(entries.filter((name) => /^doctor-.+\.jsonl$/u.test(name)).length, 5);
    assert.ok(entries.includes('foreign.log'));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('doctor distinguishes no workspace, stale registration, and IPC failure', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'vlm-doctor-runtime-'));
  try {
    const fixture = await createInstalledFixture(root);
    const runtimeRoot = await createRuntime(root);
    const now = Date.now();
    const unavailableSource = usableRecord('empty', now);
    const unavailable = {
      registryVersion: unavailableSource.registryVersion,
      protocolVersion: unavailableSource.protocolVersion,
      kind: 'unavailable',
      instanceId: unavailableSource.instanceId,
      workspaceId: unavailableSource.workspaceId,
      workspaceGeneration: unavailableSource.workspaceGeneration,
      recordNonce: unavailableSource.recordNonce,
      workspaceName: unavailableSource.workspaceName,
      extensionHostPid: unavailableSource.extensionHostPid,
      activationStartedAt: unavailableSource.activationStartedAt,
      publishedAt: unavailableSource.publishedAt,
      updatedAt: unavailableSource.updatedAt,
      reasonCode: 'no_workspace_folders',
    };
    await writeRecord(runtimeRoot, unavailable);
    const noWorkspace = await runDoctor({ ...fixture, runtimeRoot }, injected(now));
    assert.ok(noWorkspace.checks.some((check) => check.code === 'NO_WORKSPACE'));

    await rm(path.join(runtimeRoot, 'registrations'), { recursive: true, force: true });
    await mkdir(path.join(runtimeRoot, 'registrations'), { mode: 0o700 });
    const stale = usableRecord('stale', now - 120_000);
    stale.vscodeVersion = '1.100.0';
    await writeRecord(runtimeRoot, stale);
    const staleReport = await runDoctor(
      { ...fixture, runtimeRoot },
      injected(now + 1, {
        connectRegisteredBridge: async () => ({
          call: async () => ({ status: 'healthy' }),
          close: async () => undefined,
        }),
      }),
    );
    assert.ok(staleReport.checks.some((check) => check.code === 'STALE_REGISTRATION'));
    assert.ok(staleReport.checks.some((check) => check.code === 'VSCODE_VERSION_MISMATCH'));

    await rm(path.join(runtimeRoot, 'registrations'), { recursive: true, force: true });
    await mkdir(path.join(runtimeRoot, 'registrations'), { mode: 0o700 });
    const disconnected = usableRecord('disconnected', now + 2);
    await writeRecord(runtimeRoot, disconnected);
    const disconnectedReport = await runDoctor(
      { ...fixture, runtimeRoot },
      injected(now + 2, {
        connectRegisteredBridge: async () => {
          throw new BridgeTransportError('disconnected', 'private endpoint omitted', 'notStarted');
        },
      }),
    );
    assert.ok(disconnectedReport.checks.some((check) => check.code === 'IPC_DISCONNECTED'));
    assert.equal(JSON.stringify(disconnectedReport).includes('private endpoint omitted'), false);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
