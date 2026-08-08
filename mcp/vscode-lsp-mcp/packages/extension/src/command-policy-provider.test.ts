import assert from 'node:assert/strict';
import test from 'node:test';
import {
  CommandPolicyPreflight,
  createVscodeCommandPolicyHost,
} from './command-policy-provider.js';

const allowlist = {
  commands: [{
    commandId: 'fixture.complete',
    nonInteractive: true,
    completion: 'promise',
    maxTimeoutMs: 30_000,
  }],
  tasks: [],
};

test('extension command preflight reads the current workspace-scoped configuration and trust state', () => {
  const reads: string[] = [];
  const host = createVscodeCommandPolicyHost({
    workspace: {
      isTrusted: true,
      getConfiguration: (section) => {
        reads.push(section);
        return {
          get: <T>(key: string): T | undefined => {
            reads.push(key);
            return allowlist as T;
          },
        };
      },
    },
  });
  const decision = new CommandPolicyPreflight(host).check({
    workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA',
    target: { kind: 'command', commandId: 'fixture.complete', arguments: [] },
    timeoutMs: 20_000,
  });
  assert.equal(decision.ok, true);
  assert.deepEqual(reads, ['vscodeLspMcp', 'commandPolicy']);
});

test('extension preflight fails closed for absent policy, untrusted workspaces, and task targets', () => {
  const absent = new CommandPolicyPreflight({
    isWorkspaceTrusted: () => true,
    readCommandPolicyConfiguration: () => undefined,
  }).check({
    workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA',
    target: { kind: 'command', commandId: 'fixture.complete' },
  });
  assert.equal(absent.ok, false);
  if (!absent.ok) assert.equal(absent.error.code, 'COMMAND_NOT_ALLOWED');

  const untrusted = new CommandPolicyPreflight({
    isWorkspaceTrusted: () => false,
    readCommandPolicyConfiguration: () => allowlist,
  }).check({
    workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA',
    target: { kind: 'command', commandId: 'fixture.complete' },
  });
  assert.equal(untrusted.ok, false);
  if (!untrusted.ok) assert.equal(untrusted.error.code, 'INTERACTIVE_COMMAND');

  const task = new CommandPolicyPreflight({
    isWorkspaceTrusted: () => true,
    readCommandPolicyConfiguration: () => allowlist,
  }).check({
    workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA',
    target: { kind: 'task', taskName: 'build', taskRoot: 'app' },
  });
  assert.equal(task.ok, false);
  if (!task.ok) assert.equal(task.error.code, 'COMMAND_NOT_ALLOWED');
});

test('extension preflight fails closed when the configuration source throws', () => {
  const decision = new CommandPolicyPreflight({
    isWorkspaceTrusted: () => true,
    readCommandPolicyConfiguration: () => {
      throw new Error('configuration unavailable');
    },
  }).check({
    workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA',
    target: { kind: 'command', commandId: 'fixture.complete' },
  });
  assert.equal(decision.ok, false);
  if (!decision.ok) {
    assert.equal(decision.error.code, 'COMMAND_NOT_ALLOWED');
    assert.equal(typeof decision.configurationIssue, 'string');
  }
});
