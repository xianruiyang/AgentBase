import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import * as vscode from 'vscode';

interface ClientReport {
  readonly capabilityAvailable: number;
  readonly capabilityWindowReturned: number;
  readonly callHierarchyAvailable: number;
  readonly callHierarchyReturned: number;
  readonly diagnosticsReturned: number;
  readonly dirtyCallHierarchyReturned: number;
  readonly dirtyDefinitionFound: boolean;
  readonly dirtyReferenceFound: boolean;
  readonly dirtySymbolsReturned: number;
  readonly dirtyTypeHierarchyReturned: number;
  readonly hiddenSymbolsReturned: number;
  readonly knownPositionDefinition: boolean;
  readonly leakageChecksPassed: boolean;
  readonly referenceAvailable: number;
  readonly referenceResponseBytes: number;
  readonly referenceWindowReturned: number;
  readonly typeHierarchyAvailable: number;
  readonly typeHierarchyReturned: number;
  readonly unsupportedCallHierarchyReturned: number;
  readonly unsupportedCapabilityReason: string;
  readonly unsupportedCapabilityStatus: string;
  readonly unsupportedTypeHierarchyReturned: number;
  readonly workspaceSymbolAvailable: number;
  readonly workspaceSymbolResponseBytes: number;
  readonly workspaceSymbolWindowReturned: number;
}

const requiredEnvironment = (name: string): string => {
  const value = process.env[name];
  if (value === undefined || value.length === 0) {
    throw new Error(`Missing Stage B environment variable: ${name}.`);
  }
  return value;
};

const waitForDirtyDiagnostic = async (uri: vscode.Uri): Promise<void> => {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    const diagnostics = vscode.languages.getDiagnostics(uri);
    if (diagnostics.some((diagnostic) => diagnostic.severity === vscode.DiagnosticSeverity.Error)) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error('The TypeScript provider did not publish the dirty-document diagnostic.');
};

const registerStageBTypeHierarchy = (fixtureRoot: string): vscode.Disposable => {
  const typeItem = (uri: vscode.Uri, name: string, line: number): vscode.TypeHierarchyItem => {
    const nameStart = 13;
    const selection = new vscode.Range(line, nameStart, line, nameStart + name.length);
    return new vscode.TypeHierarchyItem(
      vscode.SymbolKind.Class,
      name,
      'stage-b-type-hierarchy',
      uri,
      selection,
      selection,
    );
  };
  const hierarchyUri = vscode.Uri.file(path.join(fixtureRoot, 'src', 'hierarchy.ts'));
  const dirtyUri = vscode.Uri.file(path.join(fixtureRoot, 'src', 'dirty.ts'));
  const baseType = typeItem(hierarchyUri, 'BaseType', 9);
  const middleType = typeItem(hierarchyUri, 'MiddleType', 10);
  const leafType = typeItem(hierarchyUri, 'LeafType', 11);
  const dirtyBase = typeItem(dirtyUri, 'DirtyBase', 5);
  const dirtyMiddle = typeItem(dirtyUri, 'DirtyMiddle', 6);
  const dirtyLeaf = typeItem(dirtyUri, 'DirtyLeaf', 7);
  return vscode.languages.registerTypeHierarchyProvider(
    [
      { language: 'typescript', scheme: 'file', pattern: '**/hierarchy.ts' },
      { language: 'typescript', scheme: 'file', pattern: '**/dirty.ts' },
    ],
    {
      prepareTypeHierarchy: (document, position) => {
        if (document.uri.toString() === hierarchyUri.toString() && position.line === 10 &&
            position.character >= 13 && position.character <= 23) {
          return [middleType];
        }
        return document.uri.toString() === dirtyUri.toString() && position.line === 6 &&
          position.character >= 13 && position.character <= 24
          ? [dirtyMiddle]
          : [];
      },
      provideTypeHierarchySupertypes: (item) => item.name === 'MiddleType'
        ? [baseType]
        : item.name === 'LeafType'
          ? [middleType]
          : item.name === 'DirtyMiddle'
            ? [dirtyBase]
            : item.name === 'DirtyLeaf' ? [dirtyMiddle] : [],
      provideTypeHierarchySubtypes: (item) => item.name === 'MiddleType'
        ? [leafType]
        : item.name === 'BaseType'
          ? [middleType]
          : item.name === 'DirtyMiddle'
            ? [dirtyLeaf]
            : item.name === 'DirtyBase' ? [dirtyMiddle] : [],
    },
  );
};

