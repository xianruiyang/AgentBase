import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { createRequire } from 'node:module';
import {
  lstat,
  mkdir,
  readFile,
  readdir,
  rm,
  writeFile,
} from 'node:fs/promises';
import path from 'node:path';
import {
  CAPABILITIES_BRIDGE_METHOD,
  parseCapabilitiesBridgeResponse,
} from '../packages/protocol/dist/capability-bridge.js';
import { CAPABILITY_NAMES } from '../packages/protocol/dist/dto.js';
import {
  IPC_HEALTH_TIMEOUT_MS,
  IPC_HELLO_TIMEOUT_MS,
  IPC_PROTOCOL_VERSION,
  parseStrictJson,
} from '../packages/protocol/dist/ipc-protocol.js';
import {
  BridgeClientSession,
  BridgeTransportError,
  authenticateIpcClientConnection,
} from '../packages/protocol/dist/ipc-session.js';
import { connectNodeRawByte } from '../packages/protocol/dist/node-ipc.js';
import {
  REGISTRY_MAX_RECORD_BYTES,
  REGISTRY_MAX_RECORDS,
  REGISTRY_VERSION,
  parseRegistrationRecord,
  registrationLeaseState,
} from '../packages/protocol/dist/registry.js';
import { systemRuntimePrimitives } from '../packages/protocol/dist/runtime.js';
import {
  EXTENSION_ID,
  InstallError,
  assertNoSymlinkComponents,
  getExtensionInstallationStatus,
  validateNodeEngine,
} from './install-core.mjs';

const require = createRequire(import.meta.url);
const maximumJsonBytes = 1024 * 1024;
const maximumHashBytes = 512 * 1024 * 1024;
const maximumLogBytes = 256 * 1024;
const retainedLogFiles = 5;
const semanticVersionPattern = /^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$/u;
const sha256Pattern = /^[0-9a-f]{64}$/u;
const managedEntries = ['.staging', 'bin', 'versions', 'install-manifest.json'];
const publicIssuePattern = /^[a-z0-9_]{1,80}$/u;

const doctorFailure = (code, message, options) => {
  throw new InstallError(code, message, options);
};

const isMissing = (error) => error?.code === 'ENOENT';

const statIfPresent = async (filePath) => {
  try {
    return await lstat(filePath);
  } catch (error) {
    if (isMissing(error)) return undefined;
    throw error;
  }
};

const readBoundedJson = async (filePath, maximumBytes = maximumJsonBytes) => {
  const metadata = await lstat(filePath);
  if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.size < 1 || metadata.size > maximumBytes) {
    throw new Error('JSON file shape or size is invalid.');
  }
  return JSON.parse(await readFile(filePath, 'utf8'));
};

const hashFile = async (filePath) => {
  const metadata = await lstat(filePath);
  if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.size > maximumHashBytes) {
    throw new Error('Artifact file shape or size is invalid.');
  }
  return new Promise((resolve, reject) => {
    const hash = createHash('sha256');
    const stream = createReadStream(filePath);
    stream.once('error', reject);
    stream.on('data', (chunk) => hash.update(chunk));
    stream.once('end', () => resolve(hash.digest('hex')));
  });
};

const validateInstalledManifest = (value) => {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Installed manifest is not an object.');
  }
  const artifact = (candidate) => candidate !== null && typeof candidate === 'object' &&
    !Array.isArray(candidate) && typeof candidate.name === 'string' &&
    sha256Pattern.test(candidate.sha256);
  if (
    value.schemaVersion !== 1 || value.component !== 'vscode-lsp-mcp' ||
    typeof value.version !== 'string' || !semanticVersionPattern.test(value.version) ||
    typeof value.target !== 'string' || typeof value.nodeEngine !== 'string' ||
    typeof value.vscodeEngine !== 'string' || !/^\^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$/u.test(value.vscodeEngine) ||
    typeof value.mcpSdkVersion !== 'string' || !semanticVersionPattern.test(value.mcpSdkVersion) ||
    !artifact(value.artifacts?.server) || !artifact(value.artifacts?.extension) ||
    value.extension?.id !== EXTENSION_ID || value.extension?.version !== value.version ||
    typeof value.extension?.installed !== 'boolean' || value.config?.file !== 'config.json' ||
    typeof value.config?.createdByInstaller !== 'boolean' ||
    !Array.isArray(value.managedRootEntries) ||
    value.managedRootEntries.length !== managedEntries.length ||
    managedEntries.some((entry, index) => value.managedRootEntries[index] !== entry)
  ) {
    throw new Error('Installed manifest contract is invalid.');
  }
  return value;
};

