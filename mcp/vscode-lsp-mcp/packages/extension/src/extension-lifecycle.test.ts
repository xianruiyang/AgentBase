import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {
  BridgeClientSession,
  RegistrationStore,
  authenticateIpcClientConnection,
  connectNodeRawByte,
  type RawByteConnection,
  type RawByteServer,
  type RuntimeDirectoryLayout,
  type RuntimePrimitives,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  ExtensionRegistrationService,
  type ExtensionWorkspaceSnapshot,
} from './extension-lifecycle.js';
import { createExtensionTransportServer } from './ipc-host.js';

class PendingServer implements RawByteServer {
  #reject: ((error: Error) => void) | undefined;
  closed = false;

  accept(): Promise<RawByteConnection> {
    if (this.closed) return Promise.reject(new Error('closed'));
    return new Promise((_resolve, reject) => {
      this.#reject = reject;
    });
  }

  close(): Promise<void> {
    this.closed = true;
    this.#reject?.(new Error('closed'));
    this.#reject = undefined;
    return Promise.resolve();
  }
}

const deterministicPrimitives = (): RuntimePrimitives => {
  let call = 0;
  return {
    monotonicNowMs: () => 0,
    secureRandomBytes: (length) => new Uint8Array(length).fill(++call),
    sha256Hex: (input) => createHash('sha256').update(input).digest('hex'),
  };
};

const createFixture = async (): Promise<{
  readonly dispose: () => Promise<void>;
  readonly layout: RuntimeDirectoryLayout;
  readonly registry: RegistrationStore;
  readonly primitives: RuntimePrimitives;
}> => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'vlm-extension-lifecycle-'));
  const layout: RuntimeDirectoryLayout = {
    platform: 'win32',
    root,
    registrations: path.join(root, 'registrations'),
    quarantine: path.join(root, 'quarantine'),
  };
  await Promise.all([mkdir(layout.registrations), mkdir(layout.quarantine)]);
  const primitives = deterministicPrimitives();
  const registry = new RegistrationStore({
    layout,
    primitives,
    windowsSecurity: {
      ensureSecureRuntimeDirectory: () => ({
        path: root,
        currentUserSid: 'S-1-5-21-test',
        protectedDacl: true,
        reparsePoint: false,
      }),
      verifySecureRegistryFile: () => true,
    },
  });
  return {
    layout,
    registry,
    primitives,
    dispose: () => rm(root, { recursive: true, force: true }),
  };
};

const rootPath = (name: string): string => process.platform === 'win32'
  ? `D:\\workspace\\${name}`
  : `/workspace/${name}`;

const usableSnapshot = (names: readonly string[]): ExtensionWorkspaceSnapshot => ({
  workspaceName: names.join('+'),
  vscodeVersion: '1.125.0',
  folders: names.map((name) => ({
    name,
    uriScheme: 'file',
    lexicalAbsolutePath: rootPath(name),
  })),
});

