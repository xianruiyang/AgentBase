import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {
  BridgeTransportError,
  IPC_PROTOCOL_VERSION,
  REGISTRY_VERSION,
  RegistrationStore,
  createInstanceId,
  createRegistrationSecrets,
  createWorkspaceId,
  registrationComparison,
  type JsonObject,
  type RegistrationRecord,
  type RuntimeDirectoryLayout,
  type RuntimePrimitives,
  type UsableRegistrationRecord,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  WorkspaceRouter,
  WorkspaceRoutingError,
  type BridgeProbeSession,
} from './workspace-router.js';

const primitives = (): RuntimePrimitives => {
  let call = 0;
  return {
    monotonicNowMs: () => 0,
    secureRandomBytes: (length) => new Uint8Array(length).fill(++call),
    sha256Hex: (input) => createHash('sha256').update(input).digest('hex'),
  };
};

const fixture = async (): Promise<{
  readonly dispose: () => Promise<void>;
  readonly primitives: RuntimePrimitives;
  readonly registry: RegistrationStore;
}> => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'vlm-router-'));
  const layout: RuntimeDirectoryLayout = {
    platform: 'win32',
    root,
    registrations: path.join(root, 'registrations'),
    quarantine: path.join(root, 'quarantine'),
  };
  await Promise.all([mkdir(layout.registrations), mkdir(layout.quarantine)]);
  const source = primitives();
  return {
    primitives: source,
    registry: new RegistrationStore({
      layout,
      primitives: source,
      windowsSecurity: {
        ensureSecureRuntimeDirectory: () => ({
          path: root,
          currentUserSid: 'S-1-5-21-test',
          protectedDacl: true,
          reparsePoint: false,
        }),
        verifySecureRegistryFile: () => true,
      },
    }),
    dispose: () => rm(root, { recursive: true, force: true }),
  };
};

const usableRecord = (
  source: RuntimePrimitives,
  label: string,
  updatedAt: number,
): UsableRegistrationRecord => {
  const secrets = createRegistrationSecrets(source);
  return {
    registryVersion: REGISTRY_VERSION,
    protocolVersion: IPC_PROTOCOL_VERSION,
    kind: 'usable',
    instanceId: createInstanceId(source),
    workspaceId: createWorkspaceId(source),
    workspaceGeneration: 1,
    recordNonce: secrets.recordNonce,
    workspaceName: `Workspace ${label}`,
    extensionHostPid: 999_999,
    activationStartedAt: 1,
    publishedAt: 1,
    updatedAt,
    endpoint: { kind: 'namedPipe', address: `pipe-${label}` },
    authToken: secrets.authToken,
    rootsFingerprint: createHash('sha256').update(label).digest('hex'),
    roots: [{
      alias: label,
      folderName: label,
      folderIndex: 0,
      lexicalRoot: `D:\\${label}`,
      canonicalRoot: `D:\\${label}`,
      lexicalComparisonKey: `d:\\${label}`,
      canonicalComparisonKey: `d:\\${label}`,
    }],
    vscodeVersion: '1.125.0',
  };
};

const unavailableRecord = (
  source: RuntimePrimitives,
  updatedAt: number,
): RegistrationRecord => {
  const usable = usableRecord(source, 'unavailable-source', updatedAt);
  return {
    registryVersion: usable.registryVersion,
    protocolVersion: usable.protocolVersion,
    kind: 'unavailable',
    instanceId: usable.instanceId,
    workspaceId: usable.workspaceId,
    workspaceGeneration: usable.workspaceGeneration,
    recordNonce: usable.recordNonce,
    workspaceName: usable.workspaceName,
    extensionHostPid: usable.extensionHostPid,
    activationStartedAt: usable.activationStartedAt,
    publishedAt: usable.publishedAt,
    updatedAt: usable.updatedAt,
    reasonCode: 'cross_host_unavailable',
  };
};

class FakeSession implements BridgeProbeSession {
  readonly #result: unknown | ((method: string, params: JsonObject) => unknown);
  readonly callOptions: Array<Parameters<BridgeProbeSession['call']>[2]> = [];
  calls = 0;
  closed = false;

  constructor(result: unknown | ((method: string, params: JsonObject) => unknown)) {
    this.#result = result;
  }