const checkResult = (id, status, code, message) => Object.freeze({ id, status, code, message });

const addCheck = (checks, id, status, code, message) => {
  checks.push(checkResult(id, status, code, message));
};

const validateServerVersion = (serverEntry, serverRoot, expectedVersion) => {
  const result = spawnSync(process.execPath, [serverEntry, '--version'], {
    cwd: serverRoot,
    encoding: 'utf8',
    windowsHide: true,
    timeout: 5_000,
    maxBuffer: 4_096,
  });
  return result.error === undefined && result.status === 0 && result.stdout.trim() === expectedVersion;
};

const validateConfiguration = async (options, manifest, checks) => {
  const configPath = path.join(options.configRoot, 'config.json');
  const metadata = await statIfPresent(configPath);
  if (metadata === undefined) {
    addCheck(
      checks,
      'install.configuration',
      manifest.config.createdByInstaller ? 'fail' : 'warning',
      'CONFIGURATION_MISSING',
      'The configuration file is missing.',
    );
    return;
  }
  try {
    await assertNoSymlinkComponents(configPath);
    await readBoundedJson(configPath);
    addCheck(checks, 'install.configuration', 'pass', 'CONFIGURATION_VALID', 'Configuration JSON is valid.');
  } catch {
    addCheck(checks, 'install.configuration', 'fail', 'INVALID_CONFIGURATION', 'Configuration JSON is invalid or unsafe.');
  }
};

