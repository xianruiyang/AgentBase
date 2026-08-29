import assert from 'node:assert/strict';
import test from 'node:test';
import type { TextDocument } from 'vscode';
import {
  WorkspaceBoundaryError,
  type RootAlias,
  type WorkspacePathAccess,
  type WorkspacePathContext,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  PROVIDER_DEFAULT_TIMEOUT_MS,
  PROVIDER_MAX_TIMEOUT_MS,
  ProviderRuntime,
  classifyArrayProviderResult,
  createVscodeProviderCallInterrupter,
  type ProviderCommandAdapter,
  type ProviderCallInterruption,
  type VscodeProviderHost,
} from './provider-runtime.js';

test('provider timeout defaults to 60 seconds and remains configurable within the safe bridge bound', () => {
  assert.equal(PROVIDER_DEFAULT_TIMEOUT_MS, 60_000);
  assert.equal(PROVIDER_MAX_TIMEOUT_MS, 300_000);
  assert.ok(PROVIDER_DEFAULT_TIMEOUT_MS < PROVIDER_MAX_TIMEOUT_MS);
});

const context: WorkspacePathContext = {
  platform: 'win32',
  roots: [{
    alias: 'app' as RootAlias,
    name: 'App',
    folderIndex: 0,
    lexicalAbsolutePath: 'D:\\workspace\\app',
    canonicalAbsolutePath: 'D:\\workspace\\app',
    lexicalComparisonKey: 'd:\\workspace\\app',
    canonicalComparisonKey: 'd:\\workspace\\app',
  }],
};

const pathAccess: WorkspacePathAccess = {
  entryType: (value) => Promise.resolve(
    value.toLowerCase() === 'd:\\workspace\\app\\src\\main.ts'
      ? 'file'
      : value.toLowerCase() === 'd:\\workspace\\app'
        ? 'directory'
        : 'missing',
  ),
  realpath: (value) => Promise.resolve(value),
};

const fakeDocument = (path: string): TextDocument => ({
  uri: { scheme: 'file', fsPath: path },
} as TextDocument);

const documentSymbolsAdapter: ProviderCommandAdapter<null, readonly unknown[]> = {
  command: 'vscode.executeDocumentSymbolProvider',
  requiresDocument: true,
  buildArguments: (_input, document) => [document?.uri],
  classifyResult: classifyArrayProviderResult,
};

class Host implements VscodeProviderHost {
  results: unknown[] = [[]];
  opened: string[] = [];
  calls: Array<{ readonly args: readonly unknown[]; readonly command: string }> = [];
  interruptProviderCall?: (request: ProviderCallInterruption) => PromiseLike<void> | void;

  executeCommand(command: string, ...args: readonly unknown[]): PromiseLike<unknown> {
    this.calls.push({ command, args });
    return Promise.resolve(this.results.shift());
  }

  openTextDocument(path: string): PromiseLike<TextDocument> {
    this.opened.push(path);
    return Promise.resolve(fakeDocument(path));
  }
}

test('hidden documents activate without UI and empty provider arrays are successful results', async () => {
  const host = new Host();
  const runtime = new ProviderRuntime({ host, pathAccess });
  const result = await runtime.invoke(context, documentSymbolsAdapter, null, {
    logicalFile: 'src/main.ts',
    pollDelaysMs: [0],
  });
  assert.equal(result.status, 'completed');
  assert.deepEqual(result.status === 'completed' ? result.value : undefined, []);
  assert.deepEqual(host.opened, ['D:\\workspace\\app\\src\\main.ts']);
  assert.equal(host.calls.length, 1);
  assert.equal(host.calls[0]?.command, 'vscode.executeDocumentSymbolProvider');
});

test('explicit not-ready results use only the bounded poll schedule', async () => {
  const host = new Host();
  host.results = [undefined, undefined, ['ready']];
  const runtime = new ProviderRuntime({ host, pathAccess });
  const completed = await runtime.invoke(context, documentSymbolsAdapter, null, {
    logicalFile: 'src/main.ts',
    pollDelaysMs: [0, 1, 1],
  });
  assert.equal(completed.status, 'completed');
  assert.equal(completed.attempts, 3);

  host.results = [undefined, undefined];
  const notReady = await runtime.invoke(context, documentSymbolsAdapter, null, {
    logicalFile: 'src/main.ts',
    pollDelaysMs: [0, 1],
  });
  assert.equal(notReady.status, 'notReady');
  assert.equal(notReady.attempts, 2);
  assert.equal(host.calls.length, 5);
});

