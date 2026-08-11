import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { runTests } from '@vscode/test-electron';
import { assertToolOutput, decodeYamlText } from '@simplechat/vscode-lsp-mcp-protocol';

const componentRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const npmCliPath = process.env.npm_execpath;
if (!npmCliPath) {
  throw new Error('npm_execpath is required; run this gate through npm run test:stage-c.');
}

const build = spawnSync(process.execPath, [npmCliPath, 'run', 'build'], {
  cwd: componentRoot,
  env: process.env,
  stdio: 'inherit',
});
if (build.error) throw build.error;
if (build.status !== 0) {
  throw new Error(`Stage C prerequisite build failed with exit code ${build.status}.`);
}

const temporaryRoot = await mkdtemp(path.join(os.tmpdir(), 'vscode-lsp-mcp-stage-c-'));
const fixtureName = path.basename(temporaryRoot);
const fixtureTemplate = path.join(
  componentRoot,
  'tests',
  'fixtures',
  'extension-host-hierarchy-lifecycle',
);
const reportPath = process.env.STAGE_C_REPORT_PATH ?? path.join(temporaryRoot, 'stage-c-report.json');
const controlRoot = path.join(temporaryRoot, '.stage-c');
const extensionTestsPath = path.join(
  componentRoot,
  'packages',
  'extension',
  'dist',
  'stage-c-extension-host.js',
);

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

const readJson = async (filePath) => JSON.parse(await readFile(filePath, 'utf8'));

const waitForJson = async (filePath, predicate = () => true, timeoutMs = 15_000) => {
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
  throw new Error(`Timed out waiting for Stage C evidence at ${filePath}.`, { cause: lastError });
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
  assert.equal(serialized.includes(temporaryRoot.replaceAll('\\', '/').toLowerCase()), false);
  assert.equal(serialized.includes('file://'), false);
  assert.equal(serialized.includes('vscode.execute'), false);
  assert.equal(serialized.includes('\\\\.\\pipe'), false);
};

const hostPaths = (hostLabel) => ({
  ready: path.join(controlRoot, `${hostLabel}-ready.json`),
  state: path.join(controlRoot, `${hostLabel}-state.json`),
  stop: path.join(controlRoot, `${hostLabel}-stop`),
  userData: path.join(controlRoot, `${hostLabel}-user-data`),
  extensions: path.join(controlRoot, `${hostLabel}-extensions`),
});

const startHost = (hostLabel) => {
  const paths = hostPaths(hostLabel);
  const promise = runTests({
    version: process.env.VSCODE_TEST_VERSION ?? '1.128.0',
    extensionDevelopmentPath: path.join(componentRoot, 'packages', 'extension'),
    extensionTestsPath,
    launchArgs: [
      temporaryRoot,
      '--disable-extensions',
      '--disable-workspace-trust',
      '--skip-welcome',
      '--skip-release-notes',
      '--user-data-dir',
      paths.userData,
      '--extensions-dir',
      paths.extensions,
    ],
    extensionTestsEnv: {
      STAGE_C_FIXTURE_NAME: fixtureName,
      STAGE_C_HOST_LABEL: hostLabel,
      STAGE_C_READY_PATH: paths.ready,
      STAGE_C_STATE_PATH: paths.state,
      STAGE_C_STOP_PATH: paths.stop,
    },
  });
  promise.catch(() => undefined);
  return { paths, promise };
};

const waitForHostReady = async (host) => Promise.race([
  waitForJson(host.paths.ready),
  host.promise.then(() => {
    throw new Error('Stage C Extension Host exited before publishing readiness.');
  }),
]);

const stopHost = async (host) => {
  await writeFile(host.paths.stop, 'stop\n', 'utf8');
  await host.promise;
};