const inspectInstallation = async (options, dependencies, checks) => {
  const manifestPath = path.join(options.installRoot, 'install-manifest.json');
  if (await statIfPresent(manifestPath) === undefined) {
    addCheck(checks, 'install.manifest', 'fail', 'INSTALL_NOT_FOUND', 'The component is not installed.');
    return Object.freeze({ state: 'notInstalled' });
  }
  let manifest;
  try {
    await assertNoSymlinkComponents(options.installRoot);
    manifest = validateInstalledManifest(await readBoundedJson(manifestPath));
    addCheck(checks, 'install.manifest', 'pass', 'INSTALL_MANIFEST_VALID', 'The installed manifest is valid.');
  } catch {
    addCheck(checks, 'install.manifest', 'fail', 'INVALID_INSTALL_STATE', 'The installed manifest or managed path is invalid.');
    return Object.freeze({ state: 'invalid' });
  }

  const expectedTarget = `${dependencies.platform}-${dependencies.architecture}`;
  if (manifest.target === expectedTarget) {
    addCheck(checks, 'install.target', 'pass', 'TARGET_MATCH', 'The installed target matches this host.');
  } else {
    addCheck(checks, 'install.target', 'fail', 'TARGET_MISMATCH', 'The installed target does not match this host.');
  }
  try {
    validateNodeEngine(manifest.nodeEngine);
    addCheck(checks, 'install.nodeEngine', 'pass', 'NODE_VERSION_MATCH', 'The current Node runtime satisfies the installed engine range.');
  } catch (error) {
    const code = error instanceof InstallError ? error.code : 'NODE_VERSION_MISMATCH';
    addCheck(checks, 'install.nodeEngine', 'fail', code, 'The current Node runtime does not satisfy the installed engine range.');
  }

  const versionRoot = path.join(options.installRoot, 'versions', manifest.version);
  const serverRoot = path.join(versionRoot, 'server');
  const serverEntry = path.join(serverRoot, 'dist', 'cli.js');
  try {
    const [serverManifest, versions, release, extensionHash] = await Promise.all([
      readBoundedJson(path.join(serverRoot, 'package.json')),
      readBoundedJson(path.join(serverRoot, 'versions.json')),
      readBoundedJson(path.join(versionRoot, 'release.json')),
      hashFile(path.join(versionRoot, 'extension.vsix')),
    ]);
    const versionsMatch = Object.values(versions).length > 0 &&
      Object.values(versions).every((version) => version === manifest.version);
    const identityMatches = serverManifest.version === manifest.version && versionsMatch &&
      release.schemaVersion === 1 && release.version === manifest.version &&
      release.target === manifest.target && release.serverSha256 === manifest.artifacts.server.sha256 &&
      release.vscodeEngine === manifest.vscodeEngine &&
      release.mcpSdkVersion === manifest.mcpSdkVersion &&
      release.extensionSha256 === manifest.artifacts.extension.sha256 &&
      extensionHash === manifest.artifacts.extension.sha256;
    if (!identityMatches) throw new Error('Installed version identity differs.');
    addCheck(checks, 'install.versionIdentity', 'pass', 'VERSION_IDENTITY_MATCH', 'Installed package versions and hashes agree.');
  } catch {
    addCheck(checks, 'install.versionIdentity', 'fail', 'VERSION_MISMATCH', 'Installed package versions or hashes disagree.');
  }

  const launchers = ['vscode-lsp-mcp.cjs', 'vscode-lsp-mcp.cmd'];
  const launcherStates = await Promise.all(launchers.map((name) => statIfPresent(path.join(options.installRoot, 'bin', name))));
  if (launcherStates.every((entry) => entry?.isFile() === true && !entry.isSymbolicLink())) {
    addCheck(checks, 'install.launchers', 'pass', 'LAUNCHERS_PRESENT', 'All stable launchers are present.');
  } else {
    addCheck(checks, 'install.launchers', 'fail', 'LAUNCHER_MISSING', 'One or more stable launchers are missing or unsafe.');
  }

  const versionProbe = dependencies.validateServerVersion ?? validateServerVersion;
  if (await versionProbe(serverEntry, serverRoot, manifest.version)) {
    addCheck(checks, 'install.serverVersion', 'pass', 'SERVER_VERSION_MATCH', 'The server reports the installed version.');
  } else {
    addCheck(checks, 'install.serverVersion', 'fail', 'SERVER_VERSION_MISMATCH', 'The server did not report the installed version.');
  }

  await validateConfiguration(options, manifest, checks);

  if (manifest.extension.installed) {
    try {
      const extensionProbe = dependencies.getExtensionInstallationStatus ?? getExtensionInstallationStatus;
      const extension = await extensionProbe(options);
      if (!extension.installed) {
        addCheck(checks, 'install.extension', 'fail', 'EXTENSION_NOT_INSTALLED', 'The VS Code companion extension is not installed.');
      } else if (extension.version !== manifest.version) {
        addCheck(checks, 'install.extension', 'fail', 'EXTENSION_VERSION_MISMATCH', 'The VS Code companion extension version differs.');
      } else {
        addCheck(checks, 'install.extension', 'pass', 'EXTENSION_VERSION_MATCH', 'The VS Code companion extension version matches.');
      }
    } catch (error) {
      const code = error instanceof InstallError ? error.code : 'CODE_CLI_FAILED';
      addCheck(checks, 'install.extension', 'warning', code, 'VS Code CLI could not verify the installed extension.');
    }
  } else {
    addCheck(checks, 'install.extension', 'skipped', 'EXTENSION_INSTALL_SKIPPED', 'The installation manifest records a server-only install.');
  }

  return Object.freeze({
    state: 'installed',
    version: manifest.version,
    target: manifest.target,
    manifest,
    versionRoot,
    serverRoot,
  });
};

