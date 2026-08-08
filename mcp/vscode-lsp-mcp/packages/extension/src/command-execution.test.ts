import assert from 'node:assert/strict';
import test from 'node:test';
import type {
  ExecuteCommandInput,
  InternalWorkspaceRoot,
  JsonValue,
  RootAlias,
  WorkspacePathAccess,
  WorkspacePathContext,
  WorkspaceRouteIdentity,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  CommandExecutionExecutor,
  type CommandExecutionDisposable,
  type CommandExecutionDocument,
  type CommandExecutionHost,
  type CommandExecutionRuntime,
  type CommandTaskOutputCapture,
  type CommandTaskProcessEndEvent,
  type CommandTaskStartEvent,
} from './command-execution.js';
import { CommandPolicyPreflight } from './command-policy-provider.js';
import { WorkspaceExclusiveMutationGate } from './mutation-gate.js';
import {
  TaskDiscoveryPreflight,
  type TaskCandidate,
} from './task-discovery.js';

interface FakeExecution {
  readonly taskExecution: true;
  readonly key: string;
  ended: boolean;
}

interface FakeDocument extends CommandExecutionDocument {
  readonly name: string;
}

class FakeRuntime implements CommandExecutionRuntime {
  #now = 1_000;
  #nextId = 1;
  readonly #timers = new Map<number, { readonly due: number; readonly callback: () => void }>();

