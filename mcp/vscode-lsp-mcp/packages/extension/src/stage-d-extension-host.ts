import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import * as vscode from 'vscode';

interface ClientReport {
  readonly codeActionChangedFiles: number;
  readonly formatChangedFiles: number;
  readonly interactiveCommandReason: string;
  readonly interactiveInputReason: string;
  readonly interactiveProbeCalls: number;
  readonly interactiveTaskStarts: number;
  readonly leakageChecksPassed: boolean;
  readonly nonZeroExitCode: number;
  readonly outputCodePoints: number;
  readonly outputTruncated: boolean;
  readonly rangeFormatChangedFiles: number;
  readonly renameChangedFiles: number;
  readonly repeatedPreviewRejected: boolean;
  readonly riskyCommandReason: string;
  readonly saveModes: readonly string[];
  readonly staleApplyErrorCode: string;
  readonly successfulTasks: readonly string[];
  readonly taskOutputAbsent: boolean;
  readonly timeoutElapsedMs: number;
  readonly timeoutErrorCode: string;
  readonly timeoutOutcome: string;
  readonly uiApiCalls: number;
}

const requiredEnvironment = (name: string): string => {
  const value = process.env[name];
  if (value === undefined || value.length === 0) {
    throw new Error(`Missing Stage D environment variable: ${name}.`);
  }
  return value;
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
      STAGE_D_EXPECTED_ROOT: fixtureRoot,
      STAGE_D_FIXTURE_NAME: fixtureName,
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
    if (stdout.length > 200_000) child.kill();
  });
  child.stderr.on('data', (chunk: string) => {
    stderr += chunk;
    if (stderr.length > 200_000) child.kill();
  });
  child.once('error', reject);
  child.once('exit', (code, signal) => {
    if (code !== 0) {
      reject(new Error(`Stage D MCP client failed (${code ?? signal ?? 'unknown'}): ${stderr}`));
      return;
    }
    try {
      resolve(JSON.parse(stdout) as ClientReport);
    } catch (error) {
      reject(new Error(`Stage D MCP client returned invalid JSON: ${stdout}`, { cause: error }));
    }
  });
});

const documentFor = async (fixtureRoot: string, relativePath: string): Promise<vscode.TextDocument> =>
  vscode.workspace.openTextDocument(vscode.Uri.file(path.join(fixtureRoot, relativePath)));

const entireDocumentRange = (document: vscode.TextDocument): vscode.Range =>
  new vscode.Range(document.positionAt(0), document.positionAt(document.getText().length));