let host1;
let host2;
let client;
try {
  await cp(fixtureTemplate, temporaryRoot, { recursive: true });
  await mkdir(controlRoot, { recursive: true });

  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [path.join(componentRoot, 'packages', 'server', 'dist', 'cli.js')],
    cwd: componentRoot,
    stderr: 'pipe',
  });
  client = new Client({ name: 'stage-c-integration', version: '1.0.0' });
  await client.connect(transport);

  const call = async (name, argumentsValue) => {
    const raw = await client.callTool({ name, arguments: argumentsValue });
    assert.equal(raw.structuredContent, undefined);
    assert.equal(raw.content.length, 1);
    assert.equal(raw.content[0]?.type, 'text');
    const response = decodeYamlText(raw.content[0].text);
    assertToolOutput(name, response);
    return { raw, response };
  };
  const findFixtureWorkspace = async () => {
    const listed = await call('list_workspaces', {});
    assert.equal(listed.response.ok, true);
    const matches = listed.response.data.results.filter((workspace) => workspace.name === fixtureName);
    assert.equal(matches.length, 1, 'The Stage C workspace was not uniquely discoverable.');
    return matches[0];
  };
  const hierarchyArguments = (workspaceId, file) => ({
    workspaceId,
    file,
    line: file === 'src/hierarchy.ts' ? 2 : 1,
    column: 14,
    direction: 'both',
    maxDepth: 2,
  });

  const beforeActivation = await call('list_workspaces', {});
  assert.equal(beforeActivation.response.ok, true);
  const workspaceAbsentBeforeActivation = !beforeActivation.response.data.results.some(
    (workspace) => workspace.name === fixtureName,
  );
  assert.equal(workspaceAbsentBeforeActivation, true);

  host1 = startHost('host-1');
  const ready1 = await waitForHostReady(host1);
  const workspace1 = await findFixtureWorkspace();

  const supported = await call(
    'get_type_hierarchy',
    hierarchyArguments(workspace1.workspaceId, 'src/hierarchy.ts'),
  );
  assert.equal(supported.response.ok, true);
  assert.equal(supported.response.data.available, 3);
  assert.deepEqual(
    new Set(supported.response.data.results.map((entry) => entry.symbol.name)),
    new Set(['BaseType', 'MiddleType', 'LeafType']),
  );

  const empty = await call(
    'get_type_hierarchy',
    hierarchyArguments(workspace1.workspaceId, 'src/empty.ts'),
  );
  assert.equal(empty.response.ok, true);
  assert.equal(empty.response.data.available, 0);

  const emptyCapability = await call('get_capabilities', {
    workspaceId: workspace1.workspaceId,
    file: 'src/empty.ts',
    capabilities: ['typeHierarchy'],
  });
  assert.equal(emptyCapability.response.ok, true);
  assert.equal(emptyCapability.response.data.results[0]?.status, 'unknown');
  assert.equal(emptyCapability.response.data.results[0]?.reason, 'probe_returned_no_evidence');

  const timeoutStarted = Date.now();
  const timedOut = await call(
    'get_type_hierarchy',
    hierarchyArguments(workspace1.workspaceId, 'src/timeout.ts'),
  );
  const timeoutElapsedMs = Date.now() - timeoutStarted;
  assert.equal(timedOut.raw.isError, true);
  assert.equal(timedOut.response.ok, false);
  assert.equal(timedOut.response.error.code, 'PROVIDER_TIMEOUT');
  assert.ok(timeoutElapsedMs >= 4_000 && timeoutElapsedMs < 8_000, `Unexpected timeout: ${timeoutElapsedMs}ms.`);

  const afterTimeout = await call(
    'get_type_hierarchy',
    hierarchyArguments(workspace1.workspaceId, 'src/empty.ts'),
  );
  assert.equal(afterTimeout.response.ok, true);

  const controller = new AbortController();
  const cancellation = client.callTool({
    name: 'get_type_hierarchy',
    arguments: hierarchyArguments(workspace1.workspaceId, 'src/cancel.ts'),
  }, undefined, { signal: controller.signal, timeout: 10_000 });
  await waitForJson(host1.paths.state, (state) => state.cancelPrepares >= 1);
  const cancellationStarted = Date.now();
  controller.abort();
  await assert.rejects(cancellation);
  const cancellationElapsedMs = Date.now() - cancellationStarted;
  assert.ok(cancellationElapsedMs < 2_000, `Cancellation took ${cancellationElapsedMs}ms.`);
  await sleep(250);

  let afterCancel = await call(
    'get_type_hierarchy',
    hierarchyArguments(workspace1.workspaceId, 'src/empty.ts'),
  );
  const afterCancelDeadline = Date.now() + 5_000;
  while (!afterCancel.response.ok && Date.now() < afterCancelDeadline) {
    await sleep(100);
    afterCancel = await call(
      'get_type_hierarchy',
      hierarchyArguments(workspace1.workspaceId, 'src/empty.ts'),
    );
  }
  assert.equal(afterCancel.response.ok, true);
  await stopHost(host1);

  host2 = startHost('host-2');
  const ready2 = await waitForHostReady(host2);
  const host2BeforeOldRoute = await readJson(host2.paths.state);
  assert.equal(host2BeforeOldRoute.hierarchyPrepares, 0);

  const oldRoute = await call(
    'get_type_hierarchy',
    hierarchyArguments(workspace1.workspaceId, 'src/hierarchy.ts'),
  );
  assert.equal(oldRoute.raw.isError, true);
  assert.equal(oldRoute.response.ok, false);
  assert.equal(oldRoute.response.error.code, 'WORKSPACE_DISCONNECTED');
  await sleep(250);
  const host2AfterOldRoute = await readJson(host2.paths.state);
  assert.equal(host2AfterOldRoute.hierarchyPrepares, 0, 'An interrupted request was replayed into the new host.');

  const workspace2 = await findFixtureWorkspace();
  assert.notEqual(workspace2.workspaceId, workspace1.workspaceId);
  const recovered = await call(
    'get_type_hierarchy',
    hierarchyArguments(workspace2.workspaceId, 'src/hierarchy.ts'),
  );
  assert.equal(recovered.response.ok, true);
  assert.equal(recovered.response.data.available, 3);
  const host2RecoveredState = await waitForJson(
    host2.paths.state,
    (state) => state.hierarchyPrepares >= 1,
  );
  assert.equal(host2RecoveredState.hierarchyPrepares, 1);

  [beforeActivation, supported, empty, emptyCapability, timedOut, afterTimeout, afterCancel, oldRoute, recovered]
    .forEach(({ raw }) => assertNoInternalLeak(raw));
  const report = {
    schemaVersion: 1,
    fixtureName,
    vscodeVersion: ready2.vscodeVersion ?? ready1.vscodeVersion,
    workspaceAbsentBeforeActivation,
    workspaceDiscoveredAfterActivation: workspace1.name === fixtureName,
    supportedEntries: supported.response.data.available,
    emptyEntries: empty.response.data.available,
    emptyCapabilityStatus: emptyCapability.response.data.results[0]?.status,
    emptyCapabilityReason: emptyCapability.response.data.results[0]?.reason,
    timeoutErrorCode: timedOut.response.error.code,
    timeoutElapsedMs,
    cancellationDispatched: true,
    cancellationElapsedMs,
    responsiveAfterTimeout: afterTimeout.response.ok,
    responsiveAfterCancel: afterCancel.response.ok,
    workspaceIdChanged: workspace2.workspaceId !== workspace1.workspaceId,
    oldRouteErrorCode: oldRoute.response.error.code,
    noReplayProviderCalls: host2AfterOldRoute.hierarchyPrepares,
    recoveredProviderCalls: host2RecoveredState.hierarchyPrepares,
    leakageChecksPassed: true,
  };
  await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  await stopHost(host2);
  process.stdout.write(`Stage C integration report:\n${JSON.stringify(report, null, 2)}\n`);
} finally {
  for (const host of [host1, host2]) {
    if (host !== undefined) {
      await writeFile(host.paths.stop, 'stop\n', 'utf8').catch(() => undefined);
    }
  }
  await Promise.allSettled([host1?.promise, host2?.promise].filter(Boolean));
  await client?.close().catch(() => undefined);
  await rm(temporaryRoot, { recursive: true, force: true });
}