test('activation publishes, unchanged refresh heartbeats, root changes rotate identity, and stop unregisters', async () => {
  const fixture = await createFixture();
  let now = 1_000;
  let snapshot = usableSnapshot(['app']);
  const servers: PendingServer[] = [];
  const service = new ExtensionRegistrationService({
    layout: fixture.layout,
    registry: fixture.registry,
    primitives: fixture.primitives,
    currentUserSid: 'S-1-5-21-test',
    heartbeatIntervalMs: 60_000,
    now: () => now,
    readWorkspace: () => snapshot,
    pathAccess: {
      entryType: () => Promise.resolve('directory'),
      realpath: (value) => Promise.resolve(value),
    },
    createTransport: () => {
      const server = new PendingServer();
      servers.push(server);
      return Promise.resolve(server);
    },
  });
  try {
    await service.start();
    const first = service.currentRecord();
    assert.equal(first?.kind, 'usable');
    assert.equal(first?.kind === 'usable' ? first.roots[0]?.alias : undefined, 'app');
    assert.deepEqual(await fixture.registry.scan(), [first]);

    now = 11_000;
    await service.refresh();
    const heartbeat = service.currentRecord();
    assert.equal(heartbeat?.workspaceId, first?.workspaceId);
    assert.equal(heartbeat?.workspaceGeneration, 1);
    assert.equal(heartbeat?.updatedAt, 11_000);

    snapshot = usableSnapshot(['app', 'lib']);
    now = 12_000;
    await service.refresh();
    const changed = service.currentRecord();
    assert.equal(changed?.kind, 'usable');
    assert.equal(changed?.workspaceGeneration, 2);
    assert.notEqual(changed?.workspaceId, first?.workspaceId);
    assert.notEqual(changed?.kind === 'usable' ? changed.authToken : undefined,
      first?.kind === 'usable' ? first.authToken : undefined);
    assert.equal(servers[0]?.closed, true);
    assert.deepEqual((await fixture.registry.scan()).map((record) => record.workspaceId), [changed?.workspaceId]);
  } finally {
    await service.stop();
    assert.deepEqual(await fixture.registry.scan(), []);
    await fixture.dispose();
  }
});

test('unusable and transport-failed states publish exact secret-free unavailable records and can recover', async () => {
  const fixture = await createFixture();
  let snapshot: ExtensionWorkspaceSnapshot = {
    workspaceName: 'Empty',
    vscodeVersion: '1.125.0',
    folders: [],
  };
  let failTransport = false;
  const service = new ExtensionRegistrationService({
    layout: fixture.layout,
    registry: fixture.registry,
    primitives: fixture.primitives,
    currentUserSid: 'S-1-5-21-test',
    heartbeatIntervalMs: 60_000,
    now: () => 10_000,
    readWorkspace: () => snapshot,
    pathAccess: {
      entryType: () => Promise.resolve('directory'),
      realpath: (value) => Promise.resolve(value),
    },
    createTransport: () => failTransport
      ? Promise.reject(new Error('bind failed'))
      : Promise.resolve(new PendingServer()),
  });
  try {
    await service.start();
    const unavailable = service.currentRecord();
    assert.equal(unavailable?.kind, 'unavailable');
    assert.equal(unavailable?.kind === 'unavailable' ? unavailable.reasonCode : undefined, 'no_workspace_folders');
    assert.equal('authToken' in (unavailable ?? {}), false);
    assert.equal('endpoint' in (unavailable ?? {}), false);
    assert.equal('roots' in (unavailable ?? {}), false);

    snapshot = usableSnapshot(['app']);
    failTransport = true;
    await service.refresh();
    const failed = service.currentRecord();
    assert.equal(failed?.kind, 'unavailable');
    assert.equal(failed?.kind === 'unavailable' ? failed.reasonCode : undefined, 'transport_start_failed');

    failTransport = false;
    await service.refresh();
    assert.equal(service.currentRecord()?.kind, 'usable');
    assert.equal(service.currentRecord()?.workspaceGeneration, 2);
  } finally {
    await service.stop();
    await fixture.dispose();
  }
});

