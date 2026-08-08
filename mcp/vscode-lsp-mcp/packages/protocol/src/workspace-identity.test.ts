import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import {
  WorkspaceIdentityController,
  createInstanceId,
  createWorkspaceId,
  isInstanceId,
  isWorkspaceId,
  type RuntimePrimitives,
} from './index.js';

const deterministicPrimitives = (): RuntimePrimitives => {
  let randomCall = 0;
  return {
    monotonicNowMs: () => 0,
    secureRandomBytes: (length) => {
      randomCall += 1;
      return new Uint8Array(length).fill(randomCall);
    },
    sha256Hex: (input) => createHash('sha256').update(input).digest('hex'),
  };
};

test('instance and workspace identities use the frozen UUIDv4/base64url formats', () => {
  const primitives = deterministicPrimitives();
  const instanceId = createInstanceId(primitives);
  const workspaceId = createWorkspaceId(primitives);

  assert.equal(isInstanceId(instanceId), true);
  assert.match(instanceId, /^[0-9a-f-]{36}$/u);
  assert.equal(isWorkspaceId(workspaceId), true);
  assert.match(workspaceId, /^ws_[A-Za-z0-9_-]{22}$/u);
  assert.equal(workspaceId.includes('='), false);
  assert.equal(isWorkspaceId('server'), false);
  assert.equal(isWorkspaceId('ws_short'), false);
});

test('root changes increment generation and rotate workspace identity', () => {
  const controller = new WorkspaceIdentityController(deterministicPrimitives());
  const roots = [
    { alias: 'app', canonicalComparisonKey: '/workspace/app' },
    { alias: 'lib', canonicalComparisonKey: '/workspace/lib' },
  ] as const;

  const first = controller.observeRoots(roots);
  const unchanged = controller.observeRoots(roots);
  const changed = controller.observeRoots([
    roots[0],
    { alias: 'shared', canonicalComparisonKey: '/workspace/shared' },
  ]);

  assert.equal(first.changed, true);
  assert.equal(first.snapshot.generation, 1);
  assert.equal(unchanged.changed, false);
  assert.equal(unchanged.snapshot, first.snapshot);
  assert.equal(changed.changed, true);
  assert.equal(changed.snapshot.generation, 2);
  assert.notEqual(changed.snapshot.workspaceId, first.snapshot.workspaceId);
  assert.equal(changed.snapshot.instanceId, first.snapshot.instanceId);
  assert.equal(controller.current(), changed.snapshot);
  assert.ok(Object.isFrozen(changed.snapshot));
});

test('root ordering is identity-bearing and an empty root set is rejected', () => {
  const controller = new WorkspaceIdentityController(deterministicPrimitives());
  const app = { alias: 'app', canonicalComparisonKey: '/workspace/app' };
  const lib = { alias: 'lib', canonicalComparisonKey: '/workspace/lib' };
  const first = controller.observeRoots([app, lib]);
  const reordered = controller.observeRoots([lib, app]);

  assert.equal(reordered.snapshot.generation, first.snapshot.generation + 1);
  assert.notEqual(reordered.snapshot.workspaceId, first.snapshot.workspaceId);
  assert.throws(() => controller.observeRoots([]), RangeError);
});

test('unavailable workspace states remain stable and rotate into usable generations', () => {
  const controller = new WorkspaceIdentityController(deterministicPrimitives());
  const unavailable = controller.observeUnavailable('no_workspace_folders');
  const same = controller.observeUnavailable('no_workspace_folders');
  const changedReason = controller.observeUnavailable('unsupported_uri_scheme:file+virtual');
  const usable = controller.observeRoots([
    { alias: 'app', canonicalComparisonKey: '/workspace/app' },
  ]);

  assert.equal(unavailable.snapshot.generation, 1);
  assert.equal(same.changed, false);
  assert.equal(same.snapshot, unavailable.snapshot);
  assert.equal(changedReason.snapshot.generation, 2);
  assert.equal(usable.snapshot.generation, 3);
  assert.equal(usable.snapshot.instanceId, unavailable.snapshot.instanceId);
  assert.notEqual(usable.snapshot.workspaceId, unavailable.snapshot.workspaceId);
});