const textRanges = (document: vscode.TextDocument, text: string): readonly vscode.Range[] => {
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

const replaceText = async (
  document: vscode.TextDocument,
  search: string,
  replacement: string,
): Promise<boolean> => {
  const range = textRanges(document, search)[0];
  if (range === undefined) return false;
  const edit = new vscode.WorkspaceEdit();
  edit.replace(document.uri, range, replacement);
  return vscode.workspace.applyEdit(edit);
};

const configurePolicy = async (): Promise<void> => {
  const commands = [
    'p6.test.documentState',
    'p6.test.longOutput',
    'p6.test.editAfterPreview',
    'p6.test.snapshot',
    'workbench.action.quickOpen',
  ].map((commandId) => ({
    commandId,
    nonInteractive: true as const,
    completion: 'promise' as const,
    maxTimeoutMs: 5_000,
  }));
  await vscode.workspace.getConfiguration('vscodeLspMcp').update(
    'commandPolicy',
    {
      allowStandardCommands: true,
      allowWorkspaceTasks: true,
      commands,
      tasks: [],
    },
    vscode.ConfigurationTarget.Workspace,
  );
  await vscode.workspace.getConfiguration('editor').update(
    'tabSize',
    3,
    vscode.ConfigurationTarget.Workspace,
  );
  await vscode.workspace.getConfiguration('editor').update(
    'insertSpaces',
    false,
    vscode.ConfigurationTarget.Workspace,
  );
};

export const run = async (): Promise<void> => {
  const clientPath = requiredEnvironment('STAGE_D_CLIENT_PATH');
  const fixtureName = requiredEnvironment('STAGE_D_FIXTURE_NAME');
  const nodePath = requiredEnvironment('STAGE_D_NODE_PATH');
  const reportPath = requiredEnvironment('STAGE_D_REPORT_PATH');
  const taskMarkerPath = requiredEnvironment('STAGE_D_TASK_MARKER_PATH');
  const folder = vscode.workspace.workspaceFolders?.[0];
  assert.ok(folder, 'The Stage D fixture workspace was not opened.');
  const fixtureRoot = folder.uri.fsPath;
  assert.equal(path.basename(fixtureRoot), fixtureName);
  const companion = vscode.extensions.getExtension('simplechat.vscode-lsp-mcp-companion');
  assert.ok(companion, 'The companion extension was not loaded in the Extension Development Host.');
  assert.equal(companion.isActive, false, 'Policy must be installed before companion activation.');
  await configurePolicy();

  const uiApiCalls: string[] = [];
  const windowRecord = vscode.window as unknown as Record<string, unknown>;
  const inputDescriptor = Object.getOwnPropertyDescriptor(windowRecord, 'showInputBox');
  assert.ok(inputDescriptor, 'VS Code showInputBox descriptor is unavailable.');
  Object.defineProperty(windowRecord, 'showInputBox', {
    ...inputDescriptor,
    value: (): Promise<undefined> => {
      uiApiCalls.push('showInputBox');
      return Promise.resolve(undefined);
    },
  });

  const taskStarts: string[] = [];
  let interactiveProbeCalls = 0;
  const providerState = {
    codeActionCalls: 0,
    documentFormatCalls: 0,
    documentFormatOptions: undefined as { tabSize: number; insertSpaces: boolean } | undefined,
    rangeFormatCalls: 0,
    rangeFormatOptions: undefined as { tabSize: number; insertSpaces: boolean } | undefined,
    rangeFormatSelection: undefined as { start: number; end: number; text: string } | undefined,
    renameCalls: 0,
  };
  const disposables: vscode.Disposable[] = [
    vscode.tasks.onDidStartTask((event) => taskStarts.push(event.execution.task.name)),
    vscode.commands.registerCommand('p6.test.interactiveProbe', () => {
      interactiveProbeCalls += 1;
      return vscode.window.showInputBox({ prompt: 'P6-003 must never show this input.' });
    }),
  ];

  const saveActive = await documentFor(fixtureRoot, 'src/save-active.txt');
  const saveAll = await documentFor(fixtureRoot, 'src/save-all.txt');
  assert.equal(await replaceText(saveActive, 'active disk', 'active memory'), true);
  assert.equal(await replaceText(saveAll, 'all disk', 'all memory'), true);
  await vscode.window.showTextDocument(saveActive, { preview: false, preserveFocus: false });
  assert.equal(vscode.window.activeTextEditor?.document.uri.toString(), saveActive.uri.toString());

  const mutationFiles = [
    'src/rename-a.p6',
    'src/rename-b.p6',
    'src/stale.p6',
    'src/action-a.p6',
    'src/action-b.p6',
    'src/format.p6',
    'src/range.p6',
  ];
  const diskBefore = new Map<string, string>();
  for (const file of mutationFiles) {
    diskBefore.set(file, await readFile(path.join(fixtureRoot, file), 'utf8'));
  }

  disposables.push(
    vscode.commands.registerCommand('p6.test.documentState', () => ({
      activeDirty: saveActive.isDirty,
      allDirty: saveAll.isDirty,
    })),
    vscode.commands.registerCommand('p6.test.longOutput', () => '😀'.repeat(1_200)),
    vscode.commands.registerCommand('p6.test.editAfterPreview', async () => {
      const document = await documentFor(fixtureRoot, 'src/stale.p6');
      const edit = new vscode.WorkspaceEdit();
      edit.insert(document.uri, document.positionAt(document.getText().length), '// user edit\n');
      assert.equal(await vscode.workspace.applyEdit(edit), true);
      return 'edited';
    }),
    vscode.commands.registerCommand('p6.test.snapshot', () => ({
      uiApiCalls: uiApiCalls.length,
      interactiveProbeCalls,
      interactiveTaskStarts: taskStarts.filter((name) => name.startsWith('p6-interactive-')).length,
    })),
    vscode.languages.registerDefinitionProvider(
      [
        { scheme: 'file', pattern: '**/rename-*.p6' },
        { scheme: 'file', pattern: '**/stale.p6' },
      ],
      {
        provideDefinition: async (document, position) => {
          const stale = path.basename(document.uri.fsPath) === 'stale.p6';
          const symbol = stale ? 'staleName' : 'oldName';
          if (!textRanges(document, symbol).some((range) => range.contains(position))) {
            return undefined;
          }
          const definition = stale
            ? document
            : await documentFor(fixtureRoot, 'src/rename-a.p6');
          const range = textRanges(definition, symbol)[0];
          return range === undefined ? undefined : new vscode.Location(definition.uri, range);
        },
      },
    ),
    vscode.languages.registerRenameProvider(
      [
        { scheme: 'file', pattern: '**/rename-*.p6' },
        { scheme: 'file', pattern: '**/stale.p6' },
      ],
      {
        prepareRename: (document, position) => {
          const sourceName = path.basename(document.uri.fsPath) === 'stale.p6'
            ? 'staleName'
            : 'oldName';
          const range = textRanges(document, sourceName).find((candidate) => candidate.contains(position));
          return range === undefined ? undefined : { range, placeholder: sourceName };
        },
        provideRenameEdits: async (document, _position, newName) => {
          providerState.renameCalls += 1;
          const edit = new vscode.WorkspaceEdit();
          const basename = path.basename(document.uri.fsPath);
          const targets = basename === 'stale.p6'
            ? [document]
            : [
                await documentFor(fixtureRoot, 'src/rename-a.p6'),
                await documentFor(fixtureRoot, 'src/rename-b.p6'),
              ];
          const sourceName = basename === 'stale.p6' ? 'staleName' : 'oldName';
          for (const target of targets) {
            for (const range of textRanges(target, sourceName)) edit.replace(target.uri, range, newName);
          }
          return edit;
        },
      },
    ),
    vscode.languages.registerCodeActionsProvider(
      { scheme: 'file', pattern: '**/action-a.p6' },
      {
        provideCodeActions: async () => {
          providerState.codeActionCalls += 1;
          const actionA = await documentFor(fixtureRoot, 'src/action-a.p6');
          const actionB = await documentFor(fixtureRoot, 'src/action-b.p6');
          const edit = new vscode.WorkspaceEdit();
          edit.replace(actionA.uri, entireDocumentRange(actionA), 'ACTION_A_NEW\n');
          edit.replace(actionB.uri, entireDocumentRange(actionB), 'ACTION_B_NEW\n');
          const action = new vscode.CodeAction('P6 multi-file quick fix', vscode.CodeActionKind.QuickFix);
          action.edit = edit;
          action.isPreferred = true;
          return [action];
        },
      },
      { providedCodeActionKinds: [vscode.CodeActionKind.QuickFix] },
    ),
    vscode.languages.registerDocumentFormattingEditProvider(
      { scheme: 'file', pattern: '**/format.p6' },
      {
        provideDocumentFormattingEdits: (document, options) => {
          providerState.documentFormatCalls += 1;
          providerState.documentFormatOptions = {
            tabSize: options.tabSize,
            insertSpaces: options.insertSpaces,
          };
          return [vscode.TextEdit.replace(entireDocumentRange(document), 'FORMATTED\n')];
        },
      },
    ),
    vscode.languages.registerDocumentRangeFormattingEditProvider(
      { scheme: 'file', pattern: '**/range.p6' },
      {
        provideDocumentRangeFormattingEdits: (document, range, options) => {
          providerState.rangeFormatCalls += 1;
          providerState.rangeFormatOptions = {
            tabSize: options.tabSize,
            insertSpaces: options.insertSpaces,
          };
          providerState.rangeFormatSelection = {
            start: range.start.character,
            end: range.end.character,
            text: document.getText(range),
          };
          return [vscode.TextEdit.replace(range, 'R')];
        },
      },
    ),
  );

  await companion.activate();
  assert.equal(companion.isActive, true);

  let clientReport: ClientReport;
  try {
    clientReport = await runClient(nodePath, clientPath, fixtureName, fixtureRoot);

    assert.equal(saveActive.isDirty, false);
    assert.equal(saveAll.isDirty, false);
    assert.equal(await readFile(saveActive.uri.fsPath, 'utf8'), 'active memory\n');
    assert.equal(await readFile(saveAll.uri.fsPath, 'utf8'), 'all memory\n');

    const expectedMemory = new Map<string, (text: string) => boolean>([
      ['src/rename-a.p6', (text) => text.includes('newName') && !text.includes('oldName')],
      ['src/rename-b.p6', (text) => text.includes('newName') && !text.includes('oldName')],
      ['src/stale.p6', (text) => text.includes('staleName') && text.includes('// user edit') && !text.includes('changedName')],
      ['src/action-a.p6', (text) => text === 'ACTION_A_NEW\n'],
      ['src/action-b.p6', (text) => text === 'ACTION_B_NEW\n'],
      ['src/format.p6', (text) => text === 'FORMATTED\n'],
      ['src/range.p6', (text) => text.replaceAll('\r\n', '\n') === 'ARZ\n'],
    ]);
    for (const [file, predicate] of expectedMemory) {
      const document = await documentFor(fixtureRoot, file);
      assert.equal(predicate(document.getText()), true, `Unexpected in-memory mutation for ${file}.`);
      assert.equal(document.isDirty, true, `${file} was unexpectedly saved.`);
      assert.equal(await readFile(document.uri.fsPath, 'utf8'), diskBefore.get(file));
    }

    const taskMarkers = (await readFile(taskMarkerPath, 'utf8')).trim().split(/\r?\n/u);
    assert.deepEqual(new Set(taskMarkers), new Set(['build', 'test', 'format', 'fail', 'timeout']));
    assert.equal(taskMarkers.some((marker) => marker.includes('unsafe')), false);
    assert.equal(taskStarts.some((name) => name.startsWith('p6-interactive-')), false);
    assert.equal(interactiveProbeCalls, 0);
    assert.equal(uiApiCalls.length, 0);
    assert.equal(providerState.renameCalls, 2);
    assert.equal(providerState.codeActionCalls, 1);
    assert.equal(providerState.documentFormatCalls, 1);
    assert.deepEqual(providerState.documentFormatOptions, { tabSize: 3, insertSpaces: false });
    assert.equal(providerState.rangeFormatCalls, 1);
    assert.deepEqual(providerState.rangeFormatOptions, { tabSize: 3, insertSpaces: true });
    assert.deepEqual(providerState.rangeFormatSelection, { start: 1, end: 5, text: '😀é' });

    await writeFile(reportPath, `${JSON.stringify({
      schemaVersion: 1,
      fixtureName,
      vscodeVersion: vscode.version,
      companionConfiguredBeforeActivation: true,
      providerState,
      taskStarts,
      taskMarkers,
      uiApiInvocations: uiApiCalls,
      interactiveProbeInvocationCount: interactiveProbeCalls,
      saveActiveDisk: await readFile(saveActive.uri.fsPath, 'utf8'),
      saveAllDisk: await readFile(saveAll.uri.fsPath, 'utf8'),
      mutationFilesDirtyAndDiskUnchanged: true,
      ...clientReport,
    }, null, 2)}\n`, 'utf8');
  } finally {
    Object.defineProperty(windowRecord, 'showInputBox', inputDescriptor);
    for (const disposable of disposables.reverse()) disposable.dispose();
  }
};
