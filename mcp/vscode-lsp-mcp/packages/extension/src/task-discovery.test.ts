import assert from 'node:assert/strict';
import test from 'node:test';
import type {
  InternalWorkspaceRoot,
  RootAlias,
  WorkspacePathContext,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  createVscodeTaskDiscoveryHost,
  TaskDiscoveryPreflight,
  type TaskCandidate,
  type TaskConfigurationReadResult,
  type TaskDiscoveryDecision,
  type TaskDiscoveryHost,
  type TaskExecutionInspection,
} from './task-discovery.js';

const root = (alias: string, path: string, index: number): InternalWorkspaceRoot => ({
  alias: alias as RootAlias,
  name: alias,
  folderIndex: index,
  lexicalAbsolutePath: path,
  canonicalAbsolutePath: path,
  lexicalComparisonKey: path.toLowerCase(),
  canonicalComparisonKey: path.toLowerCase(),
});

const appRoot = root('app', 'C:\\workspace\\app', 0);
const libRoot = root('lib', 'C:\\workspace\\lib', 1);
const context: WorkspacePathContext = {
  platform: 'win32',
  roots: [appRoot, libRoot],
};

const processExecution = (overrides: Partial<Extract<TaskExecutionInspection, {
  readonly kind: 'process';
}>> = {}): TaskExecutionInspection => ({
  kind: 'process',
  process: 'node',
  args: [],
  ...overrides,
});

const candidate = (
  rootPath: string,
  name: string,
  overrides: Partial<TaskCandidate<string>> = {},
): TaskCandidate<string> => ({
  handle: `${rootPath}:${name}`,
  name,
  scopeKind: 'folder',
  scopePath: rootPath,
  definition: { type: 'shell' },
  execution: processExecution(),
  isBackground: false,
  ...overrides,
});

const taskPolicy = (
  rootAlias: string,
  taskName: string,
  allowDependencies = false,
  maxTimeoutMs = 60_000,
) => ({
  rootAlias,
  taskName,
  nonInteractive: true,
  allowDependencies,
  maxTimeoutMs,
});

const policyHost = (
  tasks: readonly ReturnType<typeof taskPolicy>[],
  trusted = true,
  allowWorkspaceTasks = false,
) => ({
  isWorkspaceTrusted: () => trusted,
  readCommandPolicyConfiguration: () => ({ allowWorkspaceTasks, commands: [], tasks }),
});

const host = (
  tasks: readonly TaskCandidate<string>[],
  configurations: Readonly<Record<string, TaskConfigurationReadResult>> = {},
): TaskDiscoveryHost<string> => ({
  platform: 'win32',
  fetchTasks: () => Promise.resolve(tasks),
  readTaskConfiguration: (workspaceRoot) => Promise.resolve(
    configurations[workspaceRoot.alias] ?? { status: 'missing' },
  ),
});

const taskInput = (taskName: string, taskRoot?: string, timeoutMs?: number) => ({
  workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA',
  target: {
    kind: 'task' as const,
    taskName,
    ...(taskRoot === undefined ? {} : { taskRoot }),
  },
  ...(timeoutMs === undefined ? {} : { timeoutMs }),
});

const errorCode = (decision: TaskDiscoveryDecision<string>): string => {
  assert.equal(decision.ok, false);
  return decision.ok ? 'unexpected-success' : decision.error.code;
};

test('trusted workspace foreground tasks and dependencies are authorized by default', async () => {
  const tasks = [
    candidate(appRoot.lexicalAbsolutePath, 'build'),
    candidate(appRoot.lexicalAbsolutePath, 'compile'),
  ];
  const executor = new TaskDiscoveryPreflight(
    host(tasks, {
      app: {
        status: 'loaded',
        text: '{ "tasks": [{ "label": "build", "dependsOn": "compile" }, { "label": "compile" }] }',
      },
    }),
    policyHost([], true, true),
  );
  const decision = await executor.check(context, taskInput('build', 'app', 90_000));
  assert.equal(decision.ok, true);
  if (decision.ok) {
    assert.deepEqual(decision.plan.nodes.map((node) => node.taskName), ['compile', 'build']);
    assert.equal(decision.plan.effectiveTimeoutMs, 90_000);
  }
});