  call(
    method: string,
    params: JsonObject,
    options?: Parameters<BridgeProbeSession['call']>[2],
  ): Promise<unknown> {
    this.calls += 1;
    this.callOptions.push(options);
    return Promise.resolve(typeof this.#result === 'function'
      ? this.#result(method, params)
      : this.#result);
  }

  close(): Promise<void> {
    this.closed = true;
    return Promise.resolve();
  }
}

test('mutation and command routes reuse one authenticated session and invalidate it on transport failure', async () => {
  const state = await fixture();
  const now = 1_000_000;
  const record = usableRecord(state.primitives, 'mutation-reuse', now);
  const sessions: FakeSession[] = [];
  const router = new WorkspaceRouter({
    registry: state.registry,
    primitives: state.primitives,
    now: () => now,
    connect: () => {
      const session = new FakeSession((method: string) => {
        if (method === 'break') {
          throw new BridgeTransportError('disconnected', 'test disconnect', 'notStarted');
        }
        return { status: 'completed' };
      });
      sessions.push(session);
      return Promise.resolve(session);
    },
  });
  try {
    await state.registry.publish(record);
    for (let index = 0; index < 6; index += 1) {
      const route = await router.connectWorkspaceBinding(record.workspaceId);
      assert.deepEqual(await route.session.call('mutation.test', {}), { status: 'completed' });
      await route.session.close();
    }
    assert.equal(sessions.length, 1);
    assert.equal(sessions[0]?.calls, 6);
    assert.equal(sessions[0]?.closed, false);

    const exact = await router.connectWorkspaceRoute({
      workspaceId: record.workspaceId,
      generation: record.workspaceGeneration,
    });
    await assert.rejects(exact.call('break', {}), BridgeTransportError);
    assert.equal(sessions[0]?.closed, true);

    const recovered = await router.connectWorkspaceBinding(record.workspaceId);
    assert.deepEqual(await recovered.session.call('mutation.recovered', {}), { status: 'completed' });
    assert.equal(sessions.length, 2);
    await router.close();
    assert.equal(sessions[1]?.closed, true);
  } finally {
    await router.close();
    await state.dispose();
  }
});

test('discovery reuses an existing semantic session instead of consuming another Extension slot', async () => {
  const state = await fixture();
  const now = 1_000_000;
  const record = usableRecord(state.primitives, 'probe-reuse', now);
  const sessions: FakeSession[] = [];
  const router = new WorkspaceRouter({
    registry: state.registry,
    primitives: state.primitives,
    now: () => now,
    connect: () => {
      const session = new FakeSession((method: string) => method === 'symbols.workspace'
        ? { status: 'completed', candidates: [] }
        : { status: 'healthy' });
      sessions.push(session);
      return Promise.resolve(session);
    },
  });
  try {
    await state.registry.publish(record);
    const symbols = await router.workspaceSymbols({
      workspaceId: record.workspaceId,
      query: 'probe',
    });
    assert.equal(symbols.ok, true);
    const listed = await router.listWorkspaces({});
    assert.equal(listed.ok, true);
    assert.equal(sessions.length, 1);
    assert.equal(sessions[0]?.calls, 2);
    assert.equal(sessions[0]?.closed, false);
    await router.close();
    assert.equal(sessions[0]?.closed, true);
  } finally {
    await router.close();
    await state.dispose();
  }
});

test('a failed pooled discovery probe evicts the shared session before the next routed request', async () => {
  const state = await fixture();
  const now = 1_000_000;
  const record = usableRecord(state.primitives, 'probe-eviction', now);
  const sessions: FakeSession[] = [];
  const router = new WorkspaceRouter({
    registry: state.registry,
    primitives: state.primitives,
    now: () => now,
    connect: () => {
      const sessionIndex = sessions.length;
      const session = new FakeSession((method: string) => {
        if (sessionIndex === 0 && method === 'bridge.health') {
          throw new BridgeTransportError('disconnected', 'probe failed', 'unknown');
        }
        return method === 'symbols.workspace'
          ? { status: 'completed', candidates: [] }
          : { status: 'healthy' };
      });
      sessions.push(session);
      return Promise.resolve(session);
    },
  });
  try {
    await state.registry.publish(record);
    assert.equal((await router.workspaceSymbols({
      workspaceId: record.workspaceId,
      query: 'first',
    })).ok, true);
    const listed = await router.listWorkspaces({});
    assert.equal(listed.ok && listed.data.available, 0);
    assert.equal(sessions[0]?.closed, true);
    assert.equal((await router.workspaceSymbols({
      workspaceId: record.workspaceId,
      query: 'recovered',
    })).ok, true);
    assert.equal(sessions.length, 2);
  } finally {
    await router.close();
    await state.dispose();
  }
});

test('discovery returns only fresh authenticated workspaces and exposes no routing internals', async () => {
  const state = await fixture();
  const now = 1_000_000;
  const healthy = usableRecord(state.primitives, 'healthy', now);
  const stale = usableRecord(state.primitives, 'stale', now - 60_001);
  const timedOut = usableRecord(state.primitives, 'timeout', now);
  const abandoned = usableRecord(state.primitives, 'dead', now - 300_000);
  const unavailable = unavailableRecord(state.primitives, now);
  try {
    for (const record of [healthy, stale, timedOut, abandoned, unavailable]) {
      await state.registry.publish(record);
    }
    const router = new WorkspaceRouter({
      registry: state.registry,
      primitives: state.primitives,
      now: () => now,
      isPidDefinitelyDead: () => Promise.resolve(true),
      connect: (record) => {
        if (record.endpoint.address.includes('timeout')) {
          return Promise.reject(new BridgeTransportError('timeout', 'timeout', 'notStarted'));
        }
        if (record.endpoint.address.includes('dead')) {
          return Promise.reject(new BridgeTransportError('disconnected', 'dead', 'notStarted'));
        }
        return Promise.resolve(new FakeSession({ status: 'healthy' }));
      },
    });

    const listed = await router.listWorkspaces({});
    assert.equal(listed.ok, true);
    if (listed.ok) {
      assert.deepEqual(listed.data.results, [{
        workspaceId: healthy.workspaceId,
        name: healthy.workspaceName,
        roots: ['healthy'],
      }]);
      const publicJson = JSON.stringify(listed);
      for (const forbidden of ['instanceId', 'endpoint', 'authToken', 'recordNonce', 'extensionHostPid', 'canonicalRoot']) {
        assert.equal(publicJson.includes(forbidden), false);
      }
    }
    assert.equal(await state.registry.read(abandoned.instanceId), undefined);

    const health = await router.healthCheck({});
    assert.equal(health.ok, true);
    if (health.ok) {
      const byTarget = new Map(health.data.results.map((result) => [result.target, result]));
      assert.equal(byTarget.get('server')?.status, 'healthy');
      assert.equal(byTarget.get(`workspace:${healthy.workspaceId}`)?.status, 'healthy');
      assert.equal(byTarget.get(`workspace:${stale.workspaceId}`)?.status, 'degraded');
      assert.equal(byTarget.get(`workspace:${timedOut.workspaceId}`)?.status, 'timedOut');
      assert.equal(byTarget.get(`workspace:${unavailable.workspaceId}`)?.status, 'unavailable');
    }
  } finally {
    await state.dispose();
  }
});

test('each discovery rescans records so restart routes recover without stale cache', async () => {
  const state = await fixture();
  const now = 1_000_000;
  const first = usableRecord(state.primitives, 'first', now);
  const second = usableRecord(state.primitives, 'second', now);
  const sessions: FakeSession[] = [];
  const router = new WorkspaceRouter({
    registry: state.registry,
    primitives: state.primitives,
    now: () => now,
    connect: () => {
      const session = new FakeSession({ status: 'healthy' });
      sessions.push(session);
      return Promise.resolve(session);
    },
  });
  try {
    await state.registry.publish(first);
    const firstList = await router.listWorkspaces({});
    assert.equal(firstList.ok && firstList.data.results[0]?.workspaceId, first.workspaceId);
    await state.registry.comparisonAndDelete(registrationComparison(first));
    await state.registry.publish(second);
    const secondList = await router.listWorkspaces({});
    assert.equal(secondList.ok && secondList.data.results[0]?.workspaceId, second.workspaceId);
    assert.equal(sessions.every((session) => session.closed), true);

    const route = await router.connectWorkspace(second.workspaceId);
    assert.equal(route instanceof FakeSession, true);
    await route.close();
    const exactRoute = await router.connectWorkspaceRoute({
      workspaceId: second.workspaceId,
      generation: second.workspaceGeneration,
    });
    await exactRoute.close();
    await assert.rejects(
      router.connectWorkspaceRoute({
        workspaceId: second.workspaceId,
        generation: second.workspaceGeneration + 1,
      }),
      (error: unknown) => error instanceof WorkspaceRoutingError && error.reason === 'notFound',
    );
    await assert.rejects(router.connectWorkspace(first.workspaceId), (error: unknown) =>
      error instanceof WorkspaceRoutingError && error.reason === 'notFound');
  } finally {
    await state.dispose();
  }
});

test('multi-workspace discovery keeps distinct stable routes and root aliases', async () => {
  const state = await fixture();
  const now = 1_000_000;
  const alpha = usableRecord(state.primitives, 'alpha', now);
  const beta = usableRecord(state.primitives, 'beta', now);
  const router = new WorkspaceRouter({
    registry: state.registry,
    primitives: state.primitives,
    now: () => now,
    connect: () => Promise.resolve(new FakeSession({ status: 'healthy' })),
  });
  try {
    await state.registry.publish(alpha);
    await state.registry.publish(beta);
    const first = await router.listWorkspaces({});
    const second = await router.listWorkspaces({});
    assert.equal(first.ok, true);
    assert.deepEqual(second, first);
    if (first.ok) {
      assert.equal(first.data.available, 2);
      assert.equal(new Set(first.data.results.map((workspace) => workspace.workspaceId)).size, 2);
      assert.deepEqual(
        new Set(first.data.results.flatMap((workspace) => workspace.roots)),
        new Set(['alpha', 'beta']),
      );
    }
    for (const record of [alpha, beta]) {
      const route = await router.connectWorkspace(record.workspaceId);
      await route.close();
    }
  } finally {
    await state.dispose();
  }
});

test('health filtering and result windows remain deterministic', async () => {
  const state = await fixture();
  const now = 1_000_000;
  const record = usableRecord(state.primitives, 'selected', now);
  try {
    await state.registry.publish(record);
    const router = new WorkspaceRouter({
      registry: state.registry,
      primitives: state.primitives,
      now: () => now,
      connect: () => Promise.resolve(new FakeSession({ status: 'healthy' })),
    });
    const selected = await router.healthCheck({ workspaceId: record.workspaceId, resultStart: 2, resultEnd: 2 });
    assert.equal(selected.ok, true);
    if (selected.ok) {
      assert.equal(selected.data.available, 2);
      assert.deepEqual(selected.data.results.map((result) => result.target), [`workspace:${record.workspaceId}`]);
    }
    const missing = await router.healthCheck({ workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA' });
    assert.equal(missing.ok, true);
    if (missing.ok) {
      assert.equal(missing.data.results[1]?.status, 'unavailable');
      assert.deepEqual(missing.data.results[1]?.issues, ['workspace_not_found']);
    }
  } finally {
    await state.dispose();
  }
});

test('symbol routes apply public filtering, stable ordering, depth, context, and one final window', async () => {
  const state = await fixture();
  const now = 1_000_000;
  const record = usableRecord(state.primitives, 'symbols', now);
  const calls: Array<{ readonly method: string; readonly params: JsonObject }> = [];
  try {
    await state.registry.publish(record);
    const router = new WorkspaceRouter({
      registry: state.registry,
      primitives: state.primitives,
      now: () => now,
      connect: () => Promise.resolve(new FakeSession((method: string, params: JsonObject) => {
        calls.push({ method, params });
        if (method === 'symbols.workspace') {
          if (params.query === 'Timeout') return {
            status: 'timedOut',
            provider: { status: 'timedOut', elapsedMs: 90_000, attempts: 2 },
          };
          return {
            status: 'completed',
            provider: { status: 'completed', elapsedMs: 17, attempts: 1 },
            candidates: [
              { name: 'widgetFactory', kind: 'class', file: 'src/factory.ts', line: 3, column: 1 },
              { name: 'Widget', kind: 'class', file: 'src/widget.ts', line: 2, column: 7 },
              { name: 'Widget', kind: 'class', file: 'src/widget.ts', line: 2, column: 7 },
              { name: 'Widget', kind: 'variable', file: 'src/variable.ts', line: 1, column: 1 },
              { name: 'AWidget', kind: 'class', file: 'src/widget.test.ts', line: 1, column: 1 },
            ],
          };
        }
        if (method === 'symbols.document') {
          return {
            status: 'completed',
            provider: { status: 'completed', elapsedMs: 23, attempts: 1 },
            candidates: [
              { kind: 'class', path: ['Widget'], line: 1, column: 7, range: { startLine: 1, startColumn: 1, endLine: 5, endColumn: 2 }, snippet: 'class Widget {' },
              { kind: 'method', path: ['Widget', 'run'], line: 2, column: 3, range: { startLine: 2, startColumn: 3, endLine: 2, endColumn: 11 }, snippet: '  run() {}' },
              { kind: 'field', path: ['Widget', 'value'], line: 3, column: 3 },
              { kind: 'method', path: ['Widget', 'Inner', 'deep'], line: 4, column: 5 },
            ],
          };
        }
        throw new Error('Unexpected bridge method.');
      })),
    });

    const workspace = await router.workspaceSymbols({
      workspaceId: record.workspaceId,
      query: 'Widget',
      kinds: ['class'],
      includeGlobs: ['src/**/*.ts'],
      excludeGlobs: ['**/*.test.ts'],
      contextLines: 1,
      resultStart: 1,
      resultEnd: 2,
    });
    assert.equal(workspace.ok, true);
    if (workspace.ok) {
      assert.equal(workspace.data.available, 2);
      assert.deepEqual(workspace.data.results.map(({ name }) => name), ['Widget', 'widgetFactory']);
      assert.deepEqual(workspace.data.provider, { status: 'completed', elapsedMs: 17, attempts: 1 });
    }
    assert.deepEqual(calls[0], {
      method: 'symbols.workspace',
      params: { query: 'Widget', contextLines: 1 },
    });

    const document = await router.documentSymbols({
      workspaceId: record.workspaceId,
      file: 'src/widget.ts',
      kinds: ['class', 'method'],
      maxDepth: 1,
      nameEquals: 'run',
      pathEquals: ['Widget', 'run'],
      includeRange: true,
      contextLines: 1,
      resultStart: 1,
      resultEnd: 1,
    });
    assert.equal(document.ok, true);
    if (document.ok) {
      assert.equal(document.data.available, 1);
      assert.deepEqual(document.data.results, [{
        kind: 'method',
        path: ['Widget', 'run'],
        line: 2,
        column: 3,
        range: { startLine: 2, startColumn: 3, endLine: 2, endColumn: 11 },
        snippet: '  run() {}',
      }]);
      assert.deepEqual(document.data.provider, { status: 'completed', elapsedMs: 23, attempts: 1 });
    }
    assert.deepEqual(calls[1], {
      method: 'symbols.document',
      params: { file: 'src/widget.ts', contextLines: 1 },
    });

    const timedOut = await router.workspaceSymbols({
      workspaceId: record.workspaceId,
      query: 'Timeout',
    });
    assert.equal(timedOut.ok, false);
    if (!timedOut.ok) {
      assert.equal(timedOut.error.code, 'PROVIDER_TIMEOUT');
      assert.deepEqual(timedOut.error.provider, {
        status: 'timedOut',
        elapsedMs: 90_000,
        attempts: 2,
      });
    }
  } finally {
    await state.dispose();
  }
});

test('a dispatched semantic request is not replayed after disconnect and the next request reconnects', async () => {
  const state = await fixture();
  const now = 1_000_000;
  const record = usableRecord(state.primitives, 'restart', now);
  let connectCount = 0;
  let firstSessionCalls = 0;
  const sessions: FakeSession[] = [];
  try {
    await state.registry.publish(record);
    const router = new WorkspaceRouter({
      registry: state.registry,
      primitives: state.primitives,
      now: () => now,
      connect: () => {
        connectCount += 1;
        const session = connectCount === 1
          ? new FakeSession((method: string) => {
              assert.equal(method, 'symbols.workspace');
              firstSessionCalls += 1;
              if (firstSessionCalls === 2) {
                throw new BridgeTransportError(
                  'disconnected',
                  'Extension Host fixture stopped.',
                  'unknown',
                );
              }
              return {
                status: 'completed',
                candidates: [{ name: 'BeforeRestart', kind: 'class', file: 'src/fixture.ts', line: 1, column: 1 }],
              };
            })
          : new FakeSession({
              status: 'completed',
              candidates: [{ name: 'AfterRestart', kind: 'class', file: 'src/fixture.ts', line: 2, column: 1 }],
            });
        sessions.push(session);
        return Promise.resolve(session);
      },
    });

    const beforeRestart = await router.workspaceSymbols({
      workspaceId: record.workspaceId,
      query: 'Fixture',
    });
    assert.equal(beforeRestart.ok, true);

    const interrupted = await router.workspaceSymbols({
      workspaceId: record.workspaceId,
      query: 'Fixture',
    });
    assert.equal(interrupted.ok, false);
    if (!interrupted.ok) assert.equal(interrupted.error.code, 'WORKSPACE_DISCONNECTED');
    assert.equal(connectCount, 1);
    assert.equal(firstSessionCalls, 2);
    assert.equal(sessions[0]?.closed, true);

    const recovered = await router.workspaceSymbols({
      workspaceId: record.workspaceId,
      query: 'Fixture',
    });
    assert.equal(recovered.ok, true);
    if (recovered.ok) assert.equal(recovered.data.results[0]?.name, 'AfterRestart');
    assert.equal(connectCount, 2);
    assert.equal(firstSessionCalls, 2);
    await router.close();
  } finally {
    await state.dispose();
  }
});

test('a remote bridge rejection is an internal error and does not discard the healthy session', async () => {
  const state = await fixture();
  const now = 1_000_000;
  const record = usableRecord(state.primitives, 'remote-rejection', now);
  let connectCount = 0;
  let calls = 0;
  let session: FakeSession | undefined;
  try {
    await state.registry.publish(record);
    const router = new WorkspaceRouter({
      registry: state.registry,
      primitives: state.primitives,
      now: () => now,
      connect: () => {
        connectCount += 1;
        session = new FakeSession(() => {
          calls += 1;
          if (calls === 1) {
            throw new BridgeTransportError(
              'remote',
              'Bridge fixture rejected the request.',
              'unknown',
              'BRIDGE_REQUEST_FAILED',
            );
          }
          return {
            status: 'completed',
            candidates: [{ name: 'Recovered', kind: 'class', file: 'src/fixture.ts', line: 1, column: 1 }],
          };
        });
        return Promise.resolve(session);
      },
    });

    const rejected = await router.workspaceSymbols({
      workspaceId: record.workspaceId,
      query: 'Fixture',
    });
    assert.equal(rejected.ok, false);
    if (!rejected.ok) assert.equal(rejected.error.code, 'INTERNAL_ERROR');

    const recovered = await router.workspaceSymbols({
      workspaceId: record.workspaceId,
      query: 'Fixture',
    });
    assert.equal(recovered.ok, true);
    assert.equal(connectCount, 1);
    assert.equal(calls, 2);
    assert.equal(session?.closed, false);
    await router.close();
  } finally {
    await state.dispose();
  }
});

test('a timed-out semantic request does not close the healthy shared session', async () => {
  const state = await fixture();
  const now = 1_000_000;
  const record = usableRecord(state.primitives, 'semantic-timeout', now);
  let connectCount = 0;
  let callCount = 0;
  const session = new FakeSession(() => {
    callCount += 1;
    if (callCount === 1) {
      throw new BridgeTransportError('timeout', 'Provider request timed out.', 'unknown');
    }
    return {
      status: 'completed',
      candidates: [{ name: 'Recovered', kind: 'class', file: 'src/recovered.ts', line: 1, column: 1 }],
    };
  });
  try {
    await state.registry.publish(record);
    const router = new WorkspaceRouter({
      registry: state.registry,
      primitives: state.primitives,
      now: () => now,
      connect: () => {
        connectCount += 1;
        return Promise.resolve(session);
      },
    });

    const timedOut = await router.workspaceSymbols({
      workspaceId: record.workspaceId,
      query: 'Recovered',
    });
    assert.equal(timedOut.ok, false);
    if (!timedOut.ok) assert.equal(timedOut.error.code, 'PROVIDER_TIMEOUT');
    assert.equal(session.closed, false);

    const recovered = await router.workspaceSymbols({
      workspaceId: record.workspaceId,
      query: 'Recovered',
    });
    assert.equal(recovered.ok, true);
    if (recovered.ok) assert.equal(recovered.data.results[0]?.name, 'Recovered');
    assert.equal(connectCount, 1);
    assert.equal(callCount, 2);
    assert.deepEqual(
      session.callOptions.map((options) => options?.maximumTimeoutMs),
      [305_000, 305_000],
    );
    await router.close();
    assert.equal(session.closed, true);
  } finally {
    await state.dispose();
  }
});

test('symbol info defaults to definition and applies one fixed-group result window', async () => {
  const state = await fixture();
  const now = 1_000_000;
  const record = usableRecord(state.primitives, 'symbol-info', now);
  const calls: Array<{ readonly method: string; readonly params: JsonObject }> = [];
  try {
    await state.registry.publish(record);
    const router = new WorkspaceRouter({
      registry: state.registry,
      primitives: state.primitives,
      now: () => now,
      connect: () => Promise.resolve(new FakeSession((method: string, params: JsonObject) => {
        calls.push({ method, params });
        if (method !== 'symbol.info') throw new Error('Unexpected bridge method.');
        if (params.line === 99) return { status: 'positionOutOfRange' };
        if (Array.isArray(params.include) && params.include.length === 1) {
          return {
            status: 'completed',
            candidates: [{
              type: 'definition',
              file: 'src/widget.ts',
              line: 2,
              column: 7,
            }],
          };
        }
        return {
          status: 'completed',
          candidates: [
            { type: 'signatureHelp', label: 'z(value: number)', activeSignature: false },
            { type: 'definition', file: 'src/widget.ts', line: 2, column: 7 },
            { type: 'hover', text: 'Widget docs' },
            { type: 'signatureHelp', label: 'a()', activeSignature: true },
            { type: 'declaration', file: 'src/widget.ts', line: 1, column: 14 },
            { type: 'definition', file: 'src/widget.ts', line: 2, column: 7 },
          ],
          warnings: ['implementation_unavailable'],
        };
      })),
    });

    const defaultResult = await router.symbolInfo({
      workspaceId: record.workspaceId,
      file: 'src/widget.ts',
      line: 2,
      column: 7,
    });
    assert.equal(defaultResult.ok, true);
    if (defaultResult.ok) {
      assert.deepEqual(defaultResult.data.results, [{
        type: 'definition',
        file: 'src/widget.ts',
        line: 2,
        column: 7,
      }]);
    }
    assert.deepEqual(calls[0], {
      method: 'symbol.info',
      params: {
        file: 'src/widget.ts',
        line: 2,
        column: 7,
        include: ['definition'],
        contextLines: 0,
      },
    });

    const windowed = await router.symbolInfo({
      workspaceId: record.workspaceId,
      file: 'src/widget.ts',
      line: 2,
      column: 7,
      include: ['signatureHelp', 'implementation', 'hover', 'definition', 'declaration'],
      resultStart: 2,
      resultEnd: 4,
    });
    assert.equal(windowed.ok, true);
    if (windowed.ok) {
      assert.equal(windowed.data.available, 5);
      assert.deepEqual(windowed.data.results, [
        { type: 'declaration', file: 'src/widget.ts', line: 1, column: 14 },
        { type: 'definition', file: 'src/widget.ts', line: 2, column: 7 },
        { type: 'signatureHelp', label: 'a()' },
      ]);
      assert.deepEqual(windowed.data.warnings, ['implementation_unavailable']);
      assert.equal('activeSignature' in (windowed.data.results[2] as object), false);
    }

    const outOfRange = await router.symbolInfo({
      workspaceId: record.workspaceId,
      file: 'src/widget.ts',
      line: 99,
      column: 1,
    });
    assert.equal(outOfRange.ok, false);
    if (!outOfRange.ok) assert.equal(outOfRange.error.code, 'POSITION_OUT_OF_RANGE');
  } finally {
    await state.dispose();
  }
});

test('symbol info path filters remove duplicate workspace copies without hiding non-location results', async () => {
  const state = await fixture();
  const now = 1_000_000;
  const record = usableRecord(state.primitives, 'symbol-info-filter', now);
  try {
    await state.registry.publish(record);
    const router = new WorkspaceRouter({
      registry: state.registry,
      primitives: state.primitives,
      now: () => now,
      connect: () => Promise.resolve(new FakeSession({
        status: 'completed',
        candidates: [
          { type: 'hover', text: 'Widget docs' },
          { type: 'definition', file: 'src/widget.ts', line: 2, column: 7 },
          {
            type: 'definition',
            file: 'Saved/CodexValidation/widget.ts',
            line: 2,
            column: 7,
          },
        ],
      })),
    });

    const filtered = await router.symbolInfo({
      workspaceId: record.workspaceId,
      file: 'src/widget.ts',
      line: 2,
      column: 7,
      include: ['hover', 'definition'],
      excludeGlobs: ['Saved/**'],
    });
    assert.equal(filtered.ok, true);
    if (filtered.ok) {
      assert.equal(filtered.data.available, 2);
      assert.equal(filtered.data.results.some((result) => result.type === 'hover'), true);
      assert.equal(filtered.data.results.some((result) =>
        result.type === 'definition' && result.file === 'src/widget.ts'), true);
      assert.equal(JSON.stringify(filtered.data.results).includes('CodexValidation'), false);
    }
    await router.close();
  } finally {
    await state.dispose();
  }
});

test('capability route validates the requested set, sorts canonically, and applies one window', async () => {
  const state = await fixture();
  const now = 1_000_000;
  const record = usableRecord(state.primitives, 'capabilities', now);
  const calls: Array<{ readonly method: string; readonly params: JsonObject }> = [];
  const session = new FakeSession((method: string, params: JsonObject) => {
    calls.push({ method, params });
    return {
      status: 'completed',
      candidates: [
        { name: 'diagnostics', status: 'available' },
        { name: 'documentSymbols', status: 'available' },
        { name: 'definition', status: 'unknown', reason: 'probe_returned_no_evidence' },
      ],
    };
  });
  try {
    await state.registry.publish(record);
    const router = new WorkspaceRouter({
      registry: state.registry,
      primitives: state.primitives,
      now: () => now,
      connect: () => Promise.resolve(session),
    });
    const response = await router.getCapabilities({
      workspaceId: record.workspaceId,
      file: 'src/widget.ts',
      capabilities: ['diagnostics', 'definition', 'documentSymbols'],
      resultStart: 2,
      resultEnd: 3,
    });
    assert.deepEqual(response, {
      ok: true,
      data: {
        results: [
          { name: 'definition', status: 'unknown', reason: 'probe_returned_no_evidence' },
          { name: 'diagnostics', status: 'available' },
        ],
        available: 3,
      },
    });
    assert.deepEqual(calls, [{
      method: 'capabilities.probe',
      params: {
        file: 'src/widget.ts',
        capabilities: ['diagnostics', 'definition', 'documentSymbols'],
      },
    }]);
    await router.close();
    assert.equal(session.closed, true);
  } finally {
    await state.dispose();
  }
});

test('call hierarchy route traverses breadth-first, preserves call-site frames, and stops cycles', async () => {
  const state = await fixture();
  const now = 1_000_000;
  const record = usableRecord(state.primitives, 'call-hierarchy', now);
  const calls: Array<{ readonly method: string; readonly params: JsonObject }> = [];
  const hierarchySymbol = (name: string, line: number) => ({
    name, kind: 'function', file: 'src/hierarchy.ts', line, column: 17,
  });
  let prepareCount = 0;
  const session = new FakeSession((method: string, params: JsonObject) => {
    calls.push({ method, params });
    if (method === 'hierarchy.prepare') {
      prepareCount += 1;
      return {
        status: 'completed', traversalId: `h${prepareCount}`,
        nodes: [{ nodeId: 'n1', symbol: hierarchySymbol('middleCall', 4) }],
      };
    }
    if (method === 'hierarchy.release') return { status: 'completed' };
    if (method !== 'hierarchy.expand') return { status: 'failed' };
    if (params.direction === 'incoming' && params.nodeId === 'n1') {
      return {
        status: 'completed',
        nodes: [{
          nodeId: 'n2', symbol: hierarchySymbol('rootCall', 7),
          callSites: [{ startLine: 8, startColumn: 10, endLine: 8, endColumn: 20 }],
        }],
      };
    }
    if (params.direction === 'incoming' && params.nodeId === 'n2') {
      return {
        status: 'completed',
        nodes: [{
          nodeId: 'n3', symbol: hierarchySymbol('middleCall', 4),
          callSites: [{ startLine: 4, startColumn: 17, endLine: 4, endColumn: 27 }],
        }],
      };
    }
    if (params.direction === 'outgoing' && params.nodeId === 'n1') {
      return {
        status: 'completed',
        nodes: [{
          nodeId: 'n4', symbol: hierarchySymbol('leafCall', 1),
          callSites: [{ startLine: 5, startColumn: 10, endLine: 5, endColumn: 18 }],
        }],
      };
    }
    if (params.direction === 'outgoing' && params.nodeId === 'n4') {
      return {
        status: 'completed',
        nodes: [{
          nodeId: 'n5', symbol: hierarchySymbol('middleCall', 4),
          callSites: [{ startLine: 1, startColumn: 17, endLine: 1, endColumn: 27 }],
        }],
      };
    }
    return { status: 'completed', nodes: [] };
  });
  try {
    await state.registry.publish(record);
    const router = new WorkspaceRouter({
      registry: state.registry,
      primitives: state.primitives,
      now: () => now,
      connect: () => Promise.resolve(session),
    });
    const both = await router.getCallHierarchy({
      workspaceId: record.workspaceId,
      file: 'src/hierarchy.ts',
      line: 4,
      column: 17,
      direction: 'both',
      maxDepth: 2,
      resultStart: 2,
      resultEnd: 4,
    });
    assert.equal(both.ok, true);
    if (both.ok) {
      assert.equal(both.data.available, 5);
      assert.deepEqual(both.data.results.map((entry) => [
        entry.depth, entry.relation, entry.symbol.name, entry.parent?.name,
      ]), [
        [1, 'incoming', 'rootCall', 'middleCall'],
        [1, 'outgoing', 'leafCall', 'middleCall'],
        [2, 'incoming', 'middleCall', 'rootCall'],
      ]);
      assert.deepEqual(both.data.results[0]?.callSites, [
        { startLine: 8, startColumn: 10, endLine: 8, endColumn: 20 },
      ]);
    }

    const incoming = await router.getCallHierarchy({
      workspaceId: record.workspaceId,
      file: 'src/hierarchy.ts',
      line: 4,
      column: 17,
      direction: 'incoming',
      maxDepth: 5,
    });
    assert.equal(incoming.ok, true);
    if (incoming.ok) {
      assert.equal(incoming.data.available, 3);
      assert.deepEqual(incoming.data.results.map((entry) => entry.relation), [
        'root', 'incoming', 'incoming',
      ]);
    }
    const outgoing = await router.getCallHierarchy({
      workspaceId: record.workspaceId,
      file: 'src/hierarchy.ts',
      line: 4,
      column: 17,
      direction: 'outgoing',
      maxDepth: 1,
    });
    assert.equal(outgoing.ok, true);
    if (outgoing.ok) {
      assert.deepEqual(outgoing.data.results.map((entry) => entry.relation), ['root', 'outgoing']);
    }
    assert.equal(calls.filter((call) => call.method === 'hierarchy.release').length, 3);
    assert.equal(calls.some((call) => call.method === 'hierarchy.expand' &&
      call.params.nodeId === 'n3'), false);
    await router.close();
  } finally {
    await state.dispose();
  }
});

test('type hierarchy route handles both directions, depth zero, and stable parent relations', async () => {
  const state = await fixture();
  const now = 1_000_000;
  const record = usableRecord(state.primitives, 'type-hierarchy', now);
  const calls: Array<{ readonly method: string; readonly params: JsonObject }> = [];
  const hierarchySymbol = (name: string, line: number) => ({
    name, kind: 'class', file: 'src/hierarchy.ts', line, column: 14,
  });
  let prepareCount = 0;
  const session = new FakeSession((method: string, params: JsonObject) => {
    calls.push({ method, params });
    if (method === 'hierarchy.prepare') {
      prepareCount += 1;
      return {
        status: 'completed', traversalId: `h${prepareCount}`,
        nodes: [{ nodeId: 'n1', symbol: hierarchySymbol('MiddleType', 11) }],
      };
    }
    if (method === 'hierarchy.release') return { status: 'completed' };
    if (method !== 'hierarchy.expand') return { status: 'failed' };
    if (params.direction === 'supertype' && params.nodeId === 'n1') {
      return { status: 'completed', nodes: [{ nodeId: 'n2', symbol: hierarchySymbol('BaseType', 10) }] };
    }
    if (params.direction === 'subtype' && params.nodeId === 'n1') {
      return { status: 'completed', nodes: [{ nodeId: 'n3', symbol: hierarchySymbol('LeafType', 12) }] };
    }
    if ((params.direction === 'supertype' && params.nodeId === 'n2') ||
        (params.direction === 'subtype' && params.nodeId === 'n3')) {
      return { status: 'completed', nodes: [{ nodeId: 'n4', symbol: hierarchySymbol('MiddleType', 11) }] };
    }
    return { status: 'completed', nodes: [] };
  });
  try {
    await state.registry.publish(record);
    const router = new WorkspaceRouter({
      registry: state.registry,
      primitives: state.primitives,
      now: () => now,
      connect: () => Promise.resolve(session),
    });
    const both = await router.getTypeHierarchy({
      workspaceId: record.workspaceId,
      file: 'src/hierarchy.ts',
      line: 11,
      column: 14,
      direction: 'both',
      maxDepth: 2,
    });
    assert.equal(both.ok, true);
    if (both.ok) {
      assert.equal(both.data.available, 5);
      assert.deepEqual(both.data.results.map((entry) => [
        entry.depth, entry.relation, entry.symbol.name, entry.parent?.name,
      ]), [
        [0, 'root', 'MiddleType', undefined],
        [1, 'supertype', 'BaseType', 'MiddleType'],
        [1, 'subtype', 'LeafType', 'MiddleType'],
        [2, 'supertype', 'MiddleType', 'BaseType'],
        [2, 'subtype', 'MiddleType', 'LeafType'],
      ]);
    }

    const beforeRootsOnly = calls.length;
    const rootsOnly = await router.getTypeHierarchy({
      workspaceId: record.workspaceId,
      file: 'src/hierarchy.ts',
      line: 11,
      column: 14,
      direction: 'supertypes',
      maxDepth: 0,
    });
    assert.equal(rootsOnly.ok, true);
    if (rootsOnly.ok) {
      assert.equal(rootsOnly.data.available, 1);
      assert.deepEqual(rootsOnly.data.results.map((entry) => entry.relation), ['root']);
    }
    assert.equal(calls.slice(beforeRootsOnly).some((call) => call.method === 'hierarchy.expand'), false);

    const supertypes = await router.getTypeHierarchy({
      workspaceId: record.workspaceId,
      file: 'src/hierarchy.ts',
      line: 11,
      column: 14,
      direction: 'supertypes',
      maxDepth: 1,
    });
    assert.equal(supertypes.ok, true);
    if (supertypes.ok) {
      assert.deepEqual(supertypes.data.results.map((entry) => entry.relation), ['root', 'supertype']);
    }
    const subtypes = await router.getTypeHierarchy({
      workspaceId: record.workspaceId,
      file: 'src/hierarchy.ts',
      line: 11,
      column: 14,
      direction: 'subtypes',
      maxDepth: 1,
    });
    assert.equal(subtypes.ok, true);
    if (subtypes.ok) {
      assert.deepEqual(subtypes.data.results.map((entry) => entry.relation), ['root', 'subtype']);
    }
    await router.close();
  } finally {
    await state.dispose();
  }
});

test('reference and diagnostic routes filter, dedupe, sort, and window safe DTOs', async () => {
  const state = await fixture();
  const now = 1_000_000;
  const record = usableRecord(state.primitives, 'read-results', now);
  const calls: Array<{ readonly method: string; readonly params: JsonObject }> = [];
  let connectCount = 0;
  let semanticSession: FakeSession | undefined;
  try {
    await state.registry.publish(record);
    const router = new WorkspaceRouter({
      registry: state.registry,
      primitives: state.primitives,
      now: () => now,
      connect: () => {
        connectCount += 1;
        semanticSession = new FakeSession((method: string, params: JsonObject) => {
        calls.push({ method, params });
        if (method === 'references.get') {
          return {
            status: 'completed',
            candidates: [
              { file: 'src/z.ts', line: 3, column: 2 },
              { file: 'src/a.ts', line: 2, column: 7, snippet: 'Widget();' },
              { file: 'src/a.ts', line: 2, column: 7, snippet: 'Widget();' },
              { file: 'src/a.test.ts', line: 1, column: 1 },
            ],
          };
        }
        if (method === 'references.verifyCandidates') {
          return {
            status: 'completed',
            candidates: [
              { file: 'src/a.ts', line: 2, column: 7, status: 'verified' },
              { file: 'src/z.ts', line: 3, column: 2, status: 'mismatched' },
            ],
          };
        }
        if (method === 'diagnostics.get') {
          return {
            status: 'completed',
            candidates: [
              {
                file: 'src/z.ts',
                range: { startLine: 2, startColumn: 1, endLine: 2, endColumn: 4 },
                severity: 'warning',
                message: 'Z warning.',
                source: 'typescript',
              },
              {
                file: 'src/widget.ts',
                range: { startLine: 3, startColumn: 1, endLine: 3, endColumn: 2 },
                severity: 'warning',
                message: 'Lint warning.',
                source: 'eslint',
              },
              {
                file: 'src/widget.ts',
                range: { startLine: 2, startColumn: 3, endLine: 2, endColumn: 9 },
                severity: 'warning',
                message: 'Use BaseWidget.',
                source: 'typescript',
                relatedInformation: [{
                  file: 'src/base.ts',
                  range: { startLine: 1, startColumn: 1, endLine: 1, endColumn: 5 },
                  message: 'Declared here.',
                }],
              },
            ],
          };
        }
        throw new Error('Unexpected bridge method.');
        });
        return Promise.resolve(semanticSession);
      },
    });

    const references = await router.getReferences({
      workspaceId: record.workspaceId,
      file: 'src/widget.ts',
      line: 2,
      column: 7,
      excludeGlobs: ['**/*.test.ts'],
      timeoutMs: 90_000,
      resultStart: 2,
      resultEnd: 2,
    });
    assert.equal(references.ok, true);
    if (references.ok) {
      assert.equal(references.data.available, 2);
      assert.deepEqual(references.data.results, [{ file: 'src/z.ts', line: 3, column: 2 }]);
    }
    assert.deepEqual(calls[0], {
      method: 'references.get',
      params: {
        file: 'src/widget.ts',
        line: 2,
        column: 7,
        contextLines: 0,
        excludeGlobs: ['**/*.test.ts'],
        timeoutMs: 90_000,
        resultStart: 2,
        resultEnd: 2,
      },
    });

    const verified = await router.verifySymbolCandidates({
      workspaceId: record.workspaceId,
      file: 'src/widget.ts',
      line: 2,
      column: 7,
      candidates: [
        { file: 'src/a.ts', line: 2, column: 7 },
        { file: 'src/z.ts', line: 3, column: 2 },
      ],
      timeoutMs: 30_000,
    });
    assert.equal(verified.ok, true);
    if (verified.ok) {
      assert.equal(verified.data.available, 2);
      assert.deepEqual(verified.data.results.map((candidate) => candidate.status), [
        'verified',
        'mismatched',
      ]);
    }
    assert.deepEqual(calls[1], {
      method: 'references.verifyCandidates',
      params: {
        file: 'src/widget.ts',
        line: 2,
        column: 7,
        candidates: [
          { file: 'src/a.ts', line: 2, column: 7 },
          { file: 'src/z.ts', line: 3, column: 2 },
        ],
        timeoutMs: 30_000,
      },
    });

    const diagnostics = await router.getDiagnostics({
      workspaceId: record.workspaceId,
      severities: ['warning'],
      sources: ['typescript'],
      resultStart: 1,
      resultEnd: 1,
    });
    assert.equal(diagnostics.ok, true);
    if (diagnostics.ok) {
      assert.equal(diagnostics.data.available, 2);
      assert.deepEqual(diagnostics.data.results, [{
        file: 'src/widget.ts',
        range: { startLine: 2, startColumn: 3, endLine: 2, endColumn: 9 },
        severity: 'warning',
        message: 'Use BaseWidget.',
        source: 'typescript',
      }]);
    }
    assert.deepEqual(calls[2], {
      method: 'diagnostics.get',
      params: { scope: 'modifiedFiles', includeRelatedInformation: false },
    });
    assert.equal(connectCount, 1);
    await router.close();
    assert.equal(semanticSession?.closed, true);
  } finally {
    await state.dispose();
  }
});