export const defaultRuntimeRoot = ({
  platform = process.platform,
  environment = process.env,
} = {}) => {
  if (platform !== 'win32') {
    doctorFailure('RUNTIME_ROOT_UNAVAILABLE', 'vscode-lsp-mcp is maintained only on Windows.');
  }
  if (typeof environment.LOCALAPPDATA !== 'string' || !path.win32.isAbsolute(environment.LOCALAPPDATA)) {
    doctorFailure('RUNTIME_ROOT_UNAVAILABLE', 'LOCALAPPDATA is required to locate the runtime directory.');
  }
  return path.win32.join(environment.LOCALAPPDATA, 'vscode-lsp-mcp', 'run');
};

const loadWindowsRegistryVerifier = (installation) => {
  if (installation.state !== 'installed') return undefined;
  try {
    const adapterPath = path.join(
      installation.serverRoot,
      'node_modules',
      '@simplechat',
      'vscode-lsp-mcp-win32-security',
      'dist',
      'index.js',
    );
    const adapter = require(adapterPath);
    return typeof adapter.verifySecureRegistryFile === 'function'
      ? adapter.verifySecureRegistryFile
      : undefined;
  } catch {
    return undefined;
  }
};

const assertSecureRegistryFile = (metadata, filePath, verifier) => {
  if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.size < 1 ||
      metadata.size > REGISTRY_MAX_RECORD_BYTES) {
    throw new Error('Registration file shape or size is invalid.');
  }
  if (verifier?.(filePath) !== true) throw new Error('Registration ACL is invalid or unavailable.');
};

const scanRegistrations = async ({ runtimeRoot, verifier }, checks) => {
  const rootMetadata = await statIfPresent(runtimeRoot);
  if (rootMetadata === undefined) return Object.freeze({ records: [], invalid: 0, versionMismatches: 0, quarantine: 0 });
  if (!rootMetadata.isDirectory() || rootMetadata.isSymbolicLink()) {
    addCheck(checks, 'runtime.directory', 'fail', 'RUNTIME_SECURITY_FAILED', 'The runtime directory is unsafe.');
    return Object.freeze({ records: [], invalid: 0, versionMismatches: 0, quarantine: 0 });
  }
  const registrationsRoot = path.join(runtimeRoot, 'registrations');
  const registrationsMetadata = await statIfPresent(registrationsRoot);
  if (registrationsMetadata === undefined) return Object.freeze({ records: [], invalid: 0, versionMismatches: 0, quarantine: 0 });
  if (!registrationsMetadata.isDirectory() || registrationsMetadata.isSymbolicLink()) {
    addCheck(checks, 'runtime.registryDirectory', 'fail', 'RUNTIME_SECURITY_FAILED', 'The registration directory is unsafe.');
    return Object.freeze({ records: [], invalid: 0, versionMismatches: 0, quarantine: 0 });
  }
  if (verifier === undefined) {
    addCheck(checks, 'runtime.registrySecurity', 'fail', 'REGISTRY_SECURITY_UNAVAILABLE', 'Registration ACL verification is unavailable.');
    return Object.freeze({ records: [], invalid: 0, versionMismatches: 0, quarantine: 0 });
  }

  const entries = await readdir(registrationsRoot, { withFileTypes: true });
  const candidates = entries
    .filter((entry) => entry.name.endsWith('.json'))
    .sort((left, right) => left.name.localeCompare(right.name));
  if (candidates.length > REGISTRY_MAX_RECORDS) {
    addCheck(checks, 'runtime.registryLimit', 'warning', 'REGISTRATION_LIMIT_EXCEEDED', 'The registry contains more records than the bounded scan limit.');
  }
  const records = [];
  let invalid = 0;
  let versionMismatches = 0;
  for (const candidate of candidates.slice(0, REGISTRY_MAX_RECORDS)) {
    const filePath = path.join(registrationsRoot, candidate.name);
    try {
      const metadata = await lstat(filePath);
      assertSecureRegistryFile(metadata, filePath, verifier);
      const text = await readFile(filePath, 'utf8');
      const raw = parseStrictJson(text);
      if (raw !== null && typeof raw === 'object' && !Array.isArray(raw) &&
          (raw.registryVersion !== REGISTRY_VERSION || raw.protocolVersion !== IPC_PROTOCOL_VERSION)) {
        versionMismatches += 1;
      }
      const record = parseRegistrationRecord(text);
      if (`${record.instanceId}.json` !== candidate.name) throw new Error('Registration identity differs from its filename.');
      records.push(record);
    } catch {
      invalid += 1;
    }
  }
  const quarantineRoot = path.join(runtimeRoot, 'quarantine');
  const quarantineMetadata = await statIfPresent(quarantineRoot);
  const quarantine = quarantineMetadata?.isDirectory() === true && !quarantineMetadata.isSymbolicLink()
    ? (await readdir(quarantineRoot)).slice(0, REGISTRY_MAX_RECORDS + 1).length
    : 0;
  return Object.freeze({ records: Object.freeze(records), invalid, versionMismatches, quarantine });
};

