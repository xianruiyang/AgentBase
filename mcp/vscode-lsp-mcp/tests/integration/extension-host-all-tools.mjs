import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import {
  chmod,
  cp,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  writeFile,
} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { runTests } from '@vscode/test-electron';
import {
  TOOL_DEFINITIONS,
  TOOL_NAMES,
  assertToolOutput,
  decodeYamlText,
  ensureRuntimeDirectory,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  ensureSecureRuntimeDirectory,
  verifySecureRegistryFile,
} from '@simplechat/vscode-lsp-mcp-win32-security';

const componentRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const npmCliPath = process.env.npm_execpath;
if (!npmCliPath) {
  throw new Error('npm_execpath is required; run this gate through npm run test:integration:all-tools.');
}

if (process.env.P6_004_SKIP_BUILD !== '1') {
  const build = spawnSync(process.execPath, [npmCliPath, 'run', 'build'], {
    cwd: componentRoot,
    env: process.env,
    stdio: 'inherit',
  });
  if (build.error) throw build.error;
  if (build.status !== 0) {
    throw new Error(`P6-004 prerequisite build failed with exit code ${build.status}.`);
  }
}

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
const readJson = async (filePath) => JSON.parse(await readFile(filePath, 'utf8'));
const waitForJson = async (filePath, predicate = () => true, timeoutMs = 30_000) => {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const value = await readJson(filePath);
      if (predicate(value)) return value;
    } catch (error) {
      if (error?.code !== 'ENOENT' && !(error instanceof SyntaxError)) throw error;
      lastError = error;
    }
    await sleep(100);
  }
  throw new Error(`Timed out waiting for P6-004 evidence at ${filePath}.`, { cause: lastError });
};

const waitFor = async (predicate, message, timeoutMs = 15_000) => {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await sleep(100);
  }
  throw new Error(message);
};

const temporaryRoot = await mkdtemp(path.join(os.tmpdir(), 'vscode-lsp-mcp-p6-004-'));
const nonce = path.basename(temporaryRoot).slice(-8);
const alphaName = `p6-004-alpha-${nonce}`;
const betaName = `p6-004-beta-${nonce}`;
const alphaRoot = path.join(temporaryRoot, alphaName);
const betaRoot = path.join(temporaryRoot, betaName);
const controlRoot = path.join(temporaryRoot, '.p6-004');
const fixtureTemplate = path.join(componentRoot, 'tests', 'fixtures', 'extension-host-all-tools');
const reportPath = process.env.P6_004_REPORT_PATH ?? path.join(temporaryRoot, 'p6-004-report.json');
const stdoutCapturePath = path.join(controlRoot, 'stdio-out.jsonl');
const stdinCapturePath = path.join(controlRoot, 'stdio-in.jsonl');
const extensionTestsPath = path.join(
  componentRoot,
  'packages',
  'extension',
  'dist',
  'stage-e-extension-host.js',
);

if (process.platform !== 'win32') {
  throw new Error('P6-004 is maintained only on Windows.');
}
const platform = 'win32';
const windowsSecurity = {
  ensureSecureRuntimeDirectory,
  verifySecureRegistryFile,
};
const runtimeLayout = await ensureRuntimeDirectory({
  platform,
  environment: process.env,
  windowsSecurity,
});

const hostPaths = (key) => ({
  ready: path.join(controlRoot, `${key}-ready.json`),
  state: path.join(controlRoot, `${key}-state.json`),
  stop: path.join(controlRoot, `${key}-stop`),
  userData: path.join(controlRoot, `${key}-user-data`),
  extensions: path.join(controlRoot, `${key}-extensions`),
});

