import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import * as vscode from 'vscode';

const requiredEnvironment = (name: string): string => {
  const value = process.env[name];
  if (value === undefined || value.length === 0) {
    throw new Error(`Missing Stage E environment variable: ${name}.`);
  }
  return value;
};

const fileExists = async (filePath: string): Promise<boolean> => readFile(filePath)
  .then(() => true, (error: unknown) => {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return false;
    throw error;
  });

const waitForStop = async (stopPath: string): Promise<void> => {
  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    if (await fileExists(stopPath)) return;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error('Stage E Extension Host did not receive its stop marker.');
};

const entireDocumentRange = (document: vscode.TextDocument): vscode.Range =>
  new vscode.Range(document.positionAt(0), document.positionAt(document.getText().length));

const occurrences = (document: vscode.TextDocument, text: string): readonly vscode.Range[] => {
  const ranges: vscode.Range[] = [];
  let offset = 0;
  while (offset <= document.getText().length) {
    const index = document.getText().indexOf(text, offset);
    if (index < 0) break;
    ranges.push(new vscode.Range(document.positionAt(index), document.positionAt(index + text.length)));
    offset = index + text.length;
  }
  return ranges;
};

export const run = async (): Promise<void> => {
  const fixtureName = requiredEnvironment('STAGE_E_FIXTURE_NAME');
  const hostLabel = requiredEnvironment('STAGE_E_HOST_LABEL');
  const readyPath = requiredEnvironment('STAGE_E_READY_PATH');
  const statePath = requiredEnvironment('STAGE_E_STATE_PATH');
  const stopPath = requiredEnvironment('STAGE_E_STOP_PATH');
  const folder = vscode.workspace.workspaceFolders?.[0];
  assert.ok(folder, 'The Stage E fixture workspace was not opened.');
  const fixtureRoot = folder.uri.fsPath;
  assert.equal(path.basename(fixtureRoot), fixtureName);

  const companion = vscode.extensions.getExtension('simplechat.vscode-lsp-mcp-companion');
  assert.ok(companion, 'The companion extension was not loaded in the Extension Development Host.');
  assert.equal(companion.isActive, false, 'Command policy must be installed before activation.');
  await vscode.workspace.getConfiguration('vscodeLspMcp').update(
    'commandPolicy',
    {
      commands: [{
        commandId: 'p6.alltools.identity',
        nonInteractive: true,
        completion: 'promise',
        maxTimeoutMs: 5_000,
      }],
      tasks: [],
    },
    vscode.ConfigurationTarget.Workspace,
  );

  const semanticUri = vscode.Uri.file(path.join(fixtureRoot, 'src', 'semantic.p64'));
  const referencesUri = vscode.Uri.file(path.join(fixtureRoot, 'src', 'references.p64'));
  const renameUri = vscode.Uri.file(path.join(fixtureRoot, 'src', 'rename.p64'));
  const actionUri = vscode.Uri.file(path.join(fixtureRoot, 'src', 'action.p64'));
  const formatUri = vscode.Uri.file(path.join(fixtureRoot, 'src', 'format.p64'));
  const selector: vscode.DocumentSelector = { scheme: 'file', pattern: '**/*.p64' };
  const symbolRange = new vscode.Range(0, 0, 0, 8);
  const counters = {
    callHierarchy: 0,
    codeActions: 0,
    commands: 0,
    declarations: 0,
    definitions: 0,
    diagnostics: 0,
    documentSymbols: 0,
    formatting: 0,
    hovers: 0,
    implementations: 0,
    references: 0,
    renames: 0,
    signatures: 0,
    typeDefinitions: 0,
    typeHierarchy: 0,
    workspaceSymbols: 0,
  };
  let stateWrite = Promise.resolve();
  const state = (memory?: Record<string, unknown>) => ({
    schemaVersion: 1,
    fixtureName,
    hostLabel,
    counters,
    ...(memory === undefined ? {} : { memory }),
  });
  const persistState = (memory?: Record<string, unknown>): void => {
    const snapshot = JSON.stringify(state(memory), null, 2);
    stateWrite = stateWrite.then(() => writeFile(statePath, `${snapshot}\n`, 'utf8'));
  };
  const count = (name: keyof typeof counters): void => {
    counters[name] += 1;
    persistState();
  };

  const callMiddle = new vscode.CallHierarchyItem(
    vscode.SymbolKind.Function,
    `${hostLabel}MiddleCall`,
    hostLabel,
    semanticUri,
    symbolRange,
    symbolRange,
  );
  const callRoot = new vscode.CallHierarchyItem(
    vscode.SymbolKind.Function,
    `${hostLabel}RootCall`,
    hostLabel,
    semanticUri,
    symbolRange,
    symbolRange,
  );
  const callLeaf = new vscode.CallHierarchyItem(
    vscode.SymbolKind.Function,
    `${hostLabel}LeafCall`,
    hostLabel,
    semanticUri,
    symbolRange,
    symbolRange,
  );
  const typeMiddle = new vscode.TypeHierarchyItem(
    vscode.SymbolKind.Class,
    `${hostLabel}MiddleType`,
    hostLabel,
    semanticUri,
    symbolRange,
    symbolRange,
  );
  const typeBase = new vscode.TypeHierarchyItem(
    vscode.SymbolKind.Class,
    `${hostLabel}BaseType`,
    hostLabel,
    semanticUri,
    symbolRange,
    symbolRange,
  );
  const typeLeaf = new vscode.TypeHierarchyItem(
    vscode.SymbolKind.Class,
    `${hostLabel}LeafType`,
    hostLabel,
    semanticUri,
    symbolRange,
    symbolRange,
  );

  const diagnostics = vscode.languages.createDiagnosticCollection(`p6-004-${hostLabel}`);
  const diagnostic = new vscode.Diagnostic(
    new vscode.Range(0, 0, 0, 1),
    `${hostLabel} diagnostic`,
    vscode.DiagnosticSeverity.Warning,
  );
  diagnostic.source = 'p6-004';
  diagnostics.set(semanticUri, [diagnostic]);

  const disposables: vscode.Disposable[] = [
    diagnostics,
    vscode.commands.registerCommand('p6.alltools.identity', () => {
      count('commands');
      return { fixtureName, hostLabel };
    }),
    vscode.languages.registerWorkspaceSymbolProvider({
      provideWorkspaceSymbols: () => {
        count('workspaceSymbols');
        return [new vscode.SymbolInformation(
          `${hostLabel}WorkspaceSymbol`,
          vscode.SymbolKind.Function,
          hostLabel,
          new vscode.Location(semanticUri, symbolRange),
        )];
      },
    }),
    vscode.languages.registerDocumentSymbolProvider(selector, {
      provideDocumentSymbols: () => {
        count('documentSymbols');
        return [new vscode.DocumentSymbol(
          `${hostLabel}DocumentSymbol`,
          hostLabel,
          vscode.SymbolKind.Function,
          symbolRange,
          symbolRange,
        )];
      },
    }),
    vscode.languages.registerHoverProvider(selector, {
      provideHover: () => {
        count('hovers');
        return new vscode.Hover(`${hostLabel} hover`);
      },
    }),
    vscode.languages.registerDeclarationProvider(selector, {
      provideDeclaration: () => {
        count('declarations');
        return new vscode.Location(semanticUri, symbolRange);
      },
    }),
    vscode.languages.registerDefinitionProvider(selector, {
      provideDefinition: () => {
        count('definitions');
        return new vscode.Location(semanticUri, symbolRange);
      },
    }),
    vscode.languages.registerTypeDefinitionProvider(selector, {
      provideTypeDefinition: () => {
        count('typeDefinitions');
        return new vscode.Location(semanticUri, symbolRange);
      },
    }),
    vscode.languages.registerImplementationProvider(selector, {
      provideImplementation: () => {
        count('implementations');
        return new vscode.Location(semanticUri, symbolRange);
      },
    }),
    vscode.languages.registerSignatureHelpProvider(selector, {
      provideSignatureHelp: () => {
        count('signatures');
        const signature = new vscode.SignatureInformation(`${hostLabel}(value: string)`);
        signature.parameters = [new vscode.ParameterInformation('value')];
        const help = new vscode.SignatureHelp();
        help.signatures = [signature];
        help.activeSignature = 0;
        help.activeParameter = 0;
        return help;
      },
    }, '('),
    vscode.languages.registerReferenceProvider(selector, {
      provideReferences: () => {
        count('references');
        return Array.from(
          { length: 140 },
          (_, index) => new vscode.Location(referencesUri, new vscode.Position(index, 0)),
        );
      },
    }),
    vscode.languages.registerCallHierarchyProvider(selector, {
      prepareCallHierarchy: () => {
        count('callHierarchy');
        return [callMiddle];
      },
      provideCallHierarchyIncomingCalls: (item) => item.name === callMiddle.name
        ? [new vscode.CallHierarchyIncomingCall(callRoot, [symbolRange])]
        : [],
      provideCallHierarchyOutgoingCalls: (item) => item.name === callMiddle.name
        ? [new vscode.CallHierarchyOutgoingCall(callLeaf, [symbolRange])]
        : [],
    }),
    vscode.languages.registerTypeHierarchyProvider(selector, {
      prepareTypeHierarchy: () => {
        count('typeHierarchy');
        return [typeMiddle];
      },
      provideTypeHierarchySupertypes: (item) => item.name === typeMiddle.name ? [typeBase] : [],
      provideTypeHierarchySubtypes: (item) => item.name === typeMiddle.name ? [typeLeaf] : [],
    }),
    vscode.languages.registerRenameProvider(selector, {
      prepareRename: async () => {
        const document = await vscode.workspace.openTextDocument(renameUri);
        const range = occurrences(document, 'oldName')[0];
        assert.ok(range, 'The Stage E rename marker is missing.');
        return { range, placeholder: 'oldName' };
      },
      provideRenameEdits: async (_document, _position, newName) => {
        count('renames');
        const document = await vscode.workspace.openTextDocument(renameUri);
        const edit = new vscode.WorkspaceEdit();
        for (const range of occurrences(document, 'oldName')) edit.replace(renameUri, range, newName);
        return edit;
      },
    }),
    vscode.languages.registerCodeActionsProvider(selector, {
      provideCodeActions: async (document) => {
        if (document.uri.toString() !== actionUri.toString()) return [];
        count('codeActions');
        const edit = new vscode.WorkspaceEdit();
        edit.replace(actionUri, entireDocumentRange(document), `${hostLabel}_ACTION_NEW\n`);
        const action = new vscode.CodeAction(`${hostLabel} quick fix`, vscode.CodeActionKind.QuickFix);
        action.edit = edit;
        action.isPreferred = true;
        return [action];
      },
    }, { providedCodeActionKinds: [vscode.CodeActionKind.QuickFix] }),
    vscode.languages.registerDocumentFormattingEditProvider(selector, {
      provideDocumentFormattingEdits: (document) => {
        if (document.uri.toString() !== formatUri.toString()) return [];
        count('formatting');
        return [vscode.TextEdit.replace(entireDocumentRange(document), `${hostLabel}_FORMATTED\n`)];
      },
    }),
  ];

  try {
    await companion.activate();
    assert.equal(companion.isActive, true);
    count('diagnostics');
    await stateWrite;
    await writeFile(readyPath, `${JSON.stringify({
      schemaVersion: 1,
      fixtureName,
      hostLabel,
      vscodeVersion: vscode.version,
    }, null, 2)}\n`, 'utf8');
    await waitForStop(stopPath);
    const memory: Record<string, unknown> = {};
    for (const [name, uri] of [
      ['rename', renameUri],
      ['action', actionUri],
      ['format', formatUri],
    ] as const) {
      const document = vscode.workspace.textDocuments.find(
        (candidate) => candidate.uri.toString() === uri.toString(),
      );
      memory[name] = document === undefined
        ? { open: false }
        : { open: true, dirty: document.isDirty, text: document.getText() };
    }
    persistState(memory);
    await stateWrite;
  } finally {
    for (const disposable of disposables.reverse()) disposable.dispose();
  }
};