test('task discovery builds a bounded dependency DAG from JSONC and exact allowlist entries', async () => {
  const tasks = [
    candidate(appRoot.lexicalAbsolutePath, 'build'),
    candidate(appRoot.lexicalAbsolutePath, 'compile'),
    candidate(appRoot.lexicalAbsolutePath, 'lint'),
  ];
  const configuration = `{
    // VS Code Task API does not expose dependsOn, so retain this source.
    "tasks": [
      { "label": "build", "dependsOn": ["compile", "lint"], },
      { "label": "compile" },
      { "label": "lint" },
    ],
    "inputs": [],
  }`;
  const executor = new TaskDiscoveryPreflight(
    host(tasks, { app: { status: 'loaded', text: configuration } }),
    policyHost([
      taskPolicy('app', 'build', true, 30_000),
      taskPolicy('app', 'compile', false, 20_000),
      taskPolicy('app', 'lint', false, 15_000),
    ]),
  );
  const decision = await executor.check(context, taskInput('build', 'app', 25_000));
  assert.equal(decision.ok, true);
  if (!decision.ok) return;
  assert.equal(decision.plan.rootKey, 'app\u0000build');
  assert.equal(decision.plan.effectiveTimeoutMs, 15_000);
  assert.deepEqual(decision.plan.nodes.map((node) => node.taskName), ['compile', 'lint', 'build']);
  assert.deepEqual(decision.plan.nodes.at(-1)?.dependencies, [
    'app\u0000compile',
    'app\u0000lint',
  ]);
});

test('multi-root selection never chooses the first duplicate and accepts an exact root alias', async () => {
  const tasks = [
    candidate(appRoot.lexicalAbsolutePath, 'build'),
    candidate(libRoot.lexicalAbsolutePath, 'build'),
  ];
  const executor = new TaskDiscoveryPreflight(
    host(tasks),
    policyHost([taskPolicy('app', 'build'), taskPolicy('lib', 'build')]),
  );
  assert.equal(errorCode(await executor.check(context, taskInput('build'))), 'INVALID_ARGUMENT');
  const selected = await executor.check(context, taskInput('build', 'lib'));
  assert.equal(selected.ok, true);
  if (selected.ok) assert.equal(selected.plan.rootKey, 'lib\u0000build');
  assert.equal(errorCode(await executor.check(context, taskInput('build', 'missing'))), 'ROOT_NOT_FOUND');
});

test('an omitted root is accepted only when the task name is workspace-unique', async () => {
  const executor = new TaskDiscoveryPreflight(
    host([candidate(libRoot.lexicalAbsolutePath, 'test')]),
    policyHost([taskPolicy('lib', 'test')]),
  );
  const decision = await executor.check(context, taskInput('test'));
  assert.equal(decision.ok, true);
  if (decision.ok) assert.equal(decision.plan.rootKey, 'lib\u0000test');
});