const startHost = (key, fixtureRoot, fixtureName, hostLabel) => {
  const paths = hostPaths(key);
  const promise = runTests({
    version: process.env.VSCODE_TEST_VERSION ?? '1.128.0',
    extensionDevelopmentPath: path.join(componentRoot, 'packages', 'extension'),
    extensionTestsPath,
    launchArgs: [
      fixtureRoot,
      '--disable-extensions',
      '--disable-updates',
      '--disable-workspace-trust',
      '--skip-welcome',
      '--skip-release-notes',
      '--user-data-dir',
      paths.userData,
      '--extensions-dir',
      paths.extensions,
    ],
    extensionTestsEnv: {
      STAGE_E_FIXTURE_NAME: fixtureName,
      STAGE_E_HOST_LABEL: hostLabel,
      STAGE_E_READY_PATH: paths.ready,
      STAGE_E_STATE_PATH: paths.state,
      STAGE_E_STOP_PATH: paths.stop,
    },
  });
  promise.catch(() => undefined);
  return { key, fixtureName, hostLabel, paths, promise };
};

const waitForHostReady = async (host) => Promise.race([
  waitForJson(host.paths.ready),
  host.promise.then(() => {
    throw new Error(`${host.key} exited before publishing readiness.`);
  }),
]);

const stopHost = async (host) => {
  await writeFile(host.paths.stop, 'stop\n', 'utf8');
  await host.promise;
  return readJson(host.paths.state);
};

const registryRecords = async () => {
  const entries = await readdir(runtimeLayout.registrations, { withFileTypes: true });
  const records = [];
  for (const entry of entries) {
    if (!entry.isFile() || !entry.name.endsWith('.json')) continue;
    const filePath = path.join(runtimeLayout.registrations, entry.name);
    try {
      const raw = await readFile(filePath, 'utf8');
      records.push({ filePath, raw, value: JSON.parse(raw) });
    } catch {
      // Other processes may update their own registry records concurrently.
    }
  }
  return records;
};

const findFixtureRecord = async (fixtureName) => {
  const matches = (await registryRecords()).filter(
    ({ value }) => value?.kind === 'usable' && value?.workspaceName === fixtureName,
  );
  assert.equal(matches.length, 1, `Expected one live registry record for ${fixtureName}.`);
  return matches[0];
};

const writeSecureRegistryFile = async (filePath, payload) => {
  await writeFile(filePath, payload, { encoding: 'utf8', flag: 'wx', mode: 0o600 });
  if (platform === 'win32') {
    assert.equal(verifySecureRegistryFile(filePath), true, 'Test registry file DACL is unsafe.');
  } else {
    await chmod(filePath, 0o600);
  }
};

const parseJsonLines = (text, label) => {
  const lines = text.split(/\r?\n/u).filter((line) => line.length > 0);
  assert.ok(lines.length > 0, `${label} capture is empty.`);
  return lines.map((line, index) => {
    let value;
    try {
      value = JSON.parse(line);
    } catch (error) {
      throw new Error(`${label} line ${index + 1} is not JSON-RPC: ${line.slice(0, 200)}`, {
        cause: error,
      });
    }
    assert.equal(value?.jsonrpc, '2.0', `${label} line ${index + 1} is not JSON-RPC 2.0.`);
    return value;
  });
};

const forbiddenKeys = new Set([
  'authToken',
  'endpoint',
  'instanceId',
  'provider',
  'uri',
  'workspaceGeneration',
]);
const assertNoInternalLeak = (value) => {
  const visit = (candidate) => {
    if (Array.isArray(candidate)) {
      candidate.forEach(visit);
      return;
    }
    if (candidate === null || typeof candidate !== 'object') return;
    for (const [key, nested] of Object.entries(candidate)) {
      assert.equal(forbiddenKeys.has(key), false, `Internal key leaked: ${key}.`);
      visit(nested);
    }
  };
  visit(value);
  const serialized = JSON.stringify(value).replaceAll('\\', '/').toLowerCase();
  for (const root of [temporaryRoot, alphaRoot, betaRoot]) {
    assert.equal(serialized.includes(root.replaceAll('\\', '/').toLowerCase()), false);
  }
  assert.equal(serialized.includes('file://'), false);
  assert.equal(serialized.includes('\\\\.\\pipe'), false);
};

