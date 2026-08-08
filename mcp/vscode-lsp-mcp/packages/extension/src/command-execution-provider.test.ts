import assert from 'node:assert/strict';
import test from 'node:test';
import {
  COMMAND_EXECUTE_BRIDGE_METHOD,
  type ExecuteCommandInput,
  type InternalWorkspaceRoot,
  type RootAlias,
  type ToolResponseMap,
  type WorkspacePathContext,
  type WorkspaceRouteIdentity,
} from '@simplechat/vscode-lsp-mcp-protocol';
import { createCommandExecuteBridgeHandler } from './command-execution-provider.js';

const root: InternalWorkspaceRoot = {
  alias: 'root' as RootAlias,
  name: 'root',
  folderIndex: 0,
  lexicalAbsolutePath: 'C:\\workspace',
  canonicalAbsolutePath: 'C:\\workspace',
  lexicalComparisonKey: 'c:\\workspace',
  canonicalComparisonKey: 'c:\\workspace',
};
const context: WorkspacePathContext = { platform: 'win32', roots: [root] };
const workspace: WorkspaceRouteIdentity = {
  workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA' as WorkspaceRouteIdentity['workspaceId'],
  generation: 3,
};

test('command bridge handler forwards normalized public input and the caller signal', async () => {
  let captured: ExecuteCommandInput | undefined;
  let capturedSignal: AbortSignal | undefined;
  const response: ToolResponseMap['execute_command'] = { ok: true, data: { output: 'done' } };
  const handler = createCommandExecuteBridgeHandler({
    execute: (_context, _workspace, input, signal) => {
      captured = input;
      capturedSignal = signal;
      return Promise.resolve(response);
    },
  });
  const controller = new AbortController();
  assert.deepEqual(await handler(context, workspace, {
    method: COMMAND_EXECUTE_BRIDGE_METHOD,
    params: {
      workspace: { workspaceId: workspace.workspaceId, generation: workspace.generation },
      target: { kind: 'command', commandId: 'safe.command' },
      saveBeforeRun: 'none',
      timeoutMs: 120_000,
      maxOutputChars: 20_000,
      retainOutputLog: false,
    },
  }, controller.signal), response);
  assert.deepEqual(captured, {
    workspaceId: workspace.workspaceId,
    target: { kind: 'command', commandId: 'safe.command', arguments: [] },
    saveBeforeRun: 'none',
    timeoutMs: 120_000,
    maxOutputChars: 20_000,
    retainOutputLog: false,
  });
  assert.equal(capturedSignal, controller.signal);
});

test('command bridge handler rejects route mismatch before execution and ignores other methods', async () => {
  let calls = 0;
  const handler = createCommandExecuteBridgeHandler({
    execute: () => { calls += 1; return Promise.resolve({ ok: true, data: {} }); },
  });
  const signal = new AbortController().signal;
  assert.equal(await handler(context, workspace, {
    method: 'mutation.apply',
    params: {},
  }, signal), undefined);
  const mismatch = await handler(context, workspace, {
    method: COMMAND_EXECUTE_BRIDGE_METHOD,
    params: {
      workspace: { ...workspace, generation: workspace.generation + 1 },
      target: { kind: 'task', taskName: 'build', taskRoot: 'root' },
      saveBeforeRun: 'none',
      timeoutMs: 120_000,
      maxOutputChars: 20_000,
      retainOutputLog: false,
    },
  }, signal);
  assert.deepEqual(mismatch, {
    error: {
      code: 'WORKSPACE_NOT_FOUND',
      message: 'The command bridge request does not match the active workspace route.',
      retryable: true,
    },
    ok: false,
  });
  assert.equal(calls, 0);
  await assert.rejects(handler(context, workspace, {
    method: COMMAND_EXECUTE_BRIDGE_METHOD,
    params: {
      workspace: { workspaceId: workspace.workspaceId, generation: workspace.generation },
      target: { kind: 'task', taskName: 'build' },
      injected: true,
    },
  }, signal));
  assert.equal(calls, 0);
});