test('dependency cycles and missing or ambiguous nodes fail without unbounded traversal', async () => {
  const cycle = `{
    "tasks": [
      { "label": "a", "dependsOn": "b" },
      { "label": "b", "dependsOn": "a" }
    ]
  }`;
  const cycleExecutor = new TaskDiscoveryPreflight(
    host([
      candidate(appRoot.lexicalAbsolutePath, 'a'),
      candidate(appRoot.lexicalAbsolutePath, 'b'),
    ], { app: { status: 'loaded', text: cycle } }),
    policyHost([taskPolicy('app', 'a', true), taskPolicy('app', 'b', true)]),
  );
  const cycleDecision = await cycleExecutor.check(context, taskInput('a', 'app'));
  assert.equal(errorCode(cycleDecision), 'COMMAND_FAILED');

  const missingExecutor = new TaskDiscoveryPreflight(
    host([candidate(appRoot.lexicalAbsolutePath, 'a')], {
      app: { status: 'loaded', text: '{ "tasks": [{ "label": "a", "dependsOn": "b" }] }' },
    }),
    policyHost([taskPolicy('app', 'a', true), taskPolicy('app', 'b')]),
  );
  assert.equal(
    errorCode(await missingExecutor.check(context, taskInput('a', 'app'))),
    'COMMAND_FAILED',
  );

  const duplicateExecutor = new TaskDiscoveryPreflight(
    host([
      candidate(appRoot.lexicalAbsolutePath, 'a', { handle: 'first' }),
      candidate(appRoot.lexicalAbsolutePath, 'a', { handle: 'second' }),
    ]),
    policyHost([taskPolicy('app', 'a')]),
  );
  assert.equal(
    errorCode(await duplicateExecutor.check(context, taskInput('a', 'app'))),
    'INVALID_ARGUMENT',
  );
});

test('platform overrides are authoritative and API/config dependency disagreement fails closed', async () => {
  const tasks = [
    candidate(appRoot.lexicalAbsolutePath, 'build'),
    candidate(appRoot.lexicalAbsolutePath, 'windows-build'),
  ];
  const overridden = new TaskDiscoveryPreflight(
    host(tasks, {
      app: {
        status: 'loaded',
        text: `{
          "tasks": [{
            "label": "build",
            "dependsOn": "portable-build",
            "windows": { "dependsOn": "windows-build" }
          }, { "label": "windows-build" }]
        }`,
      },
    }),
    policyHost([
      taskPolicy('app', 'build', true),
      taskPolicy('app', 'windows-build'),
    ]),
  );
  const accepted = await overridden.check(context, taskInput('build', 'app'));
  assert.equal(accepted.ok, true);
  if (accepted.ok) {
    assert.deepEqual(accepted.plan.nodes.at(-1)?.dependencies, ['app\u0000windows-build']);
  }

  const disagreement = new TaskDiscoveryPreflight(
    host([
      candidate(appRoot.lexicalAbsolutePath, 'build', {
        definition: { type: 'shell', dependsOn: 'api-build' },
      }),
      candidate(appRoot.lexicalAbsolutePath, 'config-build'),
      candidate(appRoot.lexicalAbsolutePath, 'api-build'),
    ], {
      app: {
        status: 'loaded',
        text: '{ "tasks": [{ "label": "build", "dependsOn": "config-build" }] }',
      },
    }),
    policyHost([
      taskPolicy('app', 'build', true),
      taskPolicy('app', 'config-build'),
      taskPolicy('app', 'api-build'),
    ]),
  );
  assert.equal(
    errorCode(await disagreement.check(context, taskInput('build', 'app'))),
    'COMMAND_FAILED',
  );
});

test('every dependency must be allowlisted and dependency permission is explicit', async () => {
  const tasks = [
    candidate(appRoot.lexicalAbsolutePath, 'build'),
    candidate(appRoot.lexicalAbsolutePath, 'compile'),
  ];
  const config = {
    app: {
      status: 'loaded' as const,
      text: '{ "tasks": [{ "label": "build", "dependsOn": "compile" }, { "label": "compile" }] }',
    },
  };
  const dependencyNotAllowed = new TaskDiscoveryPreflight(
    host(tasks, config),
    policyHost([taskPolicy('app', 'build', true)]),
  );
  assert.equal(
    errorCode(await dependencyNotAllowed.check(context, taskInput('build', 'app'))),
    'COMMAND_NOT_ALLOWED',
  );
  const dependenciesDisabled = new TaskDiscoveryPreflight(
    host(tasks, config),
    policyHost([taskPolicy('app', 'build'), taskPolicy('app', 'compile')]),
  );
  assert.equal(
    errorCode(await dependenciesDisabled.check(context, taskInput('build', 'app'))),
    'COMMAND_NOT_ALLOWED',
  );
});

