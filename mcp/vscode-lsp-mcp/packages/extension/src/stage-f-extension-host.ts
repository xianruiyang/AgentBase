import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import * as vscode from 'vscode';

const requiredEnvironment = (name: string): string => {
  const value = process.env[name];
  if (value === undefined || value.length === 0) {
    throw new Error(`Missing Stage F environment variable: ${name}.`);
  }
  return value;
};

const sleep = (milliseconds: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

const withTimeout = async <T>(promise: PromiseLike<T>, timeoutMs: number): Promise<T> => {
  let timer: NodeJS.Timeout | undefined;
  try {
    return await Promise.race([
      Promise.resolve(promise),
      new Promise<T>((_resolve, reject) => {
        timer = setTimeout(() => reject(new Error(`Operation timed out after ${timeoutMs}ms.`)), timeoutMs);
      }),
    ]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
};

const boundedError = (error: unknown): string =>
  (error instanceof Error ? error.message : String(error)).replaceAll('\r', ' ').replaceAll('\n', ' ').slice(0, 512);

const activateExtension = async (id: string) => {
  const extension = vscode.extensions.getExtension(id);
  if (extension === undefined) {
    return { id, present: false, active: false } as const;
  }
  try {
    await withTimeout(extension.activate(), 90_000);
    return {
      id,
      present: true,
      active: extension.isActive,
      version: String(extension.packageJSON.version ?? 'unknown'),
    } as const;
  } catch (error) {
    return {
      id,
      present: true,
      active: extension.isActive,
      version: String(extension.packageJSON.version ?? 'unknown'),
      activationError: boundedError(error),
    } as const;
  }
};

const symbolPosition = (document: vscode.TextDocument, symbol: string): vscode.Position => {
  const offset = document.getText().lastIndexOf(symbol);
  if (offset < 0) throw new Error(`Fixture symbol ${symbol} was not found.`);
  return document.positionAt(offset + 1);
};

const directProbe = async (
  document: vscode.TextDocument,
  symbol: string,
  renamedSymbol: string,
) => {
  const startedAt = Date.now();
  const deadline = startedAt + 120_000;
  let definitionLocations = 0;
  let referenceLocations = 0;
  let diagnosticCount = 0;
  let renamePrepared = false;
  let lastError: string | undefined;
  while (Date.now() < deadline) {
    try {
      const position = symbolPosition(document, symbol);
      const [definitions, references, rename] = await Promise.all([
        withTimeout(vscode.commands.executeCommand<readonly unknown[]>(
          'vscode.executeDefinitionProvider',
          document.uri,
          position,
        ), 10_000),
        withTimeout(vscode.commands.executeCommand<readonly unknown[]>(
          'vscode.executeReferenceProvider',
          document.uri,
          position,
        ), 10_000),
        withTimeout(vscode.commands.executeCommand<unknown>(
          'vscode.executeDocumentRenameProvider',
          document.uri,
          position,
          renamedSymbol,
        ), 10_000),
      ]);
      definitionLocations = Array.isArray(definitions) ? definitions.length : 0;
      referenceLocations = Array.isArray(references) ? references.length : 0;
      diagnosticCount = vscode.languages.getDiagnostics(document.uri).length;
      renamePrepared = rename instanceof vscode.WorkspaceEdit;
      if (
        definitionLocations >= 1 &&
        referenceLocations >= 2 &&
        diagnosticCount >= 1 &&
        renamePrepared
      ) {
        return {
          status: 'ready' as const,
          definitionLocations,
          referenceLocations,
          diagnosticCount,
          renamePrepared,
          elapsedMs: Date.now() - startedAt,
        };
      }
      lastError = undefined;
    } catch (error) {
      lastError = boundedError(error);
    }
    await sleep(500);
  }
  return {
    status: definitionLocations >= 1 && referenceLocations >= 2 && renamePrepared
      ? 'partial' as const
      : 'unavailable' as const,
    definitionLocations,
    referenceLocations,
    diagnosticCount,
    renamePrepared,
    elapsedMs: Date.now() - startedAt,
    ...(lastError === undefined ? {} : { lastError }),
  };
};

const fileExists = async (filePath: string): Promise<boolean> => readFile(filePath)
  .then(() => true, (error: unknown) => {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return false;
    throw error;
  });

const waitForStop = async (stopPath: string): Promise<void> => {
  const deadline = Date.now() + 180_000;
  while (Date.now() < deadline) {
    if (await fileExists(stopPath)) return;
    await sleep(100);
  }
  throw new Error('Stage F Extension Host did not receive its stop marker.');
};

export const run = async (): Promise<void> => {
  const fixtureName = requiredEnvironment('STAGE_F_FIXTURE_NAME');
  const readyPath = requiredEnvironment('STAGE_F_READY_PATH');
  const statePath = requiredEnvironment('STAGE_F_STATE_PATH');
  const stopPath = requiredEnvironment('STAGE_F_STOP_PATH');
  const cppCompilerPath = process.env.STAGE_F_CPP_COMPILER_PATH;
  const folder = vscode.workspace.workspaceFolders?.[0];
  assert.ok(folder, 'The Stage F fixture workspace was not opened.');
  const fixtureRoot = folder.uri.fsPath;
  assert.equal(path.basename(fixtureRoot), fixtureName);

  if (cppCompilerPath !== undefined && cppCompilerPath.length > 0) {
    await vscode.workspace.getConfiguration('C_Cpp').update(
      'default.compilerPath',
      cppCompilerPath,
      vscode.ConfigurationTarget.Workspace,
    );
    await vscode.workspace.getConfiguration('C_Cpp').update(
      'errorSquiggles',
      'enabled',
      vscode.ConfigurationTarget.Workspace,
    );
  }

  const cppPath = path.join(fixtureRoot, 'cpp', 'main.cpp');
  const csharpPath = path.join(fixtureRoot, 'csharp', 'Program.cs');
  const cppDocument = await vscode.workspace.openTextDocument(cppPath);
  const csharpDocument = await vscode.workspace.openTextDocument(csharpPath);
  const extensionIds = [
    'ms-vscode.cpptools',
    'llvm-vs-code-extensions.vscode-clangd',
    'ms-dotnettools.csharp',
    'ms-dotnettools.csdevkit',
  ];
  const extensions = await Promise.all(extensionIds.map(activateExtension));
  const [cppProbe, csharpProbe] = await Promise.all([
    directProbe(cppDocument, 'CppAddP6005', 'CppAddP6005Probe'),
    directProbe(csharpDocument, 'CsAddP6005', 'CsAddP6005Probe'),
  ]);

  const companion = vscode.extensions.getExtension('simplechat.vscode-lsp-mcp-companion');
  assert.ok(companion, 'The companion extension was not loaded in the Extension Development Host.');
  await companion.activate();
  assert.equal(companion.isActive, true);

  const ready = {
    schemaVersion: 1,
    fixtureName,
    vscodeVersion: vscode.version,
    cppCompilerPath: cppCompilerPath ?? null,
    extensions,
    directProviders: {
      cpp: cppProbe,
      csharp: csharpProbe,
    },
  };
  await writeFile(readyPath, `${JSON.stringify(ready, null, 2)}\n`, 'utf8');
  await waitForStop(stopPath);

  const documents = Object.fromEntries(await Promise.all([
    ['cpp', cppDocument, cppPath],
    ['csharp', csharpDocument, csharpPath],
  ].map(async ([name, document, filePath]) => [name, {
    dirty: (document as vscode.TextDocument).isDirty,
    memoryText: (document as vscode.TextDocument).getText(),
    diskText: await readFile(filePath as string, 'utf8'),
    visible: vscode.window.visibleTextEditors.some(
      (editor) => editor.document.uri.toString() === (document as vscode.TextDocument).uri.toString(),
    ),
  }])));
  await writeFile(statePath, `${JSON.stringify({ ...ready, documents }, null, 2)}\n`, 'utf8');
};
