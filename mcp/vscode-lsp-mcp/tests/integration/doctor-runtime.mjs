import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {
  BridgeServerSession,
  CAPABILITY_NAMES,
  IPC_PROTOCOL_VERSION,
  REGISTRY_VERSION,
  authenticateIpcServerConnection,
  createInstanceId,
  createRegistrationSecrets,
  createWorkspaceId,
  systemRuntimePrimitives,
} from '../../packages/protocol/dist/index.js';
import { createSecurePipeServer } from '../../packages/win32-security/dist/index.js';
import { runDoctor } from '../../scripts/doctor-core.mjs';

assert.equal(process.platform, 'win32', 'P7-003 real IPC integration currently targets Windows.');

const sha256 = (value) => createHash('sha256').update(value).digest('hex');

const createInstalledFixture = async (root, version) => {
  const installRoot = path.join(root, 'install');
  const configRoot = path.join(root, 'config');
  const versionRoot = path.join(installRoot, 'versions', version);
  const serverRoot = path.join(versionRoot, 'server');
  const extensionBytes = Buffer.from('p7-003-extension-fixture');
  const extensionSha256 = sha256(extensionBytes);
  const serverSha256 = sha256('p7-003-server-fixture');
  const target = `${process.platform}-${process.arch}`;
  await Promise.all([
    mkdir(path.join(serverRoot, 'dist'), { recursive: true }),
    mkdir(path.join(installRoot, 'bin'), { recursive: true }),
    mkdir(configRoot, { recursive: true }),
  ]);
  const installed = {
    schemaVersion: 1,
    component: 'vscode-lsp-mcp',
    version,
    target,
    nodeEngine: '>=22.9.0 <27',
    vscodeEngine: '^1.125.0',
    mcpSdkVersion: '1.29.0',
    artifacts: {
      server: { name: 'server.zip', sha256: serverSha256 },
      extension: { name: 'extension.vsix', sha256: extensionSha256 },
    },
    extension: { id: 'simplechat.vscode-lsp-mcp-companion', version, installed: true },
    config: { file: 'config.json', createdByInstaller: true },
    managedRootEntries: ['.staging', 'bin', 'versions', 'install-manifest.json'],
  };
  await Promise.all([
    writeFile(path.join(installRoot, 'install-manifest.json'), `${JSON.stringify(installed)}\n`),
    writeFile(path.join(serverRoot, 'package.json'), `${JSON.stringify({ version })}\n`),
    writeFile(path.join(serverRoot, 'versions.json'), `${JSON.stringify({ server: version, protocol: version })}\n`),
    writeFile(path.join(serverRoot, 'dist', 'cli.js'), `if (process.argv.includes('--version')) process.stdout.write(${JSON.stringify(version)});\n`),
    writeFile(path.join(versionRoot, 'extension.vsix'), extensionBytes),
    writeFile(path.join(versionRoot, 'release.json'), `${JSON.stringify({
      schemaVersion: 1,
      version,
      target,
      vscodeEngine: installed.vscodeEngine,
      mcpSdkVersion: installed.mcpSdkVersion,
      serverSha256,
      extensionSha256,
    })}\n`),
    writeFile(path.join(installRoot, 'bin', 'vscode-lsp-mcp.cjs'), 'fixture'),
    writeFile(path.join(installRoot, 'bin', 'vscode-lsp-mcp.cmd'), 'fixture'),
    writeFile(path.join(configRoot, 'config.json'), '{"schemaVersion":1}\n'),
  ]);
  return { installRoot, configRoot };
};