const publicIssue = (value, fallback) => typeof value === 'string' && publicIssuePattern.test(value)
  ? value
  : fallback;

const transportIssue = (error) => {
  if (!(error instanceof BridgeTransportError)) return 'IPC_FAILURE';
  if (error.reason === 'authentication') return 'IPC_AUTHENTICATION_FAILED';
  if (error.reason === 'timeout') return 'IPC_TIMEOUT';
  if (error.reason === 'protocol') return 'IPC_PROTOCOL_FAILURE';
  if (error.reason === 'disconnected') return 'IPC_DISCONNECTED';
  if (error.reason === 'remote') return 'IPC_REMOTE_FAILURE';
  if (error.reason === 'cancelled') return 'IPC_CANCELLED';
  return 'IPC_FAILURE';
};

const pidDefinitelyDead = async (pid) => {
  try {
    process.kill(pid, 0);
    return false;
  } catch (error) {
    return error?.code === 'ESRCH';
  }
};

const satisfiesCaretVersion = (version, engine) => {
  const parsedVersion = /^(\d+)\.(\d+)\.(\d+)/u.exec(version);
  const parsedEngine = /^\^(\d+)\.(\d+)\.(\d+)$/u.exec(engine);
  if (parsedVersion === null || parsedEngine === null) return false;
  const current = parsedVersion.slice(1, 4).map(Number);
  const minimum = parsedEngine.slice(1, 4).map(Number);
  const compare = (left, right) => {
    for (let index = 0; index < 3; index += 1) {
      if (left[index] !== right[index]) return left[index] < right[index] ? -1 : 1;
    }
    return 0;
  };
  const maximum = minimum[0] > 0
    ? [minimum[0] + 1, 0, 0]
    : minimum[1] > 0
      ? [0, minimum[1] + 1, 0]
      : [0, 0, minimum[2] + 1];
  return compare(current, minimum) >= 0 && compare(current, maximum) < 0;
};