let alpha1;
let alpha2;
let beta;
let client;
let transport;
let restoredRecordPath;
let invalidRecordPath;
let invalidInstanceId;
let serverStderr = '';
try {
  await Promise.all([
    cp(fixtureTemplate, alphaRoot, { recursive: true }),
    cp(fixtureTemplate, betaRoot, { recursive: true }),
    mkdir(controlRoot, { recursive: true }),
    mkdir(path.dirname(reportPath), { recursive: true }),
  ]);
  const references = Array.from({ length: 140 }, (_, index) => `reference_${index + 1}`).join('\n');
  await Promise.all([
    writeFile(path.join(alphaRoot, 'src', 'references.p64'), `${references}\n`, 'utf8'),
    writeFile(path.join(betaRoot, 'src', 'references.p64'), `${references}\n`, 'utf8'),
  ]);

  transport = new StdioClientTransport({
    command: process.execPath,
    args: [
      path.join(componentRoot, 'tests', 'integration', 'stdio-capture-proxy.mjs'),
      stdoutCapturePath,
      stdinCapturePath,
      path.join(componentRoot, 'packages', 'server', 'dist', 'cli.js'),
    ],
    cwd: componentRoot,
    stderr: 'pipe',
  });
  transport.stderr?.setEncoding('utf8');
  transport.stderr?.on('data', (chunk) => {
    serverStderr += chunk;
    if (serverStderr.length > 200_000) throw new Error('P6-004 server stderr exceeded its bound.');
  });
  client = new Client({ name: 'p6-004-all-tools', version: '1.0.0' });
  await client.connect(transport);

  const successfulTools = new Set();
  const failedTools = new Set();
  let yamlOnlyCalls = 0;
  const semanticResponses = [];
  const call = async (name, argumentsValue, expectedOk) => {
    const raw = await client.callTool({ name, arguments: argumentsValue });
    assert.equal(raw.structuredContent, undefined, `${name} duplicated YAML as structuredContent.`);
    assert.equal(raw.content.length, 1, `${name} returned an unexpected content count.`);
    const textContent = raw.content[0];
    assert.equal(textContent?.type, 'text', `${name} did not return YAML text content.`);
    const response = decodeYamlText(textContent.text);
    assertToolOutput(name, response);
    yamlOnlyCalls += 1;
    assert.equal(response.ok, expectedOk, `${name} returned the wrong envelope state.`);
    assert.equal(raw.isError, expectedOk ? undefined : true);
    (expectedOk ? successfulTools : failedTools).add(name);
    assertNoInternalLeak(raw);
    semanticResponses.push(raw);
    return { raw, response };
  };

  const initialList = await call('list_workspaces', {}, true);
  assert.equal(initialList.response.data.results.some(
    (workspace) => workspace.name === alphaName || workspace.name === betaName,
  ), false);

  const listedTools = await client.listTools();
  assert.deepEqual(listedTools.tools.map(({ name }) => name), [...TOOL_NAMES]);
  for (const [index, definition] of TOOL_DEFINITIONS.entries()) {
    const listed = listedTools.tools[index];
    assert.ok(listed);
    assert.deepEqual(listed.inputSchema, definition.inputSchema);
    assert.equal(listed.outputSchema, undefined);
  }

  alpha1 = startHost('alpha-1', alphaRoot, alphaName, 'alpha');
  beta = startHost('beta-1', betaRoot, betaName, 'beta');
  const [alphaReady, betaReady] = await Promise.all([
    waitForHostReady(alpha1),
    waitForHostReady(beta),
  ]);

  const discover = async () => {
    const listed = await call('list_workspaces', { resultStart: 1, resultEnd: 100 }, true);
    const alphaMatches = listed.response.data.results.filter(({ name }) => name === alphaName);
    const betaMatches = listed.response.data.results.filter(({ name }) => name === betaName);
    return { alphaMatches, betaMatches };
  };
  const discovered = await discover();
  assert.equal(discovered.alphaMatches.length, 1);
  assert.equal(discovered.betaMatches.length, 1);
  const alphaWorkspace = discovered.alphaMatches[0];
  const betaWorkspace = discovered.betaMatches[0];
  assert.notEqual(alphaWorkspace.workspaceId, betaWorkspace.workspaceId);

  const semanticArguments = (workspaceId) => ({
    workspaceId,
    file: 'src/semantic.p64',
    line: 1,
    column: 1,
  });
  const health = await call('health_check', {
    workspaceId: alphaWorkspace.workspaceId,
    file: 'src/semantic.p64',
  }, true);
  assert.equal(health.response.data.results.some(({ status }) => status === 'healthy'), true);

  const capabilities = await call('get_capabilities', {
    workspaceId: alphaWorkspace.workspaceId,
    file: 'src/semantic.p64',
    capabilities: ['references'],
  }, true);
  assert.equal(capabilities.response.data.results[0]?.status, 'available');

  const alphaSymbols = await call('workspace_symbols', {
    workspaceId: alphaWorkspace.workspaceId,
    query: 'WorkspaceSymbol',
  }, true);
  assert.deepEqual(alphaSymbols.response.data.results.map(({ name }) => name), [
    'alphaWorkspaceSymbol',
  ]);
  const betaSymbols = await call('workspace_symbols', {
    workspaceId: betaWorkspace.workspaceId,
    query: 'WorkspaceSymbol',
  }, true);
  assert.deepEqual(betaSymbols.response.data.results.map(({ name }) => name), [
    'betaWorkspaceSymbol',
  ]);

  const documentSymbols = await call('document_symbols', {
    workspaceId: alphaWorkspace.workspaceId,
    file: 'src/semantic.p64',
  }, true);
  assert.equal(documentSymbols.response.data.results[0]?.path[0], 'alphaDocumentSymbol');

  const symbolInfo = await call('symbol_info', {
    ...semanticArguments(alphaWorkspace.workspaceId),
    include: ['hover', 'declaration', 'definition', 'typeDefinition', 'implementation'],
  }, true);
  assert.ok(symbolInfo.response.data.available >= 5);

  const referencesResult = await call('get_references', {
    workspaceId: alphaWorkspace.workspaceId,
    file: 'src/references.p64',
    line: 1,
    column: 1,
    resultStart: 41,
    resultEnd: 60,
  }, true);
  assert.equal(referencesResult.response.data.available, 140);
  assert.equal(referencesResult.response.data.results.length, 20);
  assert.equal(referencesResult.response.data.results[0]?.line, 41);
  assert.equal(referencesResult.response.data.results.at(-1)?.line, 60);

  const verifiedCandidates = await call('verify_symbol_candidates', {
    ...semanticArguments(alphaWorkspace.workspaceId),
    candidates: [{
      file: 'src/semantic.p64',
      line: 1,
      column: 1,
    }],
    timeoutMs: 30_000,
  }, true);
  assert.deepEqual(verifiedCandidates.response.data.results.map(({ status }) => status), [
    'verified',
  ]);

  const callHierarchy = await call('get_call_hierarchy', {
    ...semanticArguments(alphaWorkspace.workspaceId),
    direction: 'both',
    maxDepth: 1,
  }, true);
  assert.equal(callHierarchy.response.data.available, 3);

  const typeHierarchy = await call('get_type_hierarchy', {
    ...semanticArguments(alphaWorkspace.workspaceId),
    direction: 'both',
    maxDepth: 1,
  }, true);
  assert.equal(typeHierarchy.response.data.available, 3);

  const diagnostics = await call('get_diagnostics', {
    workspaceId: alphaWorkspace.workspaceId,
    scope: 'files',
    files: ['src/semantic.p64'],
  }, true);
  assert.equal(diagnostics.response.data.results[0]?.message, 'alpha diagnostic');

  const rename = await call('rename_preview', {
    workspaceId: alphaWorkspace.workspaceId,
    file: 'src/rename.p64',
    line: 1,
    column: 2,
    newName: 'alphaNewName',
    includeGlobs: ['src/rename.p64'],
  }, true);
  assert.ok(rename.response.data.previewId);
  const renameApply = await call('rename_apply', {
    previewId: rename.response.data.previewId,
  }, true);
  assert.deepEqual(renameApply.response.data.changedFiles, ['src/rename.p64']);

  const actions = await call('code_actions', {
    workspaceId: alphaWorkspace.workspaceId,
    file: 'src/action.p64',
    range: { startLine: 1, startColumn: 1, endLine: 1, endColumn: 2 },
    onlyKinds: ['quickfix'],
  }, true);
  assert.ok(actions.response.data.actionSetId);
  assert.equal(actions.response.data.results.length, 1);
  const actionPreview = await call('code_action_preview', {
    actionSetId: actions.response.data.actionSetId,
    actionId: actions.response.data.results[0].actionId,
  }, true);
  assert.ok(actionPreview.response.data.previewId);
  const actionApply = await call('code_action_apply', {
    previewId: actionPreview.response.data.previewId,
  }, true);
  assert.deepEqual(actionApply.response.data.changedFiles, ['src/action.p64']);

  const format = await call('format_preview', {
    workspaceId: alphaWorkspace.workspaceId,
    file: 'src/format.p64',
  }, true);
  assert.ok(format.response.data.previewId);
  const formatApply = await call('format_apply', {
    previewId: format.response.data.previewId,
  }, true);
  assert.deepEqual(formatApply.response.data.changedFiles, ['src/format.p64']);

  const identity = async (workspaceId) => call('execute_command', {
    workspaceId,
    target: { kind: 'command', commandId: 'p6.alltools.identity' },
  }, true);
  const alphaIdentity = await identity(alphaWorkspace.workspaceId);
  const betaIdentity = await identity(betaWorkspace.workspaceId);
  assert.deepEqual(alphaIdentity.response.data.result, { fixtureName: alphaName, hostLabel: 'alpha' });
  assert.deepEqual(betaIdentity.response.data.result, { fixtureName: betaName, hostLabel: 'beta' });

  for (const toolName of TOOL_NAMES) {
    const invalid = await call(toolName, { __p6Invalid: true }, false);
    assert.equal(invalid.response.error.code, 'INVALID_ARGUMENT');
  }
  assert.deepEqual([...successfulTools].sort(), [...TOOL_NAMES].sort());
  assert.deepEqual([...failedTools].sort(), [...TOOL_NAMES].sort());

  const alphaRecord = await findFixtureRecord(alphaName);
  const alpha1Final = await stopHost(alpha1);
  alpha1 = undefined;
  assert.deepEqual(alpha1Final.memory.rename, {
    open: true,
    dirty: true,
    text: 'alphaNewName alphaNewName\n',
  });
  assert.deepEqual(alpha1Final.memory.action, {
    open: true,
    dirty: true,
    text: 'alpha_ACTION_NEW\n',
  });
  assert.deepEqual(alpha1Final.memory.format, {
    open: true,
    dirty: true,
    text: 'alpha_FORMATTED\n',
  });

  const oldSemanticRoute = await call('get_references', {
    workspaceId: alphaWorkspace.workspaceId,
    file: 'src/references.p64',
    line: 1,
    column: 1,
  }, false);
  assert.equal(oldSemanticRoute.response.error.code, 'WORKSPACE_DISCONNECTED');
  const oldCommandRoute = await call('execute_command', {
    workspaceId: alphaWorkspace.workspaceId,
    target: { kind: 'command', commandId: 'p6.alltools.identity' },
  }, false);
  assert.equal(oldCommandRoute.response.error.code, 'WORKSPACE_DISCONNECTED');

  await waitFor(
    async () => !(await readdir(runtimeLayout.registrations)).includes(path.basename(alphaRecord.filePath)),
    'The retired alpha registration was not removed.',
  );
  restoredRecordPath = alphaRecord.filePath;
  await writeSecureRegistryFile(restoredRecordPath, alphaRecord.raw);
  invalidInstanceId = randomUUID();
  invalidRecordPath = path.join(runtimeLayout.registrations, `${invalidInstanceId}.json`);
  await writeSecureRegistryFile(invalidRecordPath, '{"invalid":true}\n');

  const withDeadEndpoint = await discover();
  assert.equal(withDeadEndpoint.alphaMatches.length, 0);
  assert.equal(withDeadEndpoint.betaMatches.length, 1);
  await waitFor(async () => {
    const entries = await readdir(runtimeLayout.quarantine);
    return entries.some((entry) => entry.startsWith(`${invalidInstanceId}.`));
  }, 'The malformed registration was not quarantined.');

  alpha2 = startHost('alpha-2', alphaRoot, alphaName, 'alpha-restart');
  await waitForHostReady(alpha2);
  const alpha2Before = await waitForJson(alpha2.paths.state);
  assert.equal(alpha2Before.counters.references, 0);
  assert.equal(alpha2Before.counters.commands, 0);

  const oldSemanticAfterRestart = await call('get_references', {
    workspaceId: alphaWorkspace.workspaceId,
    file: 'src/references.p64',
    line: 1,
    column: 1,
  }, false);
  assert.equal(oldSemanticAfterRestart.response.error.code, 'WORKSPACE_DISCONNECTED');
  const oldCommandAfterRestart = await call('execute_command', {
    workspaceId: alphaWorkspace.workspaceId,
    target: { kind: 'command', commandId: 'p6.alltools.identity' },
  }, false);
  assert.equal(oldCommandAfterRestart.response.error.code, 'WORKSPACE_DISCONNECTED');
  await sleep(250);
  const alpha2AfterOldRoutes = await readJson(alpha2.paths.state);
  assert.equal(alpha2AfterOldRoutes.counters.references, 0);
  assert.equal(alpha2AfterOldRoutes.counters.commands, 0);

  const recoveredDiscovery = await discover();
  const recoveryDiscoveryAttempts = 1;
  assert.equal(recoveredDiscovery.alphaMatches.length, 1);
  assert.equal(recoveredDiscovery.betaMatches.length, 1);
  const recoveredWorkspace = recoveredDiscovery.alphaMatches[0];
  assert.notEqual(recoveredWorkspace.workspaceId, alphaWorkspace.workspaceId);
  const recoveredReferences = await call('get_references', {
    workspaceId: recoveredWorkspace.workspaceId,
    file: 'src/references.p64',
    line: 1,
    column: 1,
    resultStart: 1,
    resultEnd: 20,
  }, true);
  assert.equal(recoveredReferences.response.data.available, 140);
  const recoveredIdentity = await identity(recoveredWorkspace.workspaceId);
  assert.deepEqual(recoveredIdentity.response.data.result, {
    fixtureName: alphaName,
    hostLabel: 'alpha-restart',
  });
  const recoveredState = await waitForJson(
    alpha2.paths.state,
    (value) => value.counters.references >= 1 && value.counters.commands >= 1,
  );
  assert.equal(recoveredState.counters.references, 1);
  assert.equal(recoveredState.counters.commands, 1);

  const [alpha2Final, betaFinal] = await Promise.all([
    stopHost(alpha2),
    stopHost(beta),
  ]);
  alpha2 = undefined;
  beta = undefined;
  assert.equal(betaFinal.counters.renames, 0);
  assert.equal(betaFinal.counters.codeActions, 0);
  assert.equal(betaFinal.counters.formatting, 0);
  assert.ok(betaFinal.counters.workspaceSymbols >= 1);
  assert.equal(betaFinal.counters.commands, 1);
  assert.equal(alpha2Final.counters.references, 1);
  assert.equal(alpha2Final.counters.commands, 1);

  await client.close();
  client = undefined;
  transport = undefined;
  await waitFor(
    async () => {
      try {
        return (await readFile(stdoutCapturePath)).length > 0 && (await readFile(stdinCapturePath)).length > 0;
      } catch {
        return false;
      }
    },
    'The stdio capture proxy did not flush its evidence.',
  );
  const stdoutText = await readFile(stdoutCapturePath, 'utf8');
  const stdinText = await readFile(stdinCapturePath, 'utf8');
  const stdoutFrames = parseJsonLines(stdoutText, 'server stdout');
  const stdinFrames = parseJsonLines(stdinText, 'client stdin');
  const methods = stdinFrames.map((frame) => frame.method).filter(Boolean);
  assert.equal(methods.filter((method) => method === 'initialize').length, 1);
  assert.equal(methods.includes('notifications/initialized'), true);
  assert.equal(methods.filter((method) => method === 'tools/list').length, 1);
  assert.ok(methods.filter((method) => method === 'tools/call').length >= 36);
  stdoutFrames.forEach(assertNoInternalLeak);
  semanticResponses.forEach(assertNoInternalLeak);

  const report = {
    schemaVersion: 1,
    task: 'P6-004',
    vscodeVersion: alphaReady.vscodeVersion ?? betaReady.vscodeVersion,
    listedToolCount: listedTools.tools.length,
    listedTools: listedTools.tools.map(({ name }) => name),
    successEnvelopeTools: [...successfulTools].sort(),
    failureEnvelopeTools: [...failedTools].sort(),
    yamlOnlyCalls,
    multiWorkspace: {
      simultaneousHosts: 2,
      distinctWorkspaceIds: alphaWorkspace.workspaceId !== betaWorkspace.workspaceId,
      semanticRoutesIsolated: alphaSymbols.response.data.results[0]?.name === 'alphaWorkspaceSymbol' &&
        betaSymbols.response.data.results[0]?.name === 'betaWorkspaceSymbol',
      commandRoutesIsolated: alphaIdentity.response.data.result.hostLabel === 'alpha' &&
        betaIdentity.response.data.result.hostLabel === 'beta',
      betaMutationProviderCalls: {
        rename: betaFinal.counters.renames,
        codeActions: betaFinal.counters.codeActions,
        formatting: betaFinal.counters.formatting,
      },
    },
    boundedReferences: {
      available: referencesResult.response.data.available,
      returned: referencesResult.response.data.results.length,
      firstLine: referencesResult.response.data.results[0]?.line,
      lastLine: referencesResult.response.data.results.at(-1)?.line,
    },
    recovery: {
      workspaceIdChanged: recoveredWorkspace.workspaceId !== alphaWorkspace.workspaceId,
      discoveryAttempts: recoveryDiscoveryAttempts,
      deadEndpointExcluded: withDeadEndpoint.alphaMatches.length === 0,
      malformedRegistrationQuarantined: true,
      oldSemanticErrorCode: oldSemanticAfterRestart.response.error.code,
      oldCommandErrorCode: oldCommandAfterRestart.response.error.code,
      oldRoutesNotReplayed: alpha2AfterOldRoutes.counters.references === 0 &&
        alpha2AfterOldRoutes.counters.commands === 0,
      recoveredReferenceProviderCalls: recoveredState.counters.references,
      recoveredCommandCalls: recoveredState.counters.commands,
    },
    stdio: {
      initializeRequests: methods.filter((method) => method === 'initialize').length,
      listToolsRequests: methods.filter((method) => method === 'tools/list').length,
      callToolRequests: methods.filter((method) => method === 'tools/call').length,
      stdoutFrames: stdoutFrames.length,
      stdoutBytes: Buffer.byteLength(stdoutText, 'utf8'),
      stdoutJsonRpcOnly: true,
      serverStderrBytes: Buffer.byteLength(serverStderr, 'utf8'),
    },
    leakageChecksPassed: true,
  };
  await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  process.stdout.write(`P6-004 integration report:\n${JSON.stringify(report, null, 2)}\n`);
} finally {
  for (const host of [alpha1, alpha2, beta]) {
    if (host !== undefined) {
      await writeFile(host.paths.stop, 'stop\n', 'utf8').catch(() => undefined);
    }
  }
  await Promise.allSettled([alpha1?.promise, alpha2?.promise, beta?.promise].filter(Boolean));
  await client?.close().catch(() => undefined);
  for (const filePath of [restoredRecordPath, invalidRecordPath]) {
    if (filePath !== undefined) await rm(filePath, { force: true }).catch(() => undefined);
  }
  if (invalidInstanceId !== undefined) {
    const quarantined = await readdir(runtimeLayout.quarantine).catch(() => []);
    await Promise.all(quarantined
      .filter((entry) => entry.startsWith(`${invalidInstanceId}.`))
      .map((entry) => rm(path.join(runtimeLayout.quarantine, entry), { force: true })));
  }
  const fixtureRecords = await registryRecords().catch(() => []);
  await Promise.all(fixtureRecords
    .filter(({ value }) => value?.workspaceName === alphaName || value?.workspaceName === betaName)
    .map(({ filePath }) => rm(filePath, { force: true })));
  await rm(temporaryRoot, { recursive: true, force: true });
}
