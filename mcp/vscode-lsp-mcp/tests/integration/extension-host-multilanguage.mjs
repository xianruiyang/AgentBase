import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import {
  cp,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  symlink,
  writeFile,
} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { runTests } from '@vscode/test-electron';
import {
  assertToolOutput,
  decodeYamlText,
} from '@simplechat/vscode-lsp-mcp-protocol';

const componentRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const npmCliPath = process.env.npm_execpath;
if (!npmCliPath) {
  throw new Error('npm_execpath is required; run this audit through npm run test:manual:multilanguage.');
}

if (process.env.P6_005_SKIP_BUILD !== '1') {
  const build = spawnSync(process.execPath, [npmCliPath, 'run', 'build'], {
    cwd: componentRoot,
    env: process.env,
    stdio: 'inherit',
  });
  if (build.error) throw build.error;
  if (build.status !== 0) {
    throw new Error(`P6-005 prerequisite build failed with exit code ${build.status}.`);
  }
}

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
const readJson = async (filePath) => JSON.parse(await readFile(filePath, 'utf8'));
const waitForJson = async (filePath, timeoutMs = 160_000) => {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      return await readJson(filePath);
    } catch (error) {
      if (error?.code !== 'ENOENT' && !(error instanceof SyntaxError)) throw error;
      lastError = error;
    }
    await sleep(250);
  }
  throw new Error(`Timed out waiting for P6-005 evidence at ${filePath}.`, { cause: lastError });
};

const commandVersion = (command, args) => {
  const result = spawnSync(command, args, { encoding: 'utf8', windowsHide: true });
  return {
    available: result.error === undefined && result.status === 0,
    exitCode: result.status,
    firstLine: result.status === 0
      ? String(result.stdout).split(/\r?\n/u).find((line) => line.trim().length > 0)?.trim()
      : undefined,
  };
};

const findCppCompiler = () => {
  const result = spawnSync('where.exe', ['clang++.exe'], { encoding: 'utf8', windowsHide: true });
  if (result.status !== 0) return undefined;
  return String(result.stdout).split(/\r?\n/u).find((line) => line.trim().length > 0)?.trim();
};

const temporaryRoot = await mkdtemp(path.join(os.tmpdir(), 'vscode-lsp-mcp-p6-005-'));
const fixtureName = path.basename(temporaryRoot);
const fixtureTemplate = path.join(
  componentRoot,
  'tests',
  'fixtures',
  'extension-host-multilanguage',
);
const controlRoot = path.join(temporaryRoot, '.p6-005');
const readyPath = path.join(controlRoot, 'ready.json');
const statePath = path.join(controlRoot, 'state.json');
const stopPath = path.join(controlRoot, 'stop');
const isolatedExtensions = path.join(controlRoot, 'extensions');
const reportPath = process.env.P6_005_REPORT_PATH ?? path.join(temporaryRoot, 'p6-005-report.json');
const sourceExtensions = process.env.P6_005_EXTENSIONS_DIR ?? path.join(os.homedir(), '.vscode', 'extensions');
const selectedExtensionPrefixes = [
  'ms-vscode.cpptools-',
  'llvm-vs-code-extensions.vscode-clangd-',
  'ms-dotnettools.csharp-',
  'ms-dotnettools.csdevkit-',
  'ms-dotnettools.vscode-dotnet-runtime-',
];
const cppCompilerPath = process.env.P6_005_CPP_COMPILER_PATH ?? findCppCompiler();

const positionOfLast = (text, symbol) => {
  const offset = text.lastIndexOf(symbol);
  assert.ok(offset >= 0, `Fixture symbol ${symbol} is missing.`);
  const before = text.slice(0, offset + 1);
  const lines = before.split('\n');
  return { line: lines.length, column: lines.at(-1).length };
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
  assert.equal(serialized.includes('\\\\.\\pipe'), false);
};