  now(): number { return this.#now; }
  setTimer(callback: () => void, milliseconds: number): unknown {
    const id = this.#nextId++;
    this.#timers.set(id, { due: this.#now + milliseconds, callback });
    return id;
  }
  clearTimer(handle: unknown): void { this.#timers.delete(handle as number); }
  advance(milliseconds: number): void {
    this.#now += milliseconds;
    while (true) {
      const ready = [...this.#timers.entries()]
        .filter(([, timer]) => timer.due <= this.#now)
        .sort((left, right) => left[1].due - right[1].due || left[0] - right[0])[0];
      if (ready === undefined) return;
      this.#timers.delete(ready[0]);
      ready[1].callback();
    }
  }
}

class FakeHost implements CommandExecutionHost<string, FakeExecution, FakeDocument, string> {
  readonly uri = Object.freeze({ file: (absolutePath: string) => `uri:${absolutePath}` });
  readonly taskStarts = new Set<(event: CommandTaskStartEvent<FakeExecution>) => void>();
  readonly processStarts = new Set<(event: CommandTaskStartEvent<FakeExecution>) => void>();
  readonly processEnds = new Set<(event: CommandTaskProcessEndEvent<FakeExecution>) => void>();
  readonly taskEnds = new Set<(event: CommandTaskStartEvent<FakeExecution>) => void>();
  readonly running: FakeExecution[] = [];
  readonly terminated: FakeExecution[] = [];
  docs: FakeDocument[] = [];
  active: FakeDocument | undefined;
  executeCommandImpl: (commandId: string, args: readonly unknown[]) => PromiseLike<unknown> =
    () => Promise.resolve(undefined);
  executeTaskImpl: (task: string) => PromiseLike<FakeExecution> = (task) => {
    const execution: FakeExecution = { taskExecution: true, key: `root\u0000${task}`, ended: false };
    this.running.push(execution);
    queueMicrotask(() => {
      this.emitStart(execution);
      this.emitProcessStart(execution);
      this.emitProcessEnd(execution, 0);
      this.emitEnd(execution);
    });
    return Promise.resolve(execution);
  };
  prepareTaskOutputCaptureImpl: (
    _context: WorkspacePathContext,
    task: string,
    _taskName: string,
  ) => PromiseLike<CommandTaskOutputCapture<string> | undefined> = () => Promise.resolve(undefined);
  terminateTaskImpl: (execution: FakeExecution) => void = () => undefined;

  activeDocument(): FakeDocument | undefined { return this.active; }
  documents(): readonly FakeDocument[] { return this.docs; }
  executeCommand(commandId: string, args: readonly unknown[]): PromiseLike<unknown> {
    return this.executeCommandImpl(commandId, args);
  }
  isTaskExecution(value: unknown): value is FakeExecution {
    return value !== null && typeof value === 'object' &&
      (value as Partial<FakeExecution>).taskExecution === true;
  }
  activeTaskExecutions(): readonly FakeExecution[] {
    return this.running.filter((execution) => !execution.ended);
  }
  executeTask(task: string): PromiseLike<FakeExecution> { return this.executeTaskImpl(task); }
  prepareTaskOutputCapture(
    context: WorkspacePathContext,
    task: string,
    taskName: string,
  ): PromiseLike<CommandTaskOutputCapture<string> | undefined> {
    return this.prepareTaskOutputCaptureImpl(context, task, taskName);
  }
  taskKey(_context: WorkspacePathContext, execution: FakeExecution): string { return execution.key; }
  terminateTask(execution: FakeExecution): void {
    this.terminated.push(execution);
    this.terminateTaskImpl(execution);
  }
  onTaskStart(listener: (event: CommandTaskStartEvent<FakeExecution>) => void): CommandExecutionDisposable {
    return this.subscribe(this.taskStarts, listener);
  }
  onTaskProcessStart(
    listener: (event: CommandTaskStartEvent<FakeExecution>) => void,
  ): CommandExecutionDisposable {
    return this.subscribe(this.processStarts, listener);
  }
  onTaskProcessEnd(
    listener: (event: CommandTaskProcessEndEvent<FakeExecution>) => void,
  ): CommandExecutionDisposable {
    return this.subscribe(this.processEnds, listener);
  }
  onTaskEnd(listener: (event: CommandTaskStartEvent<FakeExecution>) => void): CommandExecutionDisposable {
    return this.subscribe(this.taskEnds, listener);
  }
  emitStart(execution: FakeExecution): void {
    for (const listener of this.taskStarts) listener({ execution });
  }
  emitProcessStart(execution: FakeExecution): void {
    for (const listener of this.processStarts) listener({ execution });
  }
  emitProcessEnd(execution: FakeExecution, exitCode: number | undefined): void {
    for (const listener of this.processEnds) listener({ execution, exitCode });
  }
  emitEnd(execution: FakeExecution): void {
    execution.ended = true;
    for (const listener of this.taskEnds) listener({ execution });
  }
  private subscribe<T>(listeners: Set<T>, listener: T): CommandExecutionDisposable {
    listeners.add(listener);
    return { dispose: () => listeners.delete(listener) };
  }
}

const root: InternalWorkspaceRoot = {
  alias: 'root' as RootAlias,
  name: 'root',
  folderIndex: 0,
  lexicalAbsolutePath: 'C:\\workspace',
  canonicalAbsolutePath: 'C:\\workspace',
  lexicalComparisonKey: 'c:\\workspace',
  canonicalComparisonKey: 'c:\\workspace',
};

const context: WorkspacePathContext = { platform: 'win32', roots: [root] };
const workspace: WorkspaceRouteIdentity = {
  workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA' as WorkspaceRouteIdentity['workspaceId'],
  generation: 1,
};
const pathAccess: WorkspacePathAccess = {
  entryType: (absolutePath) => Promise.resolve(
    absolutePath.toLowerCase().startsWith('c:\\workspace\\') ? 'file' : 'missing',
  ),
  realpath: (absolutePath) => Promise.resolve(absolutePath),
};

const commandEntry = (commandId: string, argumentSchema?: Record<string, unknown>) => ({
  commandId,
  nonInteractive: true as const,
  completion: 'promise' as const,
  maxTimeoutMs: 60_000,
  ...(argumentSchema === undefined ? {} : { argumentSchema }),
});

const taskEntry = (
  taskName: string,
  maxTimeoutMs = 60_000,
  allowDependencies = false,
) => ({
  rootAlias: 'root',
  taskName,
  nonInteractive: true as const,
  allowDependencies,
  maxTimeoutMs,
});

const taskCandidate = (taskName: string): TaskCandidate<string> => ({
  handle: taskName,
  name: taskName,
  scopeKind: 'folder',
  scopePath: root.lexicalAbsolutePath,
  definition: { type: 'process' },
  execution: { kind: 'process', process: 'node', args: [] },
  isBackground: false,
});

const createExecutor = (
  host: FakeHost,
  runtime: FakeRuntime,
  commands: readonly ReturnType<typeof commandEntry>[],
  tasks: readonly ReturnType<typeof taskEntry>[] = [],
  gate = new WorkspaceExclusiveMutationGate(),
  candidates: readonly TaskCandidate<string>[] = tasks.map((entry) => taskCandidate(entry.taskName)),
  defaults: { readonly commands?: boolean; readonly tasks?: boolean } = {},
) => {
  const policyHost = {
    isWorkspaceTrusted: () => true,
    readCommandPolicyConfiguration: () => ({
      allowStandardCommands: defaults.commands ?? false,
      allowWorkspaceTasks: defaults.tasks ?? false,
      commands,
      tasks,
    }),
  };
  return {
    gate,
    executor: new CommandExecutionExecutor(host, {
      gate,
      pathAccess,
      policy: new CommandPolicyPreflight(policyHost),
      taskDiscovery: new TaskDiscoveryPreflight({
        platform: 'win32',
        fetchTasks: () => Promise.resolve(candidates),
        readTaskConfiguration: () => Promise.resolve({ status: 'missing' }),
      }, policyHost),
      runtime,
    }),
  };
};

const commandInput = (
  commandId: string,
  args: readonly JsonValue[] = [],
  extra: Partial<Pick<ExecuteCommandInput, 'saveBeforeRun' | 'timeoutMs' | 'maxOutputChars'>> = {},
): ExecuteCommandInput => ({
  workspaceId: workspace.workspaceId,
  target: { kind: 'command', commandId, arguments: args },
  ...extra,
});

const flush = async (): Promise<void> => {
  for (let index = 0; index < 8; index += 1) await Promise.resolve();
};

test('command execution saves selected files in logical order, resolves logical Uri args, and truncates code points', async () => {
  const runtime = new FakeRuntime();
  const host = new FakeHost();
  const saves: string[] = [];
  const document = (name: string, fsPath: string, scheme = 'file'): FakeDocument => ({
    name,
    uri: { scheme, fsPath },
    isDirty: true,
    save: () => { saves.push(name); return Promise.resolve(true); },
  });
  host.docs = [
    document('b', 'C:\\workspace\\b.ts'),
    document('outside', 'D:\\outside.ts'),
    document('untitled', '', 'untitled'),
    document('a', 'C:\\workspace\\a.ts'),
  ];
  let receivedArgs: readonly unknown[] = [];
  host.executeCommandImpl = (_commandId, args) => {
    receivedArgs = args;
    return Promise.resolve('A😀BC');
  };
  const schema = {
    type: 'array',
    minItems: 1,
    maxItems: 1,
    prefixItems: [{
      type: 'string',
      'x-vscode-lsp-mcp-logicalPath': true,
    }],
    items: false,
  };
  const { executor } = createExecutor(host, runtime, [commandEntry('safe.command', schema)]);
  const response = await executor.execute(
    context,
    workspace,
    commandInput('safe.command', ['src/input.ts'], { saveBeforeRun: 'all', maxOutputChars: 2 }),
  );
  assert.deepEqual(saves, ['a', 'b'], JSON.stringify(response));
  assert.deepEqual(receivedArgs, ['uri:C:\\workspace\\src\\input.ts']);
  assert.deepEqual(response, {
    ok: true,
    data: { output: 'A😀', outputTruncated: true },
  });
});

test('logical argument boundary failures stay pre-invocation protocol errors', async () => {
  const runtime = new FakeRuntime();
  const host = new FakeHost();
  let invoked = false;
  host.executeCommandImpl = () => { invoked = true; return Promise.resolve(undefined); };
  const schema = {
    type: 'array',
    minItems: 1,
    maxItems: 1,
    prefixItems: [{ type: 'string', 'x-vscode-lsp-mcp-logicalPath': true }],
    items: false,
  };
  const { executor } = createExecutor(host, runtime, [commandEntry('safe.command', schema)]);
  const response = await executor.execute(
    context,
    workspace,
    commandInput('safe.command', ['../outside.ts']),
  );
  assert.equal(invoked, false);
  assert.equal(response.ok, false);
  if (!response.ok) assert.equal(response.error.code, 'INVALID_ARGUMENT');
});

test('save failure prevents invocation and reports possible partial saves without file claims', async () => {
  const runtime = new FakeRuntime();
  const host = new FakeHost();
  let invoked = false;
  host.docs = [{
    name: 'a',
    uri: { scheme: 'file', fsPath: 'C:\\workspace\\a.ts' },
    isDirty: true,
    save: () => Promise.resolve(false),
  }];
  host.executeCommandImpl = () => { invoked = true; return Promise.resolve(undefined); };
  const { executor } = createExecutor(host, runtime, [commandEntry('safe.command')]);
  const response = await executor.execute(
    context,
    workspace,
    commandInput('safe.command', [], { saveBeforeRun: 'all' }),
  );
  assert.equal(invoked, false);
  assert.equal(response.ok, false);
  if (response.ok) return;
  assert.equal(response.error.code, 'COMMAND_FAILED');
  assert.match(response.error.action ?? '', /may already have been saved/u);
  assert.equal(JSON.stringify(response).includes('savedFiles'), false);
});

test('save timeout is a saveFailed/notStarted error rather than a target timeout', async () => {
  const runtime = new FakeRuntime();
  const host = new FakeHost();
  let resolveFirst: (saved: boolean) => void = () => undefined;
  let secondSaveCalls = 0;
  host.docs = [
    {
      name: 'a',
      uri: { scheme: 'file', fsPath: 'C:\\workspace\\a.ts' },
      isDirty: true,
      save: () => new Promise<boolean>((resolve) => { resolveFirst = resolve; }),
    },
    {
      name: 'b',
      uri: { scheme: 'file', fsPath: 'C:\\workspace\\b.ts' },
      isDirty: true,
      save: () => { secondSaveCalls += 1; return Promise.resolve(true); },
    },
  ];
  const { executor } = createExecutor(host, runtime, [commandEntry('safe.command')]);
  const pending = executor.execute(
    context,
    workspace,
    commandInput('safe.command', [], { saveBeforeRun: 'all', timeoutMs: 1_000 }),
  );
  await flush();
  runtime.advance(1_000);
  const response = await pending;
  assert.equal(response.ok, false);
  if (!response.ok && response.error.code === 'COMMAND_FAILED') {
    assert.equal(response.error.details.reason, 'saveFailed');
    assert.equal(response.error.details.outcome, 'notStarted');
  }
  resolveFirst(true);
  await flush();
  assert.equal(secondSaveCalls, 0);
});

test('timed-out command retains the workspace gate until its promise settles', async () => {
  const runtime = new FakeRuntime();
  const host = new FakeHost();
  let resolveFirst: (value: unknown) => void = () => undefined;
  let calls = 0;
  host.executeCommandImpl = () => {
    calls += 1;
    if (calls === 1) return new Promise((resolve) => { resolveFirst = resolve; });
    return Promise.resolve(undefined);
  };
  const { executor } = createExecutor(host, runtime, [commandEntry('safe.command')]);
  const first = executor.execute(
    context,
    workspace,
    commandInput('safe.command', [], { timeoutMs: 1_000 }),
  );
  await flush();
  runtime.advance(1_000);
  const timedOut = await first;
  assert.equal(timedOut.ok, false);
  if (!timedOut.ok) assert.equal(timedOut.error.code, 'COMMAND_TIMEOUT');

  const blocked = await executor.execute(context, workspace, commandInput('safe.command'));
  assert.equal(blocked.ok, false);
  if (!blocked.ok && blocked.error.code === 'COMMAND_FAILED') {
    assert.equal(blocked.error.details.reason, 'alreadyRunning');
  }
  resolveFirst(undefined);
  await flush();
  assert.equal((await executor.execute(context, workspace, commandInput('safe.command'))).ok, true);
});

test('command rejection and cancellation have distinct terminal outcomes', async () => {
  const runtime = new FakeRuntime();
  const host = new FakeHost();
  const { executor, gate } = createExecutor(host, runtime, [commandEntry('safe.command')]);
  host.executeCommandImpl = () => Promise.reject(new Error('private detail'));
  const rejected = await executor.execute(context, workspace, commandInput('safe.command'));
  assert.equal(rejected.ok, false);
  if (!rejected.ok && rejected.error.code === 'COMMAND_FAILED') {
    assert.equal(rejected.error.details.reason, 'rejected');
    assert.equal(rejected.error.details.outcome, 'failed');
    assert.equal(JSON.stringify(rejected).includes('private detail'), false);
  }

  let settle = (): void => undefined;
  host.executeCommandImpl = () => new Promise<void>((resolve) => { settle = resolve; });
  const controller = new AbortController();
  const pending = executor.execute(
    context,
    workspace,
    commandInput('safe.command'),
    controller.signal,
  );
  await flush();
  controller.abort();
  const cancelled = await pending;
  assert.equal(cancelled.ok, false);
  if (!cancelled.ok && cancelled.error.code === 'COMMAND_FAILED') {
    assert.equal(cancelled.error.details.reason, 'cancelled');
    assert.equal(cancelled.error.details.outcome, 'unknown');
  }
  assert.equal(gate.tryAcquire(workspace, 'command'), undefined);
  settle();
  await flush();
  const lease = gate.tryAcquire(workspace, 'command');
  assert.ok(lease);
  lease.release();
});

test('synchronous command throws are rejected failures and release the gate', async () => {
  const runtime = new FakeRuntime();
  const host = new FakeHost();
  host.executeCommandImpl = () => { throw new Error('private detail'); };
  const { executor, gate } = createExecutor(host, runtime, [commandEntry('safe.command')]);
  const response = await executor.execute(context, workspace, commandInput('safe.command'));
  assert.equal(response.ok, false);
  if (!response.ok && response.error.code === 'COMMAND_FAILED') {
    assert.equal(response.error.details.reason, 'rejected');
    assert.equal(response.error.details.outcome, 'failed');
  }
  const lease = gate.tryAcquire(workspace, 'command');
  assert.ok(lease);
  lease.release();
});

test('reload is acknowledged before the lifecycle command disconnects the bridge', async () => {
  const runtime = new FakeRuntime();
  const host = new FakeHost();
  const invoked: string[] = [];
  host.executeCommandImpl = (commandId) => {
    invoked.push(commandId);
    return Promise.resolve(undefined);
  };
  const gate = new WorkspaceExclusiveMutationGate();
  const { executor } = createExecutor(host, runtime, [], [], gate, [], { commands: true });
  const result = await executor.execute(
    context,
    workspace,
    commandInput('workbench.action.reloadWindow'),
  );
  assert.equal(result.ok, true);
  if (result.ok) {
    assert.equal(result.data.result, true);
    assert.equal(result.data.warnings?.length, 1);
  }
  assert.deepEqual(invoked, []);
  runtime.advance(249);
  assert.deepEqual(invoked, []);
  runtime.advance(1);
  await flush();
  assert.deepEqual(invoked, ['workbench.action.reloadWindow']);
  const lease = gate.tryAcquire(workspace, 'command');
  assert.notEqual(lease, undefined);
  lease?.release();
});

test('a command returning TaskExecution is not treated as completed', async () => {
  const runtime = new FakeRuntime();
  const host = new FakeHost();
  const execution: FakeExecution = {
    taskExecution: true,
    key: 'root\u0000build',
    ended: false,
  };
  host.running.push(execution);
  host.executeCommandImpl = () => Promise.resolve(execution);
  const { executor, gate } = createExecutor(host, runtime, [commandEntry('safe.command')]);
  const response = await executor.execute(context, workspace, commandInput('safe.command'));
  assert.equal(response.ok, false);
  if (!response.ok && response.error.code === 'COMMAND_FAILED') {
    assert.equal(response.error.details.reason, 'completionUnverifiable');
    assert.equal(response.error.details.outcome, 'unknown');
  }
  assert.deepEqual(host.terminated, [execution]);
  assert.equal(gate.tryAcquire(workspace, 'command'), undefined);
  host.emitEnd(execution);
  await flush();
  const lease = gate.tryAcquire(workspace, 'command');
  assert.ok(lease);
  lease.release();
});

test('command JSON results are deterministic and unsupported public values use sanitized warnings', async () => {
  const runtime = new FakeRuntime();
  const host = new FakeHost();
  host.executeCommandImpl = () => Promise.resolve({ z: 1, a: [true] });
  const { executor } = createExecutor(host, runtime, [commandEntry('safe.command')]);
  const objectResult = await executor.execute(context, workspace, commandInput('safe.command'));
  assert.deepEqual(objectResult, { ok: true, data: { result: { a: [true], z: 1 } } });
  host.executeCommandImpl = () => Promise.resolve(null);
  const omitted = await executor.execute(context, workspace, commandInput('safe.command'));
  assert.equal(omitted.ok, true);
  if (omitted.ok) {
    assert.equal(omitted.data.result, undefined);
    assert.equal(omitted.data.warnings?.length, 1);
  }
});

test('non-interactive build, test, and format tasks complete from verified task events', async () => {
  for (const taskName of ['build', 'test', 'format']) {
    const runtime = new FakeRuntime();
    const host = new FakeHost();
    const { executor } = createExecutor(host, runtime, [], [taskEntry(taskName)]);
    const response = await executor.execute(context, workspace, {
      workspaceId: workspace.workspaceId,
      target: { kind: 'task', taskName, taskRoot: 'root' },
    });
    assert.deepEqual(response, { ok: true, data: {} }, taskName);
  }
});

test('task tracking verifies every dependency while dispatching only the root task once', async () => {
  const runtime = new FakeRuntime();
  const host = new FakeHost();
  const dispatched: string[] = [];
  host.executeTaskImpl = (task) => {
    dispatched.push(task);
    const dependency: FakeExecution = {
      taskExecution: true,
      key: 'root\u0000compile',
      ended: false,
    };
    const rootExecution: FakeExecution = {
      taskExecution: true,
      key: 'root\u0000build',
      ended: false,
    };
    host.running.push(dependency, rootExecution);
    queueMicrotask(() => {
      for (const execution of [dependency, rootExecution]) {
        host.emitStart(execution);
        host.emitProcessStart(execution);
        host.emitProcessEnd(execution, 0);
        host.emitEnd(execution);
      }
    });
    return Promise.resolve(rootExecution);
  };
  const candidates = [
    { ...taskCandidate('build'), definition: { type: 'process', dependsOn: 'compile' } },
    taskCandidate('compile'),
  ];
  const { executor } = createExecutor(
    host,
    runtime,
    [],
    [taskEntry('build', 60_000, true), taskEntry('compile')],
    new WorkspaceExclusiveMutationGate(),
    candidates,
  );
  const response = await executor.execute(context, workspace, {
    workspaceId: workspace.workspaceId,
    target: { kind: 'task', taskName: 'build', taskRoot: 'root' },
  });
  assert.deepEqual(dispatched, ['build']);
  assert.deepEqual(response, { ok: true, data: {} });
});

test('task non-zero and missing exit statuses are completion failures', async () => {
  for (const exitCode of [7, undefined] as const) {
    const runtime = new FakeRuntime();
    const host = new FakeHost();
    host.executeTaskImpl = (task) => {
      const execution: FakeExecution = {
        taskExecution: true,
        key: `root\u0000${task}`,
        ended: false,
      };
      host.running.push(execution);
      queueMicrotask(() => {
        host.emitStart(execution);
        host.emitProcessStart(execution);
        host.emitProcessEnd(execution, exitCode);
        host.emitEnd(execution);
      });
      return Promise.resolve(execution);
    };
    const { executor } = createExecutor(host, runtime, [], [taskEntry('build')]);
    const response = await executor.execute(context, workspace, {
      workspaceId: workspace.workspaceId,
      target: { kind: 'task', taskName: 'build', taskRoot: 'root' },
    });
    assert.equal(response.ok, false);
    if (!response.ok && response.error.code === 'COMMAND_FAILED') {
      assert.equal(response.error.details.reason,
        exitCode === undefined ? 'completionUnverifiable' : 'nonZeroExit');
    }
  }
});

test('task failures retain output while successful tasks require retainOutputLog', async () => {
  const outputLog = {
    path: '.vscode-lsp-mcp/task-logs/20260722T153012-build-a81f42.log',
    lineCount: 2,
    byteCount: 39,
    encoding: 'utf-8' as const,
    truncated: false,
  };
  for (const [exitCode, retainOutputLog] of [[0, false], [0, true], [7, false]] as const) {
    const runtime = new FakeRuntime();
    const host = new FakeHost();
    const retained: boolean[] = [];
    host.prepareTaskOutputCaptureImpl = (_context, task) => Promise.resolve({
      task,
      finish: (retain) => {
        retained.push(retain);
        return Promise.resolve(retain ? outputLog : undefined);
      },
    });
    host.executeTaskImpl = (task) => {
      const execution: FakeExecution = {
        taskExecution: true,
        key: `root\u0000${task}`,
        ended: false,
      };
      host.running.push(execution);
      queueMicrotask(() => {
        host.emitStart(execution);
        host.emitProcessStart(execution);
        host.emitProcessEnd(execution, exitCode);
        host.emitEnd(execution);
      });
      return Promise.resolve(execution);
    };
    const { executor } = createExecutor(host, runtime, [], [taskEntry('build')]);
    const response = await executor.execute(context, workspace, {
      workspaceId: workspace.workspaceId,
      target: { kind: 'task', taskName: 'build', taskRoot: 'root' },
      retainOutputLog,
    });
    assert.deepEqual(retained, [exitCode !== 0 || retainOutputLog]);
    if (exitCode === 0) {
      assert.deepEqual(response, {
        ok: true,
        data: retainOutputLog ? { outputLog } : {},
      });
    } else {
      assert.equal(response.ok, false);
      if (!response.ok && response.error.code === 'COMMAND_FAILED') {
        assert.deepEqual(response.error.details.outputLog, outputLog);
      }
    }
  }
});

test('synchronous task invocation throws are rejected before any task starts', async () => {
  const runtime = new FakeRuntime();
  const host = new FakeHost();
  host.executeTaskImpl = () => { throw new Error('private detail'); };
  const { executor, gate } = createExecutor(host, runtime, [], [taskEntry('build')]);
  const response = await executor.execute(context, workspace, {
    workspaceId: workspace.workspaceId,
    target: { kind: 'task', taskName: 'build', taskRoot: 'root' },
  });
  assert.equal(response.ok, false);
  if (!response.ok && response.error.code === 'COMMAND_FAILED') {
    assert.equal(response.error.details.reason, 'rejected');
    assert.equal(response.error.details.outcome, 'notStarted');
  }
  const lease = gate.tryAcquire(workspace, 'command');
  assert.ok(lease);
  lease.release();
});

test('task timeout terminates tracked executions and retains the gate until task-end', async () => {
  const runtime = new FakeRuntime();
  const host = new FakeHost();
  let execution: FakeExecution | undefined;
  host.executeTaskImpl = (task) => {
    execution = { taskExecution: true, key: `root\u0000${task}`, ended: false };
    host.running.push(execution);
    queueMicrotask(() => host.emitStart(execution!));
    return Promise.resolve(execution);
  };
  const gate = new WorkspaceExclusiveMutationGate();
  const { executor } = createExecutor(host, runtime, [], [taskEntry('build', 1_000)], gate);
  const pending = executor.execute(context, workspace, {
    workspaceId: workspace.workspaceId,
    target: { kind: 'task', taskName: 'build', taskRoot: 'root' },
    timeoutMs: 1_000,
  });
  await flush();
  runtime.advance(1_000);
  await flush();
  assert.equal(host.terminated.length, 1);
  runtime.advance(5_000);
  const response = await pending;
  assert.equal(response.ok, false);
  if (!response.ok && response.error.code === 'COMMAND_TIMEOUT') {
    assert.equal(response.error.details.outcome, 'unknown');
  }
  assert.equal(gate.tryAcquire(workspace, 'command'), undefined);
  host.emitEnd(execution!);
  await flush();
  const lease = gate.tryAcquire(workspace, 'command');
  assert.ok(lease);
  lease.release();
});

test('task timeout reports terminated when all tracked executions end during the five-second grace', async () => {
  const runtime = new FakeRuntime();
  const host = new FakeHost();
  host.executeTaskImpl = (task) => {
    const execution: FakeExecution = {
      taskExecution: true,
      key: `root\u0000${task}`,
      ended: false,
    };
    host.running.push(execution);
    queueMicrotask(() => host.emitStart(execution));
    return Promise.resolve(execution);
  };
  host.terminateTaskImpl = (execution) => queueMicrotask(() => {
    host.emitProcessEnd(execution, 0);
    host.emitEnd(execution);
  });
  const { executor } = createExecutor(host, runtime, [], [taskEntry('build', 1_000)]);
  const pending = executor.execute(context, workspace, {
    workspaceId: workspace.workspaceId,
    target: { kind: 'task', taskName: 'build', taskRoot: 'root' },
    timeoutMs: 1_000,
  });
  await flush();
  runtime.advance(1_000);
  const response = await pending;
  assert.equal(response.ok, false);
  if (!response.ok && response.error.code === 'COMMAND_TIMEOUT') {
    assert.equal(response.error.details.outcome, 'terminated');
  }
});

test('task cancellation waits for termination events and reports a terminated outcome', async () => {
  const runtime = new FakeRuntime();
  const host = new FakeHost();
  let execution: FakeExecution | undefined;
  host.executeTaskImpl = (task) => {
    execution = { taskExecution: true, key: `root\u0000${task}`, ended: false };
    host.running.push(execution);
    queueMicrotask(() => host.emitStart(execution!));
    return Promise.resolve(execution);
  };
  const { executor } = createExecutor(host, runtime, [], [taskEntry('build')]);
  const controller = new AbortController();
  const pending = executor.execute(context, workspace, {
    workspaceId: workspace.workspaceId,
    target: { kind: 'task', taskName: 'build', taskRoot: 'root' },
  }, controller.signal);
  await flush();
  controller.abort();
  await flush();
  assert.equal(host.terminated.length, 1);
  host.emitProcessEnd(execution!, 0);
  host.emitEnd(execution!);
  const response = await pending;
  assert.equal(response.ok, false);
  if (!response.ok && response.error.code === 'COMMAND_FAILED') {
    assert.equal(response.error.details.reason, 'cancelled');
    assert.equal(response.error.details.outcome, 'terminated');
  }
});

test('an already-active canonical task is not launched again and holds the gate until it ends', async () => {
  const runtime = new FakeRuntime();
  const host = new FakeHost();
  const active: FakeExecution = {
    taskExecution: true,
    key: 'root\u0000build',
    ended: false,
  };
  host.running.push(active);
  let dispatches = 0;
  host.executeTaskImpl = () => {
    dispatches += 1;
    return Promise.resolve(active);
  };
  const gate = new WorkspaceExclusiveMutationGate();
  const { executor } = createExecutor(host, runtime, [], [taskEntry('build')], gate);
  const response = await executor.execute(context, workspace, {
    workspaceId: workspace.workspaceId,
    target: { kind: 'task', taskName: 'build', taskRoot: 'root' },
  });
  assert.equal(dispatches, 0);
  assert.equal(response.ok, false);
  if (!response.ok && response.error.code === 'COMMAND_FAILED') {
    assert.equal(response.error.details.reason, 'alreadyRunning');
  }
  assert.equal(gate.tryAcquire(workspace, 'command'), undefined);
  host.emitEnd(active);
  await flush();
  const lease = gate.tryAcquire(workspace, 'command');
  assert.ok(lease);
  lease.release();
});
