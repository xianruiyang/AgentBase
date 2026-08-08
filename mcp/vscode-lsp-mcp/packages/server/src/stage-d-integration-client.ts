import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import {
  assertToolOutput,
  decodeYamlText,
  type ToolName,
  type ToolResponseMap,
} from '@simplechat/vscode-lsp-mcp-protocol';

const requiredEnvironment = (name: string): string => {
  const value = process.env[name];
  if (value === undefined || value.length === 0) throw new Error(`Missing ${name}.`);
  return value;
};

const forbiddenKeys = new Set([
  'authToken',
  'endpoint',
  'instanceId',
  'provider',
  'uri',
  'workspaceGeneration',
]);

interface RawToolResult {
  readonly content?: unknown | undefined;
  readonly isError?: boolean | undefined;
  readonly structuredContent?: unknown | undefined;
}

const assertNoInternalLeak = (value: unknown, fixtureRoot: string): void => {
  const visit = (candidate: unknown): void => {
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
  assert.equal(serialized.includes(fixtureRoot.replaceAll('\\', '/').toLowerCase()), false);
  assert.equal(serialized.includes('file://'), false);
  assert.equal(serialized.includes('vscode.execute'), false);
  assert.equal(serialized.includes('\\\\.\\pipe'), false);
};

const main = async (): Promise<void> => {
  const fixtureName = requiredEnvironment('STAGE_D_FIXTURE_NAME');
  const fixtureRoot = requiredEnvironment('STAGE_D_EXPECTED_ROOT');
  const directory = path.dirname(fileURLToPath(import.meta.url));
  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [path.join(directory, 'cli.js')],
    cwd: process.cwd(),
    stderr: 'pipe',
  });
  const client = new Client({ name: 'stage-d-integration', version: '1.0.0' });
  const semanticResponses: unknown[] = [];

  const call = async <K extends ToolName>(
    name: K,
    argumentsValue: Record<string, unknown>,
  ): Promise<{ readonly raw: RawToolResult; readonly response: ToolResponseMap[K] }> => {
    const raw = await client.callTool({ name, arguments: argumentsValue });
    const publicRaw = raw as unknown as RawToolResult;
    assert.equal(publicRaw.structuredContent, undefined);
    assert.ok(Array.isArray(publicRaw.content));
    const content = publicRaw.content[0] as {
      readonly type?: unknown;
      readonly text?: unknown;
    } | undefined;
    assert.equal(content?.type, 'text');
    assert.equal(typeof content?.text, 'string');
    if (typeof content?.text !== 'string') throw new Error(`${name} did not return YAML TextContent.`);
    const response = decodeYamlText(content.text);
    assertToolOutput(name, response);
    semanticResponses.push(raw);
    return { raw: publicRaw, response: response as unknown as ToolResponseMap[K] };
  };

  const successfulCommand = async (
    workspaceId: string,
    commandId: string,
    saveBeforeRun: 'none' | 'active' | 'all' = 'none',
    maxOutputChars?: number,
  ) => {
    const result = await call('execute_command', {
      workspaceId,
      target: { kind: 'command', commandId },
      saveBeforeRun,
      ...(maxOutputChars === undefined ? {} : { maxOutputChars }),
    });
    assert.equal(
      result.raw.isError,
      undefined,
      `${commandId} returned an MCP error: ${JSON.stringify(result.response)}.`,
    );
    assert.equal(result.response.ok, true);
    if (!result.response.ok) throw new Error(`${commandId} failed.`);
    return result.response.data;
  };

  const task = async (
    workspaceId: string,
    rootAlias: string,
    taskName: string,
    timeoutMs = 5_000,
    retainOutputLog = false,
  ) =>
    call('execute_command', {
      workspaceId,
      target: { kind: 'task', taskName, taskRoot: rootAlias },
      timeoutMs,
      retainOutputLog,
    });

  try {
    await client.connect(transport);
    const listed = await call('list_workspaces', {});
    assert.equal(listed.response.ok, true);
    if (!listed.response.ok) throw new Error('Workspace discovery failed.');
    const matches = listed.response.data.results.filter((workspace) => workspace.name === fixtureName);
    assert.equal(matches.length, 1);
    const workspaceId = matches[0]?.workspaceId;
    const rootAlias = matches[0]?.roots[0];
    assert.ok(workspaceId);
    assert.ok(rootAlias);

    const executionCapabilities = await call('get_capabilities', {
      workspaceId,
      capabilities: ['commands', 'tasks'],
    });
    assert.deepEqual(executionCapabilities.response, {
      ok: true,
      data: {
        results: [
          { name: 'commands', status: 'available' },
          { name: 'tasks', status: 'available' },
        ],
        available: 2,
      },
    });
    assert.deepEqual(
      await successfulCommand(workspaceId, 'workbench.action.debug.continue'),
      {},
    );

    const noneState = await successfulCommand(workspaceId, 'p6.test.documentState', 'none');
    assert.deepEqual(noneState.result, { activeDirty: true, allDirty: true });
    const activeState = await successfulCommand(workspaceId, 'p6.test.documentState', 'active');
    assert.deepEqual(activeState.result, { activeDirty: false, allDirty: true });
    const allState = await successfulCommand(workspaceId, 'p6.test.documentState', 'all');
    assert.deepEqual(allState.result, { activeDirty: false, allDirty: false });

    const longOutput = await successfulCommand(
      workspaceId,
      'p6.test.longOutput',
      'none',
      1_000,
    );
    assert.equal(longOutput.outputTruncated, true);
    assert.equal([...(longOutput.output ?? '')].length, 1_000);
    assert.equal((longOutput.output ?? '').endsWith('😀'), true);

    const successfulTasks: string[] = [];
    for (const taskName of ['p6-build', 'p6-test', 'p6-format']) {
      const result = await task(workspaceId, rootAlias, taskName);
      assert.equal(result.raw.isError, undefined, JSON.stringify(result.response));
      assert.deepEqual(result.response, { ok: true, data: {} });
      assert.equal(JSON.stringify(result.response).includes('stdout'), false);
      assert.equal(JSON.stringify(result.response).includes('stderr'), false);
      assert.equal(JSON.stringify(result.response).includes('output'), false);
      successfulTasks.push(taskName);
    }

    const retainedSuccessfulTask = await task(workspaceId, rootAlias, 'p6-build', 5_000, true);
    assert.equal(retainedSuccessfulTask.raw.isError, undefined, JSON.stringify(retainedSuccessfulTask.response));
    assert.equal(retainedSuccessfulTask.response.ok, true);
    if (!retainedSuccessfulTask.response.ok || retainedSuccessfulTask.response.data.outputLog === undefined) {
      throw new Error('Successful task did not retain its requested output log.');
    }
    const successfulOutputLog = retainedSuccessfulTask.response.data.outputLog;
    const successfulOutput = await readFile(
      path.join(fixtureRoot, ...successfulOutputLog.path.split('/')),
      'utf8',
    );
    assert.match(successfulOutput, /P6 successful build output/u);
    assert.equal(successfulOutputLog.lineCount, 1);
    assert.equal(successfulOutputLog.byteCount, Buffer.byteLength(successfulOutput));
    assert.equal(successfulOutputLog.encoding, 'utf-8');
    assert.equal(successfulOutputLog.truncated, false);

    const failedTask = await task(workspaceId, rootAlias, 'p6-fail');
    assert.equal(failedTask.raw.isError, true);
    assert.equal(failedTask.response.ok, false);
    if (failedTask.response.ok) throw new Error('Non-zero task unexpectedly succeeded.');
    assert.equal(failedTask.response.error.code, 'COMMAND_FAILED');
    const failedDetails = failedTask.response.error.details;
    assert.equal(failedDetails?.targetKind, 'task');
    assert.equal(failedDetails?.reason, 'nonZeroExit');
    assert.equal(failedDetails?.outcome, 'failed');
    assert.equal(failedDetails?.exitCode, 7);
    assert.ok(failedDetails?.outputLog);
    assert.match(failedDetails.outputLog.path, /^\.vscode-lsp-mcp\/task-logs\/.+\.log$/u);
    assert.equal(path.isAbsolute(failedDetails.outputLog.path), false);
    const failedOutput = await readFile(
      path.join(fixtureRoot, ...failedDetails.outputLog.path.split('/')),
      'utf8',
    );
    assert.match(failedOutput, /P6 task output first line/u);
    assert.match(failedOutput, /P6 task error detail/u);
    assert.equal(failedDetails.outputLog.lineCount, 2);
    assert.equal(failedDetails.outputLog.byteCount, Buffer.byteLength(failedOutput));
    assert.equal(failedDetails.outputLog.encoding, 'utf-8');
    assert.equal(failedDetails.outputLog.truncated, false);

    const timeoutStartedAt = Date.now();
    const timedOutTask = await task(workspaceId, rootAlias, 'p6-timeout', 1_000);
    const timeoutElapsedMs = Date.now() - timeoutStartedAt;
    assert.equal(timedOutTask.raw.isError, true);
    assert.equal(timedOutTask.response.ok, false);
    if (timedOutTask.response.ok) throw new Error('Timeout task unexpectedly succeeded.');
    assert.equal(timedOutTask.response.error.code, 'COMMAND_TIMEOUT');
    assert.equal(timedOutTask.response.error.details?.targetKind, 'task');
    assert.equal(timedOutTask.response.error.details?.timeoutMs, 1_000);
    assert.ok(timeoutElapsedMs >= 900 && timeoutElapsedMs < 7_000);

    const interactiveInput = await task(workspaceId, rootAlias, 'p6-interactive-input');
    assert.equal(interactiveInput.raw.isError, true);
    assert.equal(interactiveInput.response.ok, false);
    if (interactiveInput.response.ok) throw new Error('Input task unexpectedly succeeded.');
    assert.equal(interactiveInput.response.error.code, 'INTERACTIVE_COMMAND');
    assert.equal(interactiveInput.response.error.details?.reason, 'inputVariable');

    const interactiveCommand = await task(workspaceId, rootAlias, 'p6-interactive-command');
    assert.equal(interactiveCommand.raw.isError, true);
    assert.equal(interactiveCommand.response.ok, false);
    if (interactiveCommand.response.ok) throw new Error('Command-variable task unexpectedly succeeded.');
    assert.equal(interactiveCommand.response.error.code, 'INTERACTIVE_COMMAND');
    assert.equal(interactiveCommand.response.error.details?.reason, 'commandVariable');

    const riskyCommand = await call('execute_command', {
      workspaceId,
      target: { kind: 'command', commandId: 'workbench.action.quickOpen' },
    });
    assert.equal(riskyCommand.raw.isError, true);
    assert.equal(riskyCommand.response.ok, false);
    if (riskyCommand.response.ok) throw new Error('Risky command unexpectedly succeeded.');
    assert.equal(riskyCommand.response.error.code, 'INTERACTIVE_COMMAND');
    assert.equal(riskyCommand.response.error.details?.reason, 'uiInteraction');

    const rename = await call('rename_preview', {
      workspaceId,
      file: 'src/rename-a.p6',
      line: 1,
      column: 14,
      newName: 'newName',
      includeGlobs: ['src/**'],
    });
    assert.equal(rename.response.ok, true);
    if (!rename.response.ok || rename.response.data.previewId === undefined) {
      throw new Error('Multi-file rename preview failed.');
    }
    assert.deepEqual(rename.response.data.changes.map((change) => change.file), [
      'src/rename-a.p6',
      'src/rename-b.p6',
    ]);
    const renameApply = await call('rename_apply', { previewId: rename.response.data.previewId });
    assert.deepEqual(renameApply.response, {
      ok: true,
      data: { changedFiles: ['src/rename-a.p6', 'src/rename-b.p6'] },
    });
    const repeatedRename = await call('rename_apply', { previewId: rename.response.data.previewId });
    assert.equal(repeatedRename.response.ok, false);
    if (!repeatedRename.response.ok) assert.equal(repeatedRename.response.error.code, 'PREVIEW_NOT_FOUND');

    const stale = await call('rename_preview', {
      workspaceId,
      file: 'src/stale.p6',
      line: 1,
      column: 14,
      newName: 'changedName',
      includeGlobs: ['src/**'],
    });
    assert.equal(stale.response.ok, true);
    if (!stale.response.ok || stale.response.data.previewId === undefined) {
      throw new Error('Stale rename preview failed.');
    }
    await successfulCommand(workspaceId, 'p6.test.editAfterPreview');
    const staleApply = await call('rename_apply', { previewId: stale.response.data.previewId });
    assert.equal(staleApply.raw.isError, true);
    assert.equal(staleApply.response.ok, false);
    if (staleApply.response.ok) throw new Error('Stale rename unexpectedly applied.');
    assert.equal(staleApply.response.error.code, 'DOCUMENT_CHANGED');
    assert.equal(
      staleApply.response.error.details?.reason === 'content' ||
        staleApply.response.error.details?.reason === 'version',
      true,
    );

    const actions = await call('code_actions', {
      workspaceId,
      file: 'src/action-a.p6',
      range: { startLine: 1, startColumn: 1, endLine: 1, endColumn: 2 },
      onlyKinds: ['quickfix'],
    });
    assert.equal(actions.response.ok, true);
    if (!actions.response.ok || actions.response.data.actionSetId === undefined) {
      throw new Error('Code Action listing failed.');
    }
    assert.equal(actions.response.data.results.length, 1);
    const action = actions.response.data.results[0];
    assert.ok(action);
    const actionPreview = await call('code_action_preview', {
      actionSetId: actions.response.data.actionSetId,
      actionId: action.actionId,
    });
    assert.equal(actionPreview.response.ok, true);
    if (!actionPreview.response.ok || actionPreview.response.data.previewId === undefined) {
      throw new Error('Code Action preview failed.');
    }
    assert.deepEqual(actionPreview.response.data.changes.map((change) => change.file), [
      'src/action-a.p6',
      'src/action-b.p6',
    ]);
    const actionApply = await call('code_action_apply', {
      previewId: actionPreview.response.data.previewId,
    });
    assert.deepEqual(actionApply.response, {
      ok: true,
      data: { changedFiles: ['src/action-a.p6', 'src/action-b.p6'] },
    });

    const format = await call('format_preview', {
      workspaceId,
      file: 'src/format.p6',
    });
    assert.equal(format.response.ok, true);
    if (!format.response.ok || format.response.data.previewId === undefined) {
      throw new Error('Document format preview failed.');
    }
    const formatApply = await call('format_apply', { previewId: format.response.data.previewId });
    assert.deepEqual(formatApply.response, {
      ok: true,
      data: { changedFiles: ['src/format.p6'] },
    });

    const rangeFormat = await call('format_preview', {
      workspaceId,
      file: 'src/range.p6',
      range: { startLine: 1, startColumn: 2, endLine: 1, endColumn: 6 },
      options: { insertSpaces: true },
    });
    assert.equal(rangeFormat.response.ok, true);
    if (!rangeFormat.response.ok || rangeFormat.response.data.previewId === undefined) {
      throw new Error('Range format preview failed.');
    }
    assert.equal(rangeFormat.response.data.changes[0]?.edits[0]?.oldText, '😀é');
    const rangeApply = await call('format_apply', { previewId: rangeFormat.response.data.previewId });
    assert.deepEqual(rangeApply.response, {
      ok: true,
      data: { changedFiles: ['src/range.p6'] },
    });

    const snapshot = await successfulCommand(workspaceId, 'p6.test.snapshot');
    assert.equal(snapshot.result !== undefined && !Array.isArray(snapshot.result), true);
    const snapshotResult = snapshot.result as Record<string, unknown>;
    assert.equal(snapshotResult.uiApiCalls, 0);
    assert.equal(snapshotResult.interactiveProbeCalls, 0);
    assert.equal(snapshotResult.interactiveTaskStarts, 0);

    semanticResponses.forEach((response) => assertNoInternalLeak(response, fixtureRoot));
    process.stdout.write(JSON.stringify({
      saveModes: ['none', 'active', 'all'],
      outputCodePoints: [...(longOutput.output ?? '')].length,
      outputTruncated: longOutput.outputTruncated === true,
      successfulTasks,
      successfulTaskOutputRetained: true,
      taskOutputAbsent: false,
      nonZeroExitCode: failedTask.response.ok ? undefined : failedTask.response.error.details?.exitCode,
      timeoutErrorCode: timedOutTask.response.ok ? undefined : timedOutTask.response.error.code,
      timeoutOutcome: timedOutTask.response.ok ? undefined : timedOutTask.response.error.details?.outcome,
      timeoutElapsedMs,
      interactiveInputReason: interactiveInput.response.ok
        ? undefined
        : interactiveInput.response.error.details?.reason,
      interactiveCommandReason: interactiveCommand.response.ok
        ? undefined
        : interactiveCommand.response.error.details?.reason,
      riskyCommandReason: riskyCommand.response.ok
        ? undefined
        : riskyCommand.response.error.details?.reason,
      renameChangedFiles: renameApply.response.ok ? renameApply.response.data.changedFiles.length : 0,
      repeatedPreviewRejected: !repeatedRename.response.ok,
      staleApplyErrorCode: staleApply.response.ok ? undefined : staleApply.response.error.code,
      codeActionChangedFiles: actionApply.response.ok ? actionApply.response.data.changedFiles.length : 0,
      formatChangedFiles: formatApply.response.ok ? formatApply.response.data.changedFiles.length : 0,
      rangeFormatChangedFiles: rangeApply.response.ok ? rangeApply.response.data.changedFiles.length : 0,
      uiApiCalls: snapshotResult.uiApiCalls,
      interactiveProbeCalls: snapshotResult.interactiveProbeCalls,
      interactiveTaskStarts: snapshotResult.interactiveTaskStarts,
      leakageChecksPassed: true,
    }));
  } finally {
    await client.close().catch(() => undefined);
  }
};

void main().catch((error: unknown) => {
  const message = error instanceof Error ? error.stack ?? error.message : String(error);
  process.stderr.write(`${message}\n`);
  process.exitCode = 1;
});