const root = await mkdtemp(path.join(os.tmpdir(), 'vscode-lsp-mcp-doctor-runtime-'));
const runtimeRoot = path.join(root, 'runtime');
const version = '0.1.0';
let transportServer;
let serving;
try {
  const installation = await createInstalledFixture(root, version);
  await Promise.all([
    mkdir(path.join(runtimeRoot, 'registrations'), { recursive: true }),
    mkdir(path.join(runtimeRoot, 'quarantine'), { recursive: true }),
  ]);
  const now = Date.now();
  const secrets = createRegistrationSecrets(systemRuntimePrimitives);
  const instanceId = createInstanceId(systemRuntimePrimitives);
  const workspaceId = createWorkspaceId(systemRuntimePrimitives);
  const endpoint = `\\\\.\\pipe\\vscode-lsp-mcp-p7-003-${instanceId.replaceAll('-', '')}`;
  const record = {
    registryVersion: REGISTRY_VERSION,
    protocolVersion: IPC_PROTOCOL_VERSION,
    kind: 'usable',
    instanceId,
    workspaceId,
    workspaceGeneration: 1,
    recordNonce: secrets.recordNonce,
    workspaceName: 'P7-003 fixture',
    extensionHostPid: process.pid,
    activationStartedAt: now - 2_000,
    publishedAt: now - 1_000,
    updatedAt: now,
    endpoint: { kind: 'namedPipe', address: endpoint },
    authToken: secrets.authToken,
    rootsFingerprint: sha256('fixture-root'),
    roots: [{
      alias: 'root',
      folderName: 'fixture',
      folderIndex: 0,
      lexicalRoot: 'D:\\fixture',
      canonicalRoot: 'D:\\fixture',
      lexicalComparisonKey: 'd:\\fixture',
      canonicalComparisonKey: 'd:\\fixture',
    }],
    vscodeVersion: '1.128.0',
  };
  await writeFile(
    path.join(runtimeRoot, 'registrations', `${instanceId}.json`),
    `${JSON.stringify(record)}\n`,
    { mode: 0o600 },
  );

  transportServer = createSecurePipeServer({ name: endpoint, maxInstances: 1 });
  serving = (async () => {
    const raw = await transportServer.accept();
    const connection = await authenticateIpcServerConnection(raw, {
      instanceId,
      workspaceId,
      workspaceGeneration: 1,
      token: secrets.authToken,
    });
    const session = new BridgeServerSession(connection, async (request) => {
      if (request.method === 'bridge.health') return { status: 'healthy' };
      if (request.method === 'capabilities.probe') {
        return {
          status: 'completed',
          candidates: CAPABILITY_NAMES.map((name) => {
            if (name === 'definition') return { name, status: 'unknown', reason: 'provider_not_ready' };
            if (name === 'diagnostics') return { name, status: 'unknown', reason: 'probe_returned_no_evidence' };
            if (name === 'commands' || name === 'tasks') {
              return { name, status: 'unknown', reason: 'execution_policy_not_configured' };
            }
            return { name, status: 'available' };
          }),
        };
      }
      throw new Error('Unexpected doctor bridge method.');
    });
    await session.run();
  })();

  const report = await runDoctor({
    ...installation,
    runtimeRoot,
    workspaceId,
    file: 'root/src/example.ts',
  }, {
    platform: process.platform,
    architecture: process.arch,
    environment: process.env,
    now: () => now,
    verifyWindowsRegistryFile: () => true,
    getExtensionInstallationStatus: async () => ({ installed: true, version }),
  });

  for (const code of [
    'INSTALL_MANIFEST_VALID',
    'VERSION_IDENTITY_MATCH',
    'SERVER_VERSION_MATCH',
    'EXTENSION_VERSION_MATCH',
    'IPC_HEALTHY',
    'LANGUAGE_PROVIDER_NOT_READY',
    'DIAGNOSTICS_NOT_PUBLISHED',
  ]) {
    assert.ok(report.checks.some((check) => check.code === code), `Missing doctor evidence: ${code}`);
  }
  assert.equal(report.runtime.registrations.length, 1);
  assert.equal(report.runtime.registrations[0].status, 'healthy');
  const serialized = JSON.stringify(report);
  for (const secret of [secrets.authToken, secrets.recordNonce, endpoint, 'D:\\fixture']) {
    assert.equal(serialized.includes(secret), false, `Doctor report leaked ${secret}`);
  }
  const log = await readFile(report.log.path, 'utf8');
  assert.equal(log.includes(secrets.authToken), false);
  assert.equal(log.includes(endpoint), false);

  const machineReport = {
    schemaVersion: 1,
    task: 'P7-003',
    transport: 'real-secure-named-pipe',
    installation: report.installation,
    status: report.status,
    codes: report.checks.map((check) => check.code),
    registrationCount: report.runtime.registrations.length,
    reportRedacted: true,
    logBytes: report.log.bytes,
    logBounded: report.log.bytes <= report.log.maximumBytes,
  };
  if (process.env.P7_003_REPORT_PATH !== undefined) {
    const reportPath = path.resolve(process.env.P7_003_REPORT_PATH);
    await mkdir(path.dirname(reportPath), { recursive: true });
    await writeFile(reportPath, `${JSON.stringify(machineReport, null, 2)}\n`);
  }
  process.stdout.write(`${JSON.stringify(machineReport, null, 2)}\n`);
} finally {
  await transportServer?.close().catch(() => undefined);
  await serving?.catch(() => undefined);
  await rm(root, { recursive: true, force: true });
}