const probeCapabilities = async (session, options, workspace, checks) => {
  if (options.file === undefined) {
    addCheck(checks, `runtime.provider.${workspace.workspaceId}`, 'skipped', 'PROVIDER_FILE_REQUIRED', 'Pass a logical file to diagnose document language providers.');
    return undefined;
  }
  try {
    const response = parseCapabilitiesBridgeResponse(await session.call(
      CAPABILITIES_BRIDGE_METHOD,
      { file: options.file, capabilities: CAPABILITY_NAMES },
      { deadlineAt: Date.now() + 10_000 },
    ));
    if (response.status !== 'completed') throw new Error('Capability probe failed.');
    const notReady = response.candidates.filter((candidate) => candidate.reason === 'provider_not_ready');
    const timedOut = response.candidates.filter((candidate) => candidate.reason === 'provider_timed_out');
    const diagnostics = response.candidates.find((candidate) => candidate.name === 'diagnostics');
    if (notReady.length > 0 || timedOut.length > 0) {
      addCheck(checks, `runtime.provider.${workspace.workspaceId}`, 'warning', 'LANGUAGE_PROVIDER_NOT_READY', 'One or more language providers are not ready or timed out.');
    } else {
      addCheck(checks, `runtime.provider.${workspace.workspaceId}`, 'pass', 'LANGUAGE_PROVIDER_RESPONDED', 'Language provider probes completed.');
    }
    if (diagnostics?.status === 'available') {
      addCheck(checks, `runtime.diagnostics.${workspace.workspaceId}`, 'pass', 'DIAGNOSTICS_PUBLISHED', 'The selected document has published diagnostics.');
    } else if (diagnostics?.reason === 'probe_returned_no_evidence') {
      addCheck(checks, `runtime.diagnostics.${workspace.workspaceId}`, 'warning', 'DIAGNOSTICS_NOT_PUBLISHED', 'The provider published no diagnostics for the selected document.');
    } else {
      addCheck(checks, `runtime.diagnostics.${workspace.workspaceId}`, 'warning', 'DIAGNOSTICS_PROVIDER_NOT_READY', 'Diagnostics readiness could not be confirmed.');
    }
    return response.candidates;
  } catch (error) {
    addCheck(checks, `runtime.provider.${workspace.workspaceId}`, 'warning', transportIssue(error), 'The language provider probe did not complete.');
    return undefined;
  }
};

const connectBridgeOnce = async (record) => {
  const raw = await connectNodeRawByte(record.endpoint.address, IPC_HELLO_TIMEOUT_MS);
  const framed = await authenticateIpcClientConnection(raw, {
    instanceId: record.instanceId,
    workspaceId: record.workspaceId,
    workspaceGeneration: record.workspaceGeneration,
    token: record.authToken,
  }, systemRuntimePrimitives);
  return new BridgeClientSession(framed, systemRuntimePrimitives);
};

