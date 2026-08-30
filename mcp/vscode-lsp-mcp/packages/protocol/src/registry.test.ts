import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {
  IPC_PROTOCOL_VERSION,
  REGISTRY_ABANDONED_MS,
  REGISTRY_FRESH_MS,
  REGISTRY_VERSION,
  RegistrationStore,
  createInstanceId,
  createRegistrationSecrets,
  createWorkspaceId,
  decideRegistrationCleanup,
  parseRegistrationRecord,
  registrationComparison,
  registrationLeaseState,
  type RuntimeDirectoryLayout,
  type RuntimePrimitives,
  type UsableRegistrationRecord,
} from './index.js';

const primitives = (): RuntimePrimitives => {
  let call = 0;
  return {
    monotonicNowMs: () => 0,
    secureRandomBytes: (length) => new Uint8Array(length).fill(++call),
    sha256Hex: (input) => createHash('sha256').update(input).digest('hex'),
  };
};

const record = (source: RuntimePrimitives, updatedAt = 1_000): UsableRegistrationRecord => {
  const secrets = createRegistrationSecrets(source);
  return {
    registryVersion: REGISTRY_VERSION,
    protocolVersion: IPC_PROTOCOL_VERSION,
    kind: 'usable',
    instanceId: createInstanceId(source),
    workspaceId: createWorkspaceId(source),
    workspaceGeneration: 1,
    recordNonce: secrets.recordNonce,
    workspaceName: 'Unicode 工作区',
    extensionHostPid: 1234,
    activationStartedAt: 100,
    publishedAt: 100,
    updatedAt,
    endpoint: { kind: 'namedPipe', address: '\\\\.\\pipe\\vscode-lsp-mcp-test' },
    authToken: secrets.authToken,
    rootsFingerprint: 'a'.repeat(64),
    roots: [{
      alias: 'app', folderName: 'App', folderIndex: 0,
      lexicalRoot: 'D:\\work\\app', canonicalRoot: 'D:\\work\\app',
      lexicalComparisonKey: 'd:/work/app', canonicalComparisonKey: 'd:/work/app',
    }],
    vscodeVersion: '1.125.0',
  };
};

test('registration schema preserves routing data and excludes secrets from unavailable records', () => {
  const source = primitives();
  const usable = record(source);
  assert.deepEqual(parseRegistrationRecord(JSON.stringify(usable)), usable);
  assert.throws(() => parseRegistrationRecord(JSON.stringify({
    ...usable,
    protocolVersion: '1.0',
  })), /version is unsupported/u);
  const unavailable = {
    ...usable,
    kind: 'unavailable',
    reasonCode: 'runtime_security_failed',
  };
  assert.throws(() => parseRegistrationRecord(JSON.stringify(unavailable)), /fields are invalid/u);
  assert.equal(parseRegistrationRecord(JSON.stringify({
    registryVersion: usable.registryVersion,
    protocolVersion: usable.protocolVersion,
    instanceId: usable.instanceId,
    workspaceId: usable.workspaceId,
    workspaceGeneration: usable.workspaceGeneration,
    recordNonce: usable.recordNonce,
    workspaceName: usable.workspaceName,
    extensionHostPid: usable.extensionHostPid,
    activationStartedAt: usable.activationStartedAt,
    publishedAt: usable.publishedAt,
    updatedAt: usable.updatedAt,
    kind: 'unavailable',
    reasonCode: 'runtime_security_failed',
  })).kind, 'unavailable');
  assert.throws(() => parseRegistrationRecord(JSON.stringify({
    ...usable, recordNonce: `${usable.recordNonce.slice(0, -1)}B`,
  })), /nonce is invalid/u);
});

test('lease cleanup is conservative and never treats a stale PID alone as identity', () => {
  const item = record(primitives(), 1_000);
  assert.equal(registrationLeaseState(item, 1_000 + REGISTRY_FRESH_MS), 'fresh');
  assert.equal(registrationLeaseState(item, 1_001 + REGISTRY_FRESH_MS), 'stale');
  assert.equal(registrationLeaseState(item, 1_000 + REGISTRY_ABANDONED_MS), 'abandoned');
  assert.equal(decideRegistrationCleanup(item, 1_001 + REGISTRY_FRESH_MS, {
    helloSucceeded: false, pidDefinitelyDead: false,
  }), 'retain');
  assert.equal(decideRegistrationCleanup(item, 1_001 + REGISTRY_FRESH_MS, {
    helloSucceeded: true, pidDefinitelyDead: false,
  }), 'degraded');
  assert.equal(decideRegistrationCleanup(item, 1_001 + REGISTRY_FRESH_MS, {
    helloSucceeded: false, pidDefinitelyDead: true,
  }), 'delete');
});

test('registry publish is atomic, comparison-delete is nonce guarded, and invalid records quarantine', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'vlm-registry-test-'));
  assert.equal(path.resolve(root).startsWith(path.resolve(os.tmpdir())), true);
  const layout: RuntimeDirectoryLayout = {
    platform: 'win32', root,
    registrations: path.join(root, 'registrations'),
    quarantine: path.join(root, 'quarantine'),
  };
  await Promise.all([mkdir(layout.registrations), mkdir(layout.quarantine)]);
  const source = primitives();
  const store = new RegistrationStore({
    layout, primitives: source,
    windowsSecurity: {
      ensureSecureRuntimeDirectory: () => ({
        path: root, currentUserSid: 'S-1-5-21-test', protectedDacl: true, reparsePoint: false,
      }),
      verifySecureRegistryFile: () => true,
    },
  });
  try {
    const item = record(source);
    await store.publish(item);
    assert.deepEqual(await store.read(item.instanceId), item);
    assert.equal((await readdir(layout.registrations)).some((name) => name.endsWith('.tmp')), false);
    assert.equal(await store.comparisonAndDelete({ ...registrationComparison(item), recordNonce: 'AgICAgICAgICAgICAgICAg' }), false);
    assert.notEqual(await store.read(item.instanceId), undefined);
    assert.equal(await store.comparisonAndDelete(registrationComparison(item)), true);
    assert.equal(await store.read(item.instanceId), undefined);

    const legacy = record(source);
    const legacyName = `${legacy.instanceId}.json`;
    await writeFile(path.join(layout.registrations, legacyName), JSON.stringify({
      ...legacy,
      protocolVersion: '1.0',
    }), 'utf8');
    const invalidName = '00000000-0000-4000-8000-000000000000.json';
    await writeFile(path.join(layout.registrations, invalidName), '{"kind":"usable","kind":"unavailable"}', 'utf8');
    assert.deepEqual(await store.scan(), []);
    assert.equal((await readdir(layout.registrations)).includes(legacyName), true);
    const quarantined = await readdir(layout.quarantine);
    assert.equal(quarantined.length, 1);
    assert.match(await readFile(path.join(layout.quarantine, quarantined[0] as string), 'utf8'), /"kind"/u);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