test('variables in Task.definition, execution fields, raw configuration, and inputs reject before run', async () => {
  const cases: readonly {
    readonly task: TaskCandidate<string>;
    readonly text?: string;
    readonly reason: 'inputVariable' | 'commandVariable';
  }[] = [
    {
      task: candidate(appRoot.lexicalAbsolutePath, 'build', {
        definition: { type: 'shell', option: '${input:target}' },
      }),
      reason: 'inputVariable',
    },
    {
      task: candidate(appRoot.lexicalAbsolutePath, 'build', {
        execution: processExecution({ args: ['${command:resolveTarget}'] }),
      }),
      reason: 'commandVariable',
    },
    {
      task: candidate(appRoot.lexicalAbsolutePath, 'build'),
      text: '{ "tasks": [{ "label": "build", "options": { "cwd": "${input:cwd}" } }] }',
      reason: 'inputVariable',
    },
    {
      task: candidate(appRoot.lexicalAbsolutePath, 'build'),
      text: '{ "tasks": [{ "label": "build" }], "inputs": [{ "value": "${command:pick}" }] }',
      reason: 'commandVariable',
    },
  ];
  for (const current of cases) {
    const executor = new TaskDiscoveryPreflight(
      host([current.task], current.text === undefined
        ? {}
        : { app: { status: 'loaded', text: current.text } }),
      policyHost([taskPolicy('app', 'build')]),
    );
    const decision = await executor.check(context, taskInput('build', 'app'));
    assert.equal(decision.ok, false);
    if (!decision.ok) {
      assert.equal(decision.error.code, 'INTERACTIVE_COMMAND');
      if (decision.error.code === 'INTERACTIVE_COMMAND') {
        assert.equal(decision.error.details.reason, current.reason);
      }
    }
  }
});

test('an interactive variable in a dependency task rejects the whole DAG before start', async () => {
  const executor = new TaskDiscoveryPreflight(
    host([
      candidate(appRoot.lexicalAbsolutePath, 'build'),
      candidate(appRoot.lexicalAbsolutePath, 'compile', {
        execution: {
          kind: 'shell',
          commandLine: 'compile ${input:profile}',
        },
      }),
    ], {
      app: {
        status: 'loaded',
        text: '{ "tasks": [{ "label": "build", "dependsOn": "compile" }, { "label": "compile" }] }',
      },
    }),
    policyHost([
      taskPolicy('app', 'build', true),
      taskPolicy('app', 'compile'),
    ]),
  );
  const decision = await executor.check(context, taskInput('build', 'app'));
  assert.equal(decision.ok, false);
  if (!decision.ok) {
    assert.equal(decision.error.code, 'INTERACTIVE_COMMAND');
    if (decision.error.code === 'INTERACTIVE_COMMAND') {
      assert.equal(decision.error.details.reason, 'inputVariable');
    }
  }
});

test('background, CustomExecution, and missing execution are rejected before task start', async () => {
  const cases = [
    [candidate(appRoot.lexicalAbsolutePath, 'build', { isBackground: true }), 'INTERACTIVE_COMMAND'],
    [candidate(appRoot.lexicalAbsolutePath, 'build', { execution: { kind: 'custom' } }),
      'INTERACTIVE_COMMAND'],
    [candidate(appRoot.lexicalAbsolutePath, 'build', { execution: { kind: 'missing' } }),
      'COMMAND_FAILED'],
  ] as const;
  for (const [task, expected] of cases) {
    const executor = new TaskDiscoveryPreflight(
      host([task]),
      policyHost([taskPolicy('app', 'build')]),
    );
    assert.equal(errorCode(await executor.check(context, taskInput('build', 'app'))), expected);
  }
});