const inspectRuntime = async (options, dependencies, installation, checks) => {
  const runtimeRoot = options.runtimeRoot ?? defaultRuntimeRoot({
    platform: dependencies.platform,
    environment: dependencies.environment,
  });
  const verifier = dependencies.verifyWindowsRegistryFile ??
    loadWindowsRegistryVerifier(installation);
  const scanned = await scanRegistrations({
    runtimeRoot,
    verifier,
  }, checks);
  if (scanned.invalid > 0) {
    addCheck(checks, 'runtime.invalidRegistrations', 'warning', 'INVALID_REGISTRATION', `${scanned.invalid} registration record(s) are invalid or unsafe.`);
  }
  if (scanned.versionMismatches > 0) {
    addCheck(checks, 'runtime.registrationVersions', 'fail', 'REGISTRATION_VERSION_MISMATCH', `${scanned.versionMismatches} registration record(s) use an incompatible registry or IPC version.`);
  }
  if (scanned.quarantine > 0) {
    addCheck(checks, 'runtime.quarantine', 'warning', 'QUARANTINED_REGISTRATION', `${scanned.quarantine} quarantined registration record(s) exist.`);
  }
  const selected = options.workspaceId === undefined
    ? scanned.records
    : scanned.records.filter((record) => record.workspaceId === options.workspaceId);
  if (selected.length === 0) {
    addCheck(
      checks,
      'runtime.registrations',
      'warning',
      options.workspaceId === undefined ? 'NO_REGISTRATIONS' : 'WORKSPACE_NOT_FOUND',
      options.workspaceId === undefined ? 'No VS Code workspace registration was found.' : 'The requested workspace registration was not found.',
    );
    return Object.freeze({ registrations: [], invalid: scanned.invalid, versionMismatches: scanned.versionMismatches, quarantine: scanned.quarantine });
  }

  const connect = dependencies.connectRegisteredBridge ?? connectBridgeOnce;
  const workspaces = [];
  for (const record of selected) {
    const lease = registrationLeaseState(record, dependencies.now());
    const issues = [];
    if (lease !== 'fresh') {
      issues.push('STALE_REGISTRATION');
      addCheck(checks, `runtime.lease.${record.workspaceId}`, 'warning', 'STALE_REGISTRATION', 'The workspace registration heartbeat is stale.');
    }
    if (record.kind === 'unavailable') {
      const code = record.reasonCode === 'no_workspace_folders' ? 'NO_WORKSPACE' : record.reasonCode.toUpperCase();
      issues.push(code);
      addCheck(checks, `runtime.workspace.${record.workspaceId}`, 'warning', code, 'The extension published an unavailable workspace state.');
      workspaces.push(Object.freeze({
        workspaceId: record.workspaceId,
        name: record.workspaceName,
        kind: record.kind,
        lease,
        status: 'unavailable',
        issues: Object.freeze(issues),
      }));
      continue;
    }

    if (installation.state !== 'installed') {
      addCheck(checks, `runtime.vscodeVersion.${record.workspaceId}`, 'skipped', 'VSCODE_VERSION_CHECK_SKIPPED', 'VS Code compatibility cannot be checked without a valid installation.');
    } else if (!satisfiesCaretVersion(record.vscodeVersion, installation.manifest.vscodeEngine)) {
      issues.push('VSCODE_VERSION_MISMATCH');
      addCheck(checks, `runtime.vscodeVersion.${record.workspaceId}`, 'fail', 'VSCODE_VERSION_MISMATCH', 'The registered VS Code version is outside the extension compatibility range.');
    } else {
      addCheck(checks, `runtime.vscodeVersion.${record.workspaceId}`, 'pass', 'VSCODE_VERSION_COMPATIBLE', 'The registered VS Code version is compatible with the extension.');
    }

    let session;
    let capabilities;
    let status = 'unavailable';
    try {
      session = await connect(record);
      const health = await session.call('bridge.health', {}, {
        deadlineAt: Date.now() + IPC_HEALTH_TIMEOUT_MS,
      });
      if (health === null || typeof health !== 'object' || Array.isArray(health) ||
          (health.status !== 'healthy' && health.status !== 'unavailable')) {
        throw new BridgeTransportError('protocol', 'Invalid bridge health response.', 'unknown');
      }
      if (health.status === 'healthy') {
        status = lease === 'fresh' ? 'healthy' : 'degraded';
        addCheck(checks, `runtime.ipc.${record.workspaceId}`, 'pass', 'IPC_HEALTHY', 'The workspace bridge authenticated and responded.');
      } else {
        status = 'unavailable';
        const issue = publicIssue(health.issue, 'document_unavailable').toUpperCase();
        issues.push(issue);
        addCheck(checks, `runtime.ipc.${record.workspaceId}`, 'warning', issue, 'The workspace bridge reported an unavailable state.');
      }
      capabilities = await probeCapabilities(session, options, record, checks);
    } catch (error) {
      const issue = transportIssue(error);
      issues.push(issue);
      if (await (dependencies.pidDefinitelyDead ?? pidDefinitelyDead)(record.extensionHostPid)) {
        issues.push('HOST_PROCESS_DEAD');
      }
      addCheck(checks, `runtime.ipc.${record.workspaceId}`, 'fail', issue, 'The workspace bridge connection failed.');
    } finally {
      await session?.close().catch(() => undefined);
    }
    workspaces.push(Object.freeze({
      workspaceId: record.workspaceId,
      name: record.workspaceName,
      kind: record.kind,
      lease,
      status,
      vscodeVersion: record.vscodeVersion,
      roots: Object.freeze(record.roots.map((root) => root.alias)),
      issues: Object.freeze(issues),
      ...(capabilities === undefined ? {} : { capabilities }),
    }));
  }
  return Object.freeze({ registrations: Object.freeze(workspaces), invalid: scanned.invalid, versionMismatches: scanned.versionMismatches, quarantine: scanned.quarantine });
};

const summarize = (checks) => {
  const counts = { pass: 0, warning: 0, fail: 0, skipped: 0 };
  for (const check of checks) counts[check.status] += 1;
  return Object.freeze({ checks: checks.length, ...counts });
};