const runClient = async (
  nodePath: string,
  clientPath: string,
  fixtureName: string,
  fixtureRoot: string,
): Promise<ClientReport> => new Promise((resolve, reject) => {
  const child = spawn(nodePath, [clientPath], {
    env: {
      ...process.env,
      STAGE_B_EXPECTED_ROOT: fixtureRoot,
      STAGE_B_FIXTURE_NAME: fixtureName,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
  let stdout = '';
  let stderr = '';
  child.stdout.setEncoding('utf8');
  child.stderr.setEncoding('utf8');
  child.stdout.on('data', (chunk: string) => {
    stdout += chunk;
    if (stdout.length > 100_000) child.kill();
  });
  child.stderr.on('data', (chunk: string) => {
    stderr += chunk;
    if (stderr.length > 100_000) child.kill();
  });
  child.once('error', reject);
  child.once('exit', (code, signal) => {
    if (code !== 0) {
      reject(new Error(`Stage B MCP client failed (${code ?? signal ?? 'unknown'}): ${stderr}`));
      return;
    }
    try {
      const parsed = JSON.parse(stdout) as ClientReport;
      resolve(parsed);
    } catch (error) {
      reject(new Error(`Stage B MCP client returned invalid JSON: ${stdout}`, { cause: error }));
    }
  });
});

export const run = async (): Promise<void> => {
  const clientPath = requiredEnvironment('STAGE_B_CLIENT_PATH');
  const fixtureName = requiredEnvironment('STAGE_B_FIXTURE_NAME');
  const nodePath = requiredEnvironment('STAGE_B_NODE_PATH');
  const reportPath = requiredEnvironment('STAGE_B_REPORT_PATH');
  const folder = vscode.workspace.workspaceFolders?.[0];
  assert.ok(folder, 'The Stage B fixture workspace was not opened.');
  const fixtureRoot = folder.uri.fsPath;
  assert.equal(path.basename(fixtureRoot), fixtureName);

  const companion = vscode.extensions.getExtension('simplechat.vscode-lsp-mcp-companion');
  assert.ok(companion, 'The companion extension was not loaded in the Extension Development Host.');
  const companionActiveBeforeExplicitActivation = companion.isActive;
  await companion.activate();
  const companionActiveAfterExplicitActivation = companion.isActive;
  assert.equal(companionActiveAfterExplicitActivation, true);
  const typescript = vscode.extensions.getExtension('vscode.typescript-language-features');
  assert.ok(typescript, 'The built-in TypeScript language features extension is unavailable.');
  await typescript.activate();

  const closedSemanticUris = ['consumer.ts', 'widget.ts', 'hidden.ts', 'hierarchy.ts', 'unsupported.txt']
    .map((file) => vscode.Uri.file(path.join(fixtureRoot, 'src', file)));
  const dirtyUri = vscode.Uri.file(path.join(fixtureRoot, 'src', 'dirty.ts'));
  const semanticUris = [...closedSemanticUris, dirtyUri];
  const semanticDocumentsInitiallyClosed = semanticUris.every((uri) =>
    !vscode.workspace.textDocuments.some((document) => document.uri.toString() === uri.toString()));
  assert.equal(semanticDocumentsInitiallyClosed, true);

  const dirtyDocument = await vscode.workspace.openTextDocument(dirtyUri);
  const diskBefore = await readFile(dirtyUri.fsPath, 'utf8');
  const dirtyValueOffset = dirtyDocument.getText().indexOf('= 1;') + 2;
  assert.ok(dirtyValueOffset >= 2, 'Dirty fixture marker was not found.');
  const edit = new vscode.WorkspaceEdit();
  edit.replace(
    dirtyUri,
    new vscode.Range(
      dirtyDocument.positionAt(dirtyValueOffset),
      dirtyDocument.positionAt(dirtyValueOffset + 1),
    ),
    '"broken"',
  );
  assert.equal(await vscode.workspace.applyEdit(edit), true);
  assert.equal(dirtyDocument.isDirty, true);
  assert.equal(await readFile(dirtyUri.fsPath, 'utf8'), diskBefore);
  await waitForDirtyDiagnostic(dirtyUri);

  const typeHierarchyProvider = registerStageBTypeHierarchy(fixtureRoot);
  let clientReport: ClientReport;
  try {
    clientReport = await runClient(nodePath, clientPath, fixtureName, fixtureRoot);
  } finally {
    typeHierarchyProvider.dispose();
  }
  const semanticDocumentsActivated = semanticUris.filter((uri) =>
    vscode.workspace.textDocuments.some((document) => document.uri.toString() === uri.toString()));
  const closedSemanticDocumentsVisible = closedSemanticUris.filter((uri) =>
    vscode.window.visibleTextEditors.some((editor) => editor.document.uri.toString() === uri.toString()));
  assert.equal(semanticDocumentsActivated.length, semanticUris.length);
  assert.equal(closedSemanticDocumentsVisible.length, 0);
  assert.equal(dirtyDocument.isDirty, true);
  assert.equal(await readFile(dirtyUri.fsPath, 'utf8'), diskBefore);

  await writeFile(reportPath, `${JSON.stringify({
    schemaVersion: 1,
    fixtureName,
    vscodeVersion: vscode.version,
    companionActiveBeforeExplicitActivation,
    companionActiveAfterExplicitActivation,
    semanticDocumentsInitiallyClosed,
    closedDocumentsActivatedWithoutEditor: closedSemanticUris.length,
    dirtyDocumentRemainedUnsaved: dirtyDocument.isDirty,
    dirtyDocumentVisible: vscode.window.visibleTextEditors.some(
      (editor) => editor.document.uri.toString() === dirtyUri.toString()),
    diskRemainedOriginal: (await readFile(dirtyUri.fsPath, 'utf8')) === diskBefore,
    ...clientReport,
  }, null, 2)}\n`, 'utf8');
};
