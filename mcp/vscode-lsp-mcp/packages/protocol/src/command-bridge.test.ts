import assert from 'node:assert/strict';
import test from 'node:test';
import type { WorkspaceRouteIdentity } from './index.js';
import {
  parseCommandExecuteBridgeRequest,
  parseCommandExecuteBridgeResponse,
} from './command-bridge.js';

const workspace: WorkspaceRouteIdentity = {
  workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA' as WorkspaceRouteIdentity['workspaceId'],
  generation: 4,
};

test('command bridge request is closed and applies public defaults', () => {
  const request = parseCommandExecuteBridgeRequest({
    workspace,
    target: { kind: 'command', commandId: 'safe.command' },
  });
  assert.deepEqual(request, {
    workspace,
    target: { kind: 'command', commandId: 'safe.command', arguments: [] },
    saveBeforeRun: 'none',
    timeoutMs: 120_000,
    maxOutputChars: 20_000,
    retainOutputLog: false,
  });
  assert.equal(Object.isFrozen(request), true);
  assert.throws(() => parseCommandExecuteBridgeRequest({ ...request, injected: true }));
  assert.throws(() => parseCommandExecuteBridgeRequest({
    ...request,
    workspace: { ...workspace, generation: 0 },
  }));
});

test('command bridge accepts exact task requests and strictly validates responses', () => {
  assert.deepEqual(parseCommandExecuteBridgeRequest({
    workspace,
    target: { kind: 'task', taskName: 'build', taskRoot: 'root' },
    saveBeforeRun: 'all',
    timeoutMs: 600_000,
    maxOutputChars: 200_000,
    retainOutputLog: true,
  }), {
    workspace,
    target: { kind: 'task', taskName: 'build', taskRoot: 'root' },
    saveBeforeRun: 'all',
    timeoutMs: 600_000,
    maxOutputChars: 200_000,
    retainOutputLog: true,
  });
  const response = parseCommandExecuteBridgeResponse({
    ok: true,
    data: { output: 'done' },
  });
  assert.deepEqual(response, { ok: true, data: { output: 'done' } });
  assert.equal(Object.isFrozen(response), true);
  assert.equal(Object.isFrozen(response.ok ? response.data : response.error), true);
  assert.throws(() => parseCommandExecuteBridgeResponse({
    ok: true,
    data: { output: 'done', internal: true },
  }));
});