const safeTimestamp = (timestamp) => new Date(timestamp).toISOString().replaceAll(':', '').replaceAll('.', '-');

const writeDiagnosticLog = async (options, report, dependencies) => {
  const logRoot = path.join(options.configRoot, 'logs');
  const requested = options.logFile === undefined
    ? path.join(logRoot, `doctor-${safeTimestamp(dependencies.now())}-${process.pid}.jsonl`)
    : path.resolve(options.logFile);
  const relative = path.relative(logRoot, requested);
  if (relative.startsWith('..') || path.isAbsolute(relative)) {
    doctorFailure('INVALID_LOG_PATH', 'Diagnostic logs must stay inside the configuration log directory.');
  }
  await assertNoSymlinkComponents(logRoot);
  await mkdir(logRoot, { recursive: true, mode: 0o700 });
  await assertNoSymlinkComponents(logRoot);
  const existing = (await readdir(logRoot, { withFileTypes: true }))
    .filter((entry) => entry.isFile() && /^doctor-.+\.jsonl$/u.test(entry.name))
    .sort((left, right) => left.name.localeCompare(right.name));
  for (const entry of existing.slice(0, Math.max(0, existing.length - retainedLogFiles + 1))) {
    await rm(path.join(logRoot, entry.name), { force: true });
  }
  const events = [
    { event: 'doctor.start', schemaVersion: 1 },
    ...report.checks.map((check) => ({
      event: 'doctor.check',
      id: check.id,
      status: check.status,
      code: check.code,
    })),
    { event: 'doctor.finish', status: report.status, summary: report.summary },
  ];
  let payload = '';
  let truncated = false;
  for (const event of events) {
    const line = `${JSON.stringify(event)}\n`;
    if (Buffer.byteLength(payload) + Buffer.byteLength(line) > maximumLogBytes) {
      truncated = true;
      break;
    }
    payload += line;
  }
  if (truncated) payload += `${JSON.stringify({ event: 'doctor.logTruncated' })}\n`;
  try {
    await writeFile(requested, payload, { encoding: 'utf8', flag: 'wx', mode: 0o600 });
  } catch (error) {
    doctorFailure('DIAGNOSTIC_LOG_FAILED', 'The bounded diagnostic log could not be written.', { cause: error });
  }
  return Object.freeze({ path: requested, bytes: Buffer.byteLength(payload), maximumBytes: maximumLogBytes, truncated });
};

export const runDoctor = async (options, injected = {}) => {
  const dependencies = {
    platform: injected.platform ?? process.platform,
    architecture: injected.architecture ?? process.arch,
    environment: injected.environment ?? process.env,
    now: injected.now ?? Date.now,
    ...injected,
  };
  if (dependencies.platform !== 'win32') {
    doctorFailure('UNSUPPORTED_PLATFORM', 'vscode-lsp-mcp is maintained only on Windows.');
  }
  const checks = [];
  const installation = await inspectInstallation(options, dependencies, checks);
  const runtime = await inspectRuntime(options, dependencies, installation, checks);
  const summary = summarize(checks);
  const status = summary.fail > 0 ? 'unavailable' : summary.warning > 0 ? 'degraded' : 'healthy';
  const report = Object.freeze({
    schemaVersion: 1,
    kind: 'doctor',
    ok: true,
    status,
    summary,
    installation: Object.freeze({
      state: installation.state,
      ...(installation.version === undefined ? {} : { version: installation.version }),
      ...(installation.target === undefined ? {} : { target: installation.target }),
      ...(installation.manifest?.vscodeEngine === undefined ? {} : { vscodeEngine: installation.manifest.vscodeEngine }),
      ...(installation.manifest?.mcpSdkVersion === undefined ? {} : { mcpSdkVersion: installation.manifest.mcpSdkVersion }),
    }),
    runtime,
    checks: Object.freeze(checks),
  });
  const log = await writeDiagnosticLog(options, report, dependencies);
  return Object.freeze({ ...report, log });
};
