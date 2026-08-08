import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import * as vscode from 'vscode';

interface StageCState {
  readonly schemaVersion: 1;
  readonly hostLabel: string;
  readonly hierarchyPrepares: number;
  readonly emptyPrepares: number;
  readonly timeoutPrepares: number;
  readonly cancelPrepares: number;
}

const requiredEnvironment = (name: string): string => {
  const value = process.env[name];
  if (value === undefined || value.length === 0) {
    throw new Error(`Missing Stage C environment variable: ${name}.`);
  }
  return value;
};

const fileExists = async (filePath: string): Promise<boolean> => readFile(filePath)
  .then(() => true, (error: unknown) => {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return false;
    throw error;
  });

const waitForStop = async (stopPath: string): Promise<void> => {
  const deadline = Date.now() + 45_000;
  while (Date.now() < deadline) {
    if (await fileExists(stopPath)) return;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error('Stage C Extension Host did not receive its stop marker.');
};

export const run = async (): Promise<void> => {
  const fixtureName = requiredEnvironment('STAGE_C_FIXTURE_NAME');
  const hostLabel = requiredEnvironment('STAGE_C_HOST_LABEL');
  const readyPath = requiredEnvironment('STAGE_C_READY_PATH');
  const statePath = requiredEnvironment('STAGE_C_STATE_PATH');
  const stopPath = requiredEnvironment('STAGE_C_STOP_PATH');
  const folder = vscode.workspace.workspaceFolders?.[0];
  assert.ok(folder, 'The Stage C fixture workspace was not opened.');
  const fixtureRoot = folder.uri.fsPath;
  assert.equal(path.basename(fixtureRoot), fixtureName);

  const companion = vscode.extensions.getExtension('simplechat.vscode-lsp-mcp-companion');
  assert.ok(companion, 'The companion extension was not loaded in the Extension Development Host.');
  await companion.activate();
  const typescript = vscode.extensions.getExtension('vscode.typescript-language-features');
  assert.ok(typescript, 'The built-in TypeScript language features extension is unavailable.');
  await typescript.activate();

  const hierarchyUri = vscode.Uri.file(path.join(fixtureRoot, 'src', 'hierarchy.ts'));
  const typeItem = (name: string, line: number): vscode.TypeHierarchyItem => {
    const nameStart = 13;
    const selection = new vscode.Range(line, nameStart, line, nameStart + name.length);
    return new vscode.TypeHierarchyItem(
      vscode.SymbolKind.Class,
      name,
      'stage-c-type-hierarchy',
      hierarchyUri,
      selection,
      selection,
    );
  };
  const baseType = typeItem('BaseType', 0);
  const middleType = typeItem('MiddleType', 1);
  const leafType = typeItem('LeafType', 2);
  const counters = {
    hierarchyPrepares: 0,
    emptyPrepares: 0,
    timeoutPrepares: 0,
    cancelPrepares: 0,
  };
  const state = (): StageCState => ({
    schemaVersion: 1,
    hostLabel,
    ...counters,
  });
  let stateWrite = Promise.resolve();
  const persistState = (): void => {
    stateWrite = stateWrite.then(() => writeFile(statePath, `${JSON.stringify(state(), null, 2)}\n`, 'utf8'));
  };
  const provider = vscode.languages.registerTypeHierarchyProvider(
    [
      { language: 'typescript', scheme: 'file', pattern: '**/hierarchy.ts' },
      { language: 'typescript', scheme: 'file', pattern: '**/empty.ts' },
      { language: 'typescript', scheme: 'file', pattern: '**/timeout.ts' },
      { language: 'typescript', scheme: 'file', pattern: '**/cancel.ts' },
    ],
    {
      prepareTypeHierarchy: (document, position) => {
        const basename = path.basename(document.uri.fsPath).toLowerCase();
        if (basename === 'hierarchy.ts') {
          counters.hierarchyPrepares += 1;
          persistState();
          return position.line === 1 && position.character >= 13 && position.character <= 23
            ? [middleType]
            : [];
        }
        if (basename === 'empty.ts') {
          counters.emptyPrepares += 1;
          persistState();
          return [];
        }
        if (basename === 'timeout.ts') {
          counters.timeoutPrepares += 1;
          persistState();
          return new Promise<vscode.TypeHierarchyItem[]>(() => undefined);
        }
        if (basename === 'cancel.ts') {
          counters.cancelPrepares += 1;
          persistState();
          return new Promise<vscode.TypeHierarchyItem[]>(() => undefined);
        }
        return [];
      },
      provideTypeHierarchySupertypes: (item) => item.name === 'MiddleType'
        ? [baseType]
        : item.name === 'LeafType' ? [middleType] : [],
      provideTypeHierarchySubtypes: (item) => item.name === 'MiddleType'
        ? [leafType]
        : item.name === 'BaseType' ? [middleType] : [],
    },
  );

  try {
    persistState();
    await stateWrite;
    await writeFile(readyPath, `${JSON.stringify({
      schemaVersion: 1,
      fixtureName,
      hostLabel,
      vscodeVersion: vscode.version,
    }, null, 2)}\n`, 'utf8');
    await waitForStop(stopPath);
  } finally {
    provider.dispose();
    persistState();
    await stateWrite;
  }
};
