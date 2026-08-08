import assert from 'node:assert/strict';
import test from 'node:test';
import type { WorkspaceRouteIdentity } from '@simplechat/vscode-lsp-mcp-protocol';
import { WorkspaceExclusiveMutationGate } from './mutation-gate.js';

const workspace = (id: string, generation = 1): WorkspaceRouteIdentity => ({
  workspaceId: id as WorkspaceRouteIdentity['workspaceId'],
  generation,
});

test('mutation gate serializes apply and command per workspace while other workspaces proceed', async () => {
  const gate = new WorkspaceExclusiveMutationGate();
  let releaseFirst = (): void => undefined;
  const holdFirst = new Promise<void>((resolve) => {
    releaseFirst = resolve;
  });
  const events: string[] = [];
  const first = gate.runExclusive(workspace('ws_AAAAAAAAAAAAAAAAAAAAAA'), 'apply', async () => {
    events.push('first-start');
    await holdFirst;
    events.push('first-end');
  });
  const second = gate.runExclusive(workspace('ws_AAAAAAAAAAAAAAAAAAAAAA'), 'command', async () => {
    events.push('second');
  });
  const other = gate.runExclusive(workspace('ws_BBBBBBBBBBBBBBBBBBBBBB'), 'apply', async () => {
    events.push('other');
  });
  await other;
  assert.deepEqual(events, ['first-start', 'other']);
  releaseFirst();
  await Promise.all([first, second]);
  assert.deepEqual(events, ['first-start', 'other', 'first-end', 'second']);
});

test('mutation gate releases a workspace after failure and validates its identity', async () => {
  const gate = new WorkspaceExclusiveMutationGate();
  const target = workspace('ws_AAAAAAAAAAAAAAAAAAAAAA');
  await assert.rejects(gate.runExclusive(target, 'apply', () => Promise.reject(new Error('failed'))));
  assert.equal(await gate.runExclusive(target, 'command', () => Promise.resolve('released')), 'released');
  await assert.rejects(
    gate.runExclusive(workspace('invalid'), 'apply', () => Promise.resolve()),
    TypeError,
  );
});

test('mutation gate supports a non-queued lease retained until explicit release', async () => {
  const gate = new WorkspaceExclusiveMutationGate();
  const target = workspace('ws_AAAAAAAAAAAAAAAAAAAAAA');
  const lease = gate.tryAcquire(target, 'command');
  assert.ok(lease);
  assert.equal(gate.tryAcquire(target, 'command'), undefined);
  assert.ok(gate.tryAcquire(workspace('ws_BBBBBBBBBBBBBBBBBBBBBB'), 'command'));

  let entered = false;
  const queued = gate.runExclusive(target, 'apply', async () => {
    entered = true;
  });
  await Promise.resolve();
  assert.equal(entered, false);
  lease.release();
  lease.release();
  await queued;
  assert.equal(entered, true);
  const reacquired = gate.tryAcquire(target, 'command');
  assert.ok(reacquired);
  reacquired.release();
});