test('platform command unavailability is detected by the public command invocation', async () => {
  const host = new Host();
  host.executeCommand = (command) => Promise.reject(new Error(`command '${command}' not found`));
  const runtime = new ProviderRuntime({ host, pathAccess });
  const result = await runtime.invoke(context, documentSymbolsAdapter, null, {
    logicalFile: 'src/main.ts',
  });
  assert.equal(result.status, 'unavailable');
  assert.equal(host.opened.length, 1);
  assert.equal(host.calls.length, 0);
});

test('cancellation and total timeout stop polling without replaying provider calls', async () => {
  const cancellingHost = new Host();
  let markStarted = (): void => undefined;
  const started = new Promise<void>((resolve) => {
    markStarted = resolve;
  });
  let cancellingCalls = 0;
  cancellingHost.executeCommand = () => {
    cancellingCalls += 1;
    markStarted();
    return new Promise<unknown>(() => undefined);
  };
  const cancellingRuntime = new ProviderRuntime({ host: cancellingHost, pathAccess });
  const controller = new AbortController();
  const cancelledPromise = cancellingRuntime.invoke(context, documentSymbolsAdapter, null, {
    logicalFile: 'src/main.ts',
    pollDelaysMs: [0, 1, 1],
    signal: controller.signal,
    timeoutMs: 1_000,
  });
  await started;
  controller.abort();
  const cancelled = await cancelledPromise;
  assert.equal(cancelled.status, 'cancelled');
  assert.equal(cancelled.attempts, 1);
  assert.equal(cancellingCalls, 1);

  const timeoutHost = new Host();
  timeoutHost.executeCommand = () => new Promise<unknown>(() => undefined);
  const timeoutRuntime = new ProviderRuntime({ host: timeoutHost, pathAccess });
  const timedOut = await timeoutRuntime.invoke(context, documentSymbolsAdapter, null, {
    logicalFile: 'src/main.ts',
    pollDelaysMs: [0, 1, 1],
    timeoutMs: 10,
  });
  assert.equal(timedOut.status, 'timedOut');
  assert.equal(timedOut.attempts, 1);
});

test('configured default timeout applies when a call does not override it', async () => {
  const host = new Host();
  host.executeCommand = () => new Promise<unknown>(() => undefined);
  const runtime = new ProviderRuntime({
    defaultTimeoutMs: 10,
    host,
    pathAccess,
  });
  const timedOut = await runtime.invoke(context, documentSymbolsAdapter, null, {
    logicalFile: 'src/main.ts',
    pollDelaysMs: [0],
  });
  assert.equal(timedOut.status, 'timedOut');
  assert.equal(timedOut.attempts, 1);
});

test('a timed-out Provider stays single-flight until its underlying promise settles', async () => {
  const host = new Host();
  let settleProvider: (value: unknown) => void = () => undefined;
  let calls = 0;
  host.executeCommand = () => {
    calls += 1;
    if (calls > 1) return Promise.resolve([]);
    return new Promise<unknown>((resolve) => {
      settleProvider = resolve;
    });
  };
  const runtime = new ProviderRuntime({ host, pathAccess });
  const timedOut = await runtime.invoke(context, documentSymbolsAdapter, null, {
    logicalFile: 'src/main.ts',
    pollDelaysMs: [0],
    timeoutMs: 10,
  });
  assert.equal(timedOut.status, 'timedOut');

  const busy = await runtime.invoke(context, documentSymbolsAdapter, null, {
    logicalFile: 'src/main.ts',
    pollDelaysMs: [0],
  });
  assert.equal(busy.status, 'notReady');
  assert.equal(busy.status === 'notReady' ? busy.reason : undefined, 'providerCallInFlight');
  assert.equal(busy.attempts, 0);
  assert.equal(calls, 1);

  settleProvider([]);
  await Promise.resolve();
  const recovered = await runtime.invoke(context, documentSymbolsAdapter, null, {
    logicalFile: 'src/main.ts',
    pollDelaysMs: [0],
  });
  assert.equal(recovered.status, 'completed');
  assert.equal(calls, 2);
});

