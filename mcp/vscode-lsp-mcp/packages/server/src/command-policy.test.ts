import assert from 'node:assert/strict';
import test from 'node:test';
import { serverCommandSafetyPreflight } from './command-policy.js';

test('server lets standard reload reach trusted-workspace policy and rejects other lifecycle commands', () => {
  assert.equal(serverCommandSafetyPreflight({
    workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA',
    target: { kind: 'command', commandId: 'workbench.action.reloadWindow', arguments: [] },
  }), undefined);
  const result = serverCommandSafetyPreflight({
    workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA',
    target: { kind: 'command', commandId: 'workbench.action.closeWindow', arguments: [] },
  });
  assert.equal(result?.ok, false);
  if (result !== undefined && !result.ok) {
    assert.equal(result.error.code, 'INTERACTIVE_COMMAND');
    assert.deepEqual(result.error.details, {
      targetKind: 'command',
      reason: 'uiInteraction',
    });
  }
});

test('server rejects argument variables but leaves benign commands and task discovery to later gates', () => {
  const variable = serverCommandSafetyPreflight({
    workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA',
    target: {
      kind: 'command',
      commandId: 'fixture.complete',
      arguments: [{ nested: '${input:target}' }],
    },
  });
  assert.equal(variable?.ok, false);
  if (variable !== undefined && !variable.ok) {
    assert.equal(variable.error.code, 'INTERACTIVE_COMMAND');
    if (variable.error.code === 'INTERACTIVE_COMMAND') {
      assert.equal(variable.error.details.reason, 'inputVariable');
    }
  }
  assert.equal(serverCommandSafetyPreflight({
    workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA',
    target: { kind: 'command', commandId: 'fixture.complete', arguments: ['a; b'] },
  }), undefined);
  assert.equal(serverCommandSafetyPreflight({
    workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA',
    target: { kind: 'task', taskName: 'build', taskRoot: 'app' },
  }), undefined);
});