test('started lifecycle accepts a real authenticated native pipe health request', {
  skip: process.platform !== 'win32',
  timeout: 5_000,
}, async () => {
  const fixture = await createFixture();
  let mutationWorkspace: { readonly workspaceId: string; readonly generation: number } | undefined;
  const service = new ExtensionRegistrationService({
    layout: fixture.layout,
    registry: fixture.registry,
    primitives: fixture.primitives,
    currentUserSid: 'S-1-5-21-test',
    heartbeatIntervalMs: 60_000,
    now: () => 10_000,
    readWorkspace: () => usableSnapshot(['native']),
    pathAccess: {
      entryType: () => Promise.resolve('directory'),
      realpath: (value) => Promise.resolve(value),
    },
    createTransport: (endpoint) => createExtensionTransportServer({
      endpoint,
    }),
    mutationHandler: (_context, workspace, request) => {
      mutationWorkspace = workspace;
      return Promise.resolve(request.method === 'mutation.test'
        ? { status: 'applied', changedFiles: ['src/a.ts'] }
        : undefined);
    },
    semanticHandler: (_context, request) => Promise.resolve(
      request.method === 'symbols.test'
        ? { status: 'completed', candidates: [] }
        : undefined,
    ),
  });
  let client: BridgeClientSession | undefined;
  try {
    await service.start();
    const record = service.currentRecord();
    assert.equal(record?.kind, 'usable');
    if (record?.kind !== 'usable') throw new Error('Expected a usable registration.');
    const raw = await connectNodeRawByte(record.endpoint.address, 2_000);
    const framed = await authenticateIpcClientConnection(raw, {
      instanceId: record.instanceId,
      workspaceId: record.workspaceId,
      workspaceGeneration: record.workspaceGeneration,
      token: record.authToken,
    }, fixture.primitives);
    client = new BridgeClientSession(framed, fixture.primitives);
    assert.deepEqual(await client.call('bridge.health', {}), { status: 'healthy' });
    assert.deepEqual(await client.call('symbols.test', {}), {
      status: 'completed',
      candidates: [],
    });
    assert.deepEqual(await client.call('mutation.test', {}), {
      status: 'applied',
      changedFiles: ['src/a.ts'],
    });
    assert.deepEqual(mutationWorkspace, {
      workspaceId: record.workspaceId,
      generation: record.workspaceGeneration,
    });
  } finally {
    await client?.close().catch(() => undefined);
    await service.stop();
    await fixture.dispose();
  }
});

test('native pipe accept loop resumes after all four connection slots were occupied', {
  skip: process.platform !== 'win32',
  timeout: 10_000,
}, async () => {
  const fixture = await createFixture();
  const service = new ExtensionRegistrationService({
    layout: fixture.layout,
    registry: fixture.registry,
    primitives: fixture.primitives,
    currentUserSid: 'S-1-5-21-test',
    heartbeatIntervalMs: 60_000,
    now: () => 10_000,
    readWorkspace: () => usableSnapshot(['capacity']),
    pathAccess: {
      entryType: () => Promise.resolve('directory'),
      realpath: (value) => Promise.resolve(value),
    },
    createTransport: (endpoint) => createExtensionTransportServer({
      endpoint,
    }),
  });
  const clients: BridgeClientSession[] = [];
  try {
    await service.start();
    const record = service.currentRecord();
    assert.equal(record?.kind, 'usable');
    if (record?.kind !== 'usable') throw new Error('Expected a usable registration.');

    const connectClient = async (): Promise<BridgeClientSession> => {
      let lastError: unknown;
      for (let attempt = 0; attempt < 20; attempt += 1) {
        try {
          const raw = await connectNodeRawByte(record.endpoint.address, 200);
          const framed = await authenticateIpcClientConnection(raw, {
            instanceId: record.instanceId,
            workspaceId: record.workspaceId,
            workspaceGeneration: record.workspaceGeneration,
            token: record.authToken,
          }, fixture.primitives);
          const client = new BridgeClientSession(framed, fixture.primitives);
          assert.deepEqual(await client.call('bridge.health', {}), { status: 'healthy' });
          return client;
        } catch (error) {
          lastError = error;
          await new Promise((resolve) => setTimeout(resolve, 20));
        }
      }
      throw lastError instanceof Error ? lastError : new Error('Pipe connection did not recover.');
    };

    for (let index = 0; index < 4; index += 1) {
      clients.push(await connectClient());
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
    await clients.shift()?.close();
    clients.push(await connectClient());
  } finally {
    await Promise.all(clients.map((client) => client.close().catch(() => undefined)));
    await service.stop();
    await fixture.dispose();
  }
});