let hostPromise;
let client;
let auditPhase = 'fixture-setup';
let readyEvidence;
try {
  await Promise.all([
    cp(fixtureTemplate, temporaryRoot, { recursive: true }),
    mkdir(isolatedExtensions, { recursive: true }),
    mkdir(path.dirname(reportPath), { recursive: true }),
  ]);

  const extensionEntries = await readdir(sourceExtensions, { withFileTypes: true });
  const selectedExtensions = extensionEntries
    .filter((entry) => entry.isDirectory() && selectedExtensionPrefixes.some(
      (prefix) => entry.name.toLowerCase().startsWith(prefix),
    ));
  await Promise.all(selectedExtensions.map((entry) => symlink(
    path.join(sourceExtensions, entry.name),
    path.join(isolatedExtensions, entry.name),
    process.platform === 'win32' ? 'junction' : 'dir',
  )));

  auditPhase = 'dotnet-restore';
  const restore = spawnSync('dotnet', ['restore', path.join(temporaryRoot, 'csharp', 'P6005.csproj'), '--nologo'], {
    cwd: path.join(temporaryRoot, 'csharp'),
    encoding: 'utf8',
    windowsHide: true,
  });
  const dotnetRestore = {
    exitCode: restore.status,
    succeeded: restore.error === undefined && restore.status === 0,
    stderr: String(restore.stderr ?? '').slice(0, 2_000),
  };

  auditPhase = 'extension-host-readiness';
  hostPromise = runTests({
    version: process.env.VSCODE_TEST_VERSION ?? '1.128.0',
    extensionDevelopmentPath: path.join(componentRoot, 'packages', 'extension'),
    extensionTestsPath: path.join(
      componentRoot,
      'packages',
      'extension',
      'dist',
      'stage-f-extension-host.js',
    ),
    launchArgs: [
      temporaryRoot,
      '--disable-updates',
      '--disable-workspace-trust',
      '--skip-welcome',
      '--skip-release-notes',
      '--user-data-dir',
      path.join(controlRoot, 'user-data'),
      '--extensions-dir',
      isolatedExtensions,
    ],
    extensionTestsEnv: {
      STAGE_F_FIXTURE_NAME: fixtureName,
      STAGE_F_READY_PATH: readyPath,
      STAGE_F_STATE_PATH: statePath,
      STAGE_F_STOP_PATH: stopPath,
      ...(cppCompilerPath === undefined ? {} : { STAGE_F_CPP_COMPILER_PATH: cppCompilerPath }),
    },
  });
  hostPromise.catch(() => undefined);
  const ready = await Promise.race([
    waitForJson(readyPath),
    hostPromise.then(() => {
      throw new Error('P6-005 Extension Host exited before publishing readiness.');
    }),
  ]);
  readyEvidence = ready;

  auditPhase = 'companion-connect';
  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [path.join(componentRoot, 'packages', 'server', 'dist', 'cli.js')],
    cwd: componentRoot,
    stderr: 'pipe',
  });
  client = new Client({ name: 'p6-005-multilanguage', version: '1.0.0' });
  await client.connect(transport);
  let yamlOnlyCalls = 0;
  const call = async (name, argumentsValue) => {
    const raw = await client.callTool({ name, arguments: argumentsValue });
    assert.equal(raw.structuredContent, undefined);
    assert.equal(raw.content.length, 1);
    assert.equal(raw.content[0]?.type, 'text');
    const response = decodeYamlText(raw.content[0].text);
    assertToolOutput(name, response);
    assertNoInternalLeak(raw);
    yamlOnlyCalls += 1;
    return { raw, response };
  };

  const listed = await call('list_workspaces', { resultStart: 1, resultEnd: 100 });
  assert.equal(listed.response.ok, true);
  const matches = listed.response.data.results.filter(({ name }) => name === fixtureName);
  assert.equal(matches.length, 1, 'The P6-005 fixture workspace was not uniquely discoverable.');
  const workspaceId = matches[0].workspaceId;

  const source = {
    cpp: await readFile(path.join(temporaryRoot, 'cpp', 'main.cpp'), 'utf8'),
    csharp: await readFile(path.join(temporaryRoot, 'csharp', 'Program.cs'), 'utf8'),
  };
  const auditLanguage = async ({ key, file, symbol, newName }) => {
    const position = positionOfLast(source[key], symbol);
    const capabilities = await call('get_capabilities', {
      workspaceId,
      file,
      capabilities: ['definition', 'references', 'diagnostics', 'rename'],
    });
    const definition = await call('symbol_info', {
      workspaceId,
      file,
      ...position,
      include: ['definition'],
    });
    const references = await call('get_references', {
      workspaceId,
      file,
      ...position,
    });
    const diagnostics = await call('get_diagnostics', {
      workspaceId,
      scope: 'files',
      files: [file],
    });
    const renamePreview = await call('rename_preview', {
      workspaceId,
      file,
      ...position,
      newName,
    });
    let renameApply;
    if (renamePreview.response.ok && renamePreview.response.data.previewId !== undefined) {
      renameApply = await call('rename_apply', {
        previewId: renamePreview.response.data.previewId,
      });
    }
    const capabilityMap = capabilities.response.ok
      ? Object.fromEntries(capabilities.response.data.results.map((entry) => [entry.name, {
          status: entry.status,
          ...(entry.reason === undefined ? {} : { reason: entry.reason }),
        }]))
      : {};
    const verified = capabilities.response.ok &&
      definition.response.ok && definition.response.data.available >= 1 &&
      references.response.ok && references.response.data.available >= 2 &&
      diagnostics.response.ok && diagnostics.response.data.available >= 1 &&
      renamePreview.response.ok && renamePreview.response.data.changes.length >= 1 &&
      renameApply?.response.ok === true && renameApply.response.data.changedFiles.includes(file);
    return {
      verified,
      capabilityMap,
      definition: definition.response.ok
        ? { ok: true, available: definition.response.data.available }
        : { ok: false, errorCode: definition.response.error.code },
      references: references.response.ok
        ? { ok: true, available: references.response.data.available }
        : { ok: false, errorCode: references.response.error.code },
      diagnostics: diagnostics.response.ok
        ? { ok: true, available: diagnostics.response.data.available }
        : { ok: false, errorCode: diagnostics.response.error.code },
      renamePreview: renamePreview.response.ok
        ? { ok: true, changedFiles: renamePreview.response.data.changes.map((change) => change.file) }
        : { ok: false, errorCode: renamePreview.response.error.code },
      renameApply: renameApply === undefined
        ? { ok: false, errorCode: 'NOT_ATTEMPTED' }
        : renameApply.response.ok
          ? { ok: true, changedFiles: renameApply.response.data.changedFiles }
          : { ok: false, errorCode: renameApply.response.error.code },
    };
  };

  auditPhase = 'cpp-companion-audit';
  const cpp = await auditLanguage({
    key: 'cpp',
    file: 'cpp/main.cpp',
    symbol: 'CppAddP6005',
    newName: 'CppAddP6005Renamed',
  });
  auditPhase = 'csharp-companion-audit';
  const csharp = await auditLanguage({
    key: 'csharp',
    file: 'csharp/Program.cs',
    symbol: 'CsAddP6005',
    newName: 'CsAddP6005Renamed',
  });

  auditPhase = 'document-postconditions';
  await writeFile(stopPath, 'stop\n', 'utf8');
  await hostPromise;
  hostPromise = undefined;
  const finalState = await readJson(statePath);
  for (const [key, evidence, oldName, newName] of [
    ['cpp', cpp, 'CppAddP6005', 'CppAddP6005Renamed'],
    ['csharp', csharp, 'CsAddP6005', 'CsAddP6005Renamed'],
  ]) {
    const document = finalState.documents[key];
    if (evidence.verified) {
      assert.equal(document.dirty, true);
      assert.equal(document.visible, false);
      assert.equal(document.memoryText.includes(newName), true);
      assert.equal(document.memoryText.includes(oldName), false);
      assert.equal(document.diskText.includes(oldName), true);
      assert.equal(document.diskText.includes(newName), false);
    }
  }

  const report = {
    schemaVersion: 1,
    task: 'P6-005',
    outcome: 'completed',
    vscodeVersion: ready.vscodeVersion,
    binaries: {
      clangd: commandVersion('clangd', ['--version']),
      dotnet: commandVersion('dotnet', ['--version']),
      cppCompilerPath: cppCompilerPath ?? null,
    },
    linkedExtensionDirectories: selectedExtensions.map(({ name }) => name).sort(),
    extensions: ready.extensions,
    dotnetRestore,
    directProviders: ready.directProviders,
    companion: {
      yamlOnlyCalls,
      cpp,
      csharp,
    },
    documentPostconditions: finalState.documents,
    missingCapabilitiesExplicit: !cpp.verified || !csharp.verified,
  };
  auditPhase = 'report-write';
  await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  process.stdout.write(`P6-005 multi-language report:\n${JSON.stringify(report, null, 2)}\n`);
} catch (error) {
  const failureReport = {
    schemaVersion: 1,
    task: 'P6-005',
    outcome: 'failed',
    phase: auditPhase,
    error: {
      name: error instanceof Error ? error.name : 'Error',
      message: error instanceof Error ? error.message : String(error),
      ...(error instanceof Error && error.stack !== undefined
        ? { stack: error.stack.slice(0, 4_000) }
        : {}),
    },
    ...(readyEvidence === undefined ? {} : { readiness: readyEvidence }),
  };
  await mkdir(path.dirname(reportPath), { recursive: true }).catch(() => undefined);
  await writeFile(reportPath, `${JSON.stringify(failureReport, null, 2)}\n`, 'utf8').catch(() => undefined);
  throw error;
} finally {
  if (hostPromise !== undefined) {
    await writeFile(stopPath, 'stop\n', 'utf8').catch(() => undefined);
    await hostPromise.catch(() => undefined);
  }
  await client?.close().catch(() => undefined);
  await rm(temporaryRoot, { recursive: true, force: true });
}