test('a supported interruption drains the underlying Provider before the timeout returns', async () => {
  const host = new Host();
  let settleProvider: (value: unknown) => void = () => undefined;
  let calls = 0;
  const interruptions: ProviderCallInterruption[] = [];
  host.executeCommand = () => {
    calls += 1;
    if (calls > 1) return Promise.resolve([]);
    return new Promise<unknown>((resolve) => {
      settleProvider = resolve;
    });
  };
  host.interruptProviderCall = (request) => {
    interruptions.push(request);
    settleProvider(undefined);
  };
  const runtime = new ProviderRuntime({ host, pathAccess });
  const timedOut = await runtime.invoke(context, documentSymbolsAdapter, null, {
    logicalFile: 'src/main.ts',
    pollDelaysMs: [0],
    timeoutMs: 10,
  });
  assert.equal(timedOut.status, 'timedOut');
  assert.equal(interruptions.length, 1);
  assert.equal(interruptions[0]?.command, 'vscode.executeDocumentSymbolProvider');
  assert.equal(interruptions[0]?.status, 'timedOut');

  const recovered = await runtime.invoke(context, documentSymbolsAdapter, null, {
    logicalFile: 'src/main.ts',
    pollDelaysMs: [0],
  });
  assert.equal(recovered.status, 'completed');
  assert.equal(calls, 2);
});

test('VS Code interruption pulse is bounded to heavy C++ reference operations', async () => {
  const calls: Array<{ readonly args: readonly unknown[]; readonly command: string }> = [];
  const interrupt = createVscodeProviderCallInterrupter({
    commands: {
      executeCommand: <T = unknown>(command: string, ...args: readonly unknown[]) => {
        calls.push({ command, args });
        return Promise.resolve(undefined as T);
      },
    },
  });
  const document = {
    languageId: 'cpp',
    uri: { scheme: 'file', fsPath: 'D:\\workspace\\app\\src\\main.cpp' },
    getText: () => 'int main() { return 0; }',
    positionAt: (offset: number) => ({ line: 0, character: offset }),
  } as TextDocument;
  await interrupt({
    command: 'vscode.executeReferenceProvider',
    document,
    status: 'timedOut',
  });
  await interrupt({
    command: 'vscode.executeDefinitionProvider',
    document,
    status: 'timedOut',
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0]?.command, 'vscode.prepareCallHierarchy');
  assert.deepEqual(calls[0]?.args, [document.uri, { line: 0, character: 3 }]);
});

test('document failures, invalid results, and workspace escapes stay distinguishable', async () => {
  const failingHost = new Host();
  failingHost.openTextDocument = () => Promise.reject(new Error('private path detail'));
  const runtime = new ProviderRuntime({ host: failingHost, pathAccess });
  const failed = await runtime.invoke(context, documentSymbolsAdapter, null, {
    logicalFile: 'src/main.ts',
  });
  assert.equal(failed.status, 'failed');
  assert.equal(failed.status === 'failed' ? failed.reason : undefined, 'documentActivationFailed');
  assert.equal(JSON.stringify(failed).includes('private path detail'), false);

  const invalidHost = new Host();
  invalidHost.results = [{ unexpected: true }];
  const invalidRuntime = new ProviderRuntime({ host: invalidHost, pathAccess });
  const invalid = await invalidRuntime.invoke(context, documentSymbolsAdapter, null, {
    logicalFile: 'src/main.ts',
    pollDelaysMs: [0],
  });
  assert.equal(invalid.status, 'failed');
  assert.equal(invalid.status === 'failed' ? invalid.reason : undefined, 'providerResultInvalid');

  await assert.rejects(
    runtime.invoke(context, documentSymbolsAdapter, null, {
      logicalFile: '../outside.ts',
    }),
    (error: unknown) => error instanceof WorkspaceBoundaryError && error.code === 'INVALID_ARGUMENT',
  );
});

test('invalid timeout, schedules, and non-allowlisted commands fail before invocation', async () => {
  const host = new Host();
  assert.throws(
    () => new ProviderRuntime({ defaultTimeoutMs: 0, host, pathAccess }),
    RangeError,
  );
  const runtime = new ProviderRuntime({ host, pathAccess });
  await assert.rejects(
    runtime.invoke(context, documentSymbolsAdapter, null, { timeoutMs: 0 }),
    RangeError,
  );
  await assert.rejects(
    runtime.invoke(context, documentSymbolsAdapter, null, { pollDelaysMs: [1] }),
    RangeError,
  );
  const unsafe = {
    ...documentSymbolsAdapter,
    command: 'extension.privateProvider',
  } as unknown as ProviderCommandAdapter<null, readonly unknown[]>;
  await assert.rejects(runtime.invoke(context, unsafe, null), RangeError);
  assert.equal(host.calls.length, 0);
});