test('untrusted, malformed, cancelled, and unreadable preflight inputs stay not-started', async () => {
  const task = candidate(appRoot.lexicalAbsolutePath, 'build');
  const untrusted = new TaskDiscoveryPreflight(host([task]), policyHost([
    taskPolicy('app', 'build'),
  ], false));
  assert.equal(errorCode(await untrusted.check(context, taskInput('build', 'app'))),
    'INTERACTIVE_COMMAND');

  const unreadable = new TaskDiscoveryPreflight(host([task], {
    app: { status: 'failed', issue: 'permissionDenied' },
  }), policyHost([taskPolicy('app', 'build')]));
  assert.equal(errorCode(await unreadable.check(context, taskInput('build', 'app'))),
    'COMMAND_FAILED');

  const controller = new AbortController();
  controller.abort();
  const cancelled = new TaskDiscoveryPreflight(host([task]), policyHost([
    taskPolicy('app', 'build'),
  ]));
  assert.equal(errorCode(await cancelled.check(context, taskInput('build', 'app'), controller.signal)),
    'COMMAND_FAILED');
});

test('VS Code host maps public Task executions and reads only the selected root tasks.json', async () => {
  class FakeProcessExecution {
    constructor(
      readonly process: string,
      readonly args: string[],
      readonly options?: unknown,
    ) {}
  }
  class FakeShellExecution {
    readonly commandLine: string | undefined;
    readonly command: string | undefined;
    readonly args: string[] | undefined;
    readonly options: unknown;
    constructor(commandLine: string) {
      this.commandLine = commandLine;
      this.command = undefined;
      this.args = undefined;
      this.options = undefined;
    }
  }
  class FakeCustomExecution {}
  class FakeFileSystemError extends Error {
    constructor(readonly code: string) {
      super(code);
    }
  }
  const folder = { uri: { scheme: 'file', fsPath: appRoot.lexicalAbsolutePath } };
  const uriReads: string[] = [];
  const vscode = {
    ProcessExecution: FakeProcessExecution,
    ShellExecution: FakeShellExecution,
    CustomExecution: FakeCustomExecution,
    FileSystemError: FakeFileSystemError,
    TaskScope: { Global: 1, Workspace: 2 },
    Uri: {
      file: (value: string) => ({ value }),
      joinPath: (base: { value: string }, ...parts: string[]) => ({
        value: [base.value, ...parts].join('/'),
      }),
    },
    tasks: {
      fetchTasks: () => Promise.resolve([
        {
          name: 'process', scope: folder, definition: { type: 'process' },
          execution: new FakeProcessExecution('node', ['build'], { cwd: 'src' }),
          isBackground: false,
        },
        {
          name: 'shell', scope: folder, definition: { type: 'shell' },
          execution: new FakeShellExecution('npm test'), isBackground: false,
        },
        {
          name: 'custom', scope: folder, definition: { type: 'custom' },
          execution: new FakeCustomExecution(), isBackground: false,
        },
      ]),
    },
    workspace: {
      fs: {
        readFile: (uri: { value: string }) => {
          uriReads.push(uri.value);
          return Promise.resolve(new TextEncoder().encode('{ "tasks": [] }'));
        },
      },
    },
  };
  const vscodeHost = createVscodeTaskDiscoveryHost(vscode as never);
  const mapped = await vscodeHost.fetchTasks();
  assert.deepEqual(mapped.map((task) => task.execution.kind), ['process', 'shell', 'custom']);
  assert.equal(mapped[0]?.scopePath, appRoot.lexicalAbsolutePath);
  const config = await vscodeHost.readTaskConfiguration(appRoot);
  assert.equal(config.status, 'loaded');
  assert.deepEqual(uriReads, ['C:\\workspace\\app/.vscode/tasks.json']);
});
