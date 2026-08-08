import assert from 'node:assert/strict';
import test from 'node:test';
import {
  BridgeTransportError,
  COMMAND_EXECUTE_BRIDGE_METHOD,
  IPC_MAX_REQUEST_TIMEOUT_MS,
  type JsonObject,
  type WorkspaceRouteIdentity,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  COMMAND_BRIDGE_TRANSPORT_GRACE_MS,
  CommandService,
  type CommandWorkspaceConnector,
} from './command-service.js';
import {
  WorkspaceRoutingError,
  type BridgeProbeSession,
} from './workspace-router.js';

const workspace: WorkspaceRouteIdentity = {
  workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA' as WorkspaceRouteIdentity['workspaceId'],
  generation: 7,
};

class FakeSession implements BridgeProbeSession {
  readonly calls: Array<{
    readonly method: string;
    readonly params: JsonObject;
    readonly options: {
      readonly deadlineAt?: number;
      readonly maximumTimeoutMs?: number;
      readonly signal?: AbortSignal;
    } | undefined;
  }> = [];
  closes = 0;
  result: unknown = { ok: true, data: {} };
  error: unknown;

  call(
    method: string,
    params: JsonObject,
    options?: {
      readonly deadlineAt?: number;
      readonly maximumTimeoutMs?: number;
      readonly signal?: AbortSignal;
    },
  ): Promise<unknown> {
    this.calls.push({ method, params, options });
    return this.error === undefined ? Promise.resolve(this.result) : Promise.reject(this.error);
  }

  close(): Promise<void> {
    this.closes += 1;
    return Promise.resolve();
  }
}

const connector = (session: FakeSession, onConnect?: () => void): CommandWorkspaceConnector => ({
  connectWorkspaceBinding: (workspaceId) => {
    onConnect?.();
    assert.equal(workspaceId, workspace.workspaceId);
    return Promise.resolve({ workspace, session });
  },
});

test('server command safety rejects interactive targets before route lookup', async () => {
  const session = new FakeSession();
  let connections = 0;
  const service = new CommandService({ connector: connector(session, () => { connections += 1; }) });
  const result = await service.executeCommand({
    workspaceId: workspace.workspaceId,
    target: { kind: 'command', commandId: 'workbench.action.showCommands' },
  });
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(result.error.code, 'INTERACTIVE_COMMAND');
    assert.deepEqual(result.error.details, { targetKind: 'command', reason: 'uiInteraction' });
  }
  assert.equal(connections, 0);
  assert.equal(session.calls.length, 0);
});

test('command service binds the exact route and grants a bounded long bridge deadline', async () => {
  const session = new FakeSession();
  session.result = { ok: true, data: { output: 'done' } };
  const now = 1_000_000;
  const service = new CommandService({ connector: connector(session), now: () => now });
  const result = await service.executeCommand({
    workspaceId: workspace.workspaceId,
    target: { kind: 'task', taskName: 'build', taskRoot: 'root' },
    timeoutMs: 600_000,
    retainOutputLog: true,
  });
  assert.deepEqual(result, { ok: true, data: { output: 'done' } });
  assert.equal(session.calls.length, 1);
  assert.deepEqual(session.calls[0], {
    method: COMMAND_EXECUTE_BRIDGE_METHOD,
    params: {
      maxOutputChars: 20_000,
      saveBeforeRun: 'none',
      retainOutputLog: true,
      target: { kind: 'task', taskName: 'build', taskRoot: 'root' },
      timeoutMs: 600_000,
      workspace,
    },
    options: {
      deadlineAt: now + IPC_MAX_REQUEST_TIMEOUT_MS,
      maximumTimeoutMs: IPC_MAX_REQUEST_TIMEOUT_MS,
    },
  });
  assert.equal(
    IPC_MAX_REQUEST_TIMEOUT_MS,
    600_000 + COMMAND_BRIDGE_TRANSPORT_GRACE_MS,
  );
  assert.equal(session.closes, 1);
});

test('command service distinguishes pre-dispatch route failure from unknown post-dispatch outcome', async () => {
  const notFound = new CommandService({
    connector: {
      connectWorkspaceBinding: () => Promise.reject(new WorkspaceRoutingError('notFound', 'private')),
    },
  });
  const input = {
    workspaceId: workspace.workspaceId,
    target: { kind: 'command' as const, commandId: 'safe.command' },
  };
  const missing = await notFound.executeCommand(input);
  assert.equal(missing.ok, false);
  if (!missing.ok) {
    assert.equal(missing.error.code, 'WORKSPACE_NOT_FOUND');
    assert.equal(missing.error.retryable, true);
  }

  const session = new FakeSession();
  session.error = new BridgeTransportError('disconnected', 'private', 'unknown');
  const disconnected = await new CommandService({ connector: connector(session) })
    .executeCommand(input);
  assert.deepEqual(disconnected, {
    ok: false,
    error: {
      code: 'WORKSPACE_DISCONNECTED',
      message: 'The requested workspace disconnected after command dispatch; the outcome is unknown.',
      retryable: false,
      details: { phase: 'command', outcome: 'unknown' },
    },
  });
  assert.equal(session.closes, 1);
});

test('malformed extension responses fail closed as unknown command outcomes', async () => {
  const session = new FakeSession();
  session.result = { ok: true, data: {}, internal: true };
  const result = await new CommandService({ connector: connector(session) }).executeCommand({
    workspaceId: workspace.workspaceId,
    target: { kind: 'task', taskName: 'test', taskRoot: 'root' },
  });
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(result.error.code, 'WORKSPACE_DISCONNECTED');
    assert.deepEqual(result.error.details, { phase: 'command', outcome: 'unknown' });
  }
  assert.equal(session.closes, 1);
});
