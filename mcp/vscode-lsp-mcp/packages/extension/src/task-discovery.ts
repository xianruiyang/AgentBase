import type { Task } from 'vscode';
import {
  CommandPolicy,
  CommandPolicyConfigurationError,
  toPathComparisonKey,
  type ExecuteCommandInput,
  type InternalWorkspaceRoot,
  type TaskTarget,
  type ToolError,
  type WorkspacePathContext,
} from '@simplechat/vscode-lsp-mcp-protocol';
import type { CommandPolicyHost } from './command-policy-provider.js';
import {
  MAX_TASK_CONFIGURATION_CHARS,
  parseTaskJsonc,
} from './task-jsonc.js';

export type TaskExecutionInspection =
  | {
      readonly kind: 'process';
      readonly process: string;
      readonly args: readonly string[];
      readonly options?: unknown;
    }
  | {
      readonly kind: 'shell';
      readonly commandLine?: string;
      readonly command?: unknown;
      readonly args?: readonly unknown[];
      readonly options?: unknown;
    }
  | { readonly kind: 'custom' | 'missing' | 'unknown' };

export interface TaskCandidate<TTask = unknown> {
  readonly handle: TTask;
  readonly name: string;
  readonly scopeKind: 'folder' | 'workspace' | 'global' | 'unknown';
  readonly scopePath?: string;
  readonly definition: unknown;
  readonly execution: TaskExecutionInspection;
  readonly isBackground: boolean;
}

export type TaskConfigurationReadResult =
  | { readonly status: 'missing' }
  | { readonly status: 'loaded'; readonly text: string }
  | { readonly status: 'failed'; readonly issue: string };

export interface TaskDiscoveryHost<TTask = unknown> {
  readonly platform: 'win32';
  fetchTasks(): PromiseLike<readonly TaskCandidate<TTask>[]>;
  readTaskConfiguration(root: InternalWorkspaceRoot): PromiseLike<TaskConfigurationReadResult>;
}

export interface TaskPlanNode<TTask = unknown> {
  readonly key: string;
  readonly rootAlias: string;
  readonly taskName: string;
  readonly task: TTask;
  readonly dependencies: readonly string[];
}

export interface TaskDiscoveryPlan<TTask = unknown> {
  readonly rootKey: string;
  readonly nodes: readonly TaskPlanNode<TTask>[];
  readonly effectiveTimeoutMs: number;
}

export interface TaskDiscoveryDenied {
  readonly ok: false;
  readonly error: ToolError;
  readonly issue?: string;
}

export type TaskDiscoveryDecision<TTask = unknown> =
  | { readonly ok: true; readonly plan: TaskDiscoveryPlan<TTask> }
  | TaskDiscoveryDenied;

interface RootedTask<TTask> {
  readonly candidate: TaskCandidate<TTask>;
  readonly root: InternalWorkspaceRoot;
  readonly key: string;
}

interface ParsedTaskConfiguration {
  readonly tasksByLabel: ReadonlyMap<string, readonly Record<string, unknown>[]>;
  readonly inputs?: unknown;
}

interface DependencySpec {
  readonly present: boolean;
  readonly names: readonly string[];
}

type VariableScan = 'inputVariable' | 'commandVariable' | 'tooComplex' | undefined;

const taskKey = (rootAlias: string, taskName: string): string => `${rootAlias}\u0000${taskName}`;

const fail = (error: ToolError, issue?: string): TaskDiscoveryDenied => Object.freeze({
  ok: false,
  error: Object.freeze(error),
  ...(issue === undefined ? {} : { issue }),
});

const notAllowed = (message = 'The task is not authorized by the effective execution policy.'): TaskDiscoveryDenied =>
  fail({ code: 'COMMAND_NOT_ALLOWED', message, retryable: false });

const invalidArgument = (message: string): TaskDiscoveryDenied => fail({
  code: 'INVALID_ARGUMENT',
  message,
  retryable: false,
});

const completionUnverifiable = (message: string, issue?: string): TaskDiscoveryDenied => fail({
  code: 'COMMAND_FAILED',
  message,
  retryable: false,
  details: Object.freeze({
    targetKind: 'task',
    reason: 'completionUnverifiable',
    outcome: 'notStarted',
  }),
}, issue);

const interactive = (
  reason: 'inputVariable' | 'commandVariable' | 'workspaceTrust' | 'customExecution' |
    'backgroundTask' | 'unknownInteractivity',
  message: string,
): TaskDiscoveryDenied => fail({
  code: 'INTERACTIVE_COMMAND',
  message,
  retryable: false,
  details: Object.freeze({ targetKind: 'task', reason }),
});

const asRecord = (value: unknown, label: string): Record<string, unknown> => {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object.`);
  }
  return value as Record<string, unknown>;
};

const parseTaskConfiguration = (text: string): ParsedTaskConfiguration => {
  const document = asRecord(parseTaskJsonc(text), 'tasks.json');
  const tasksValue = document.tasks ?? [];
  if (!Array.isArray(tasksValue)) throw new TypeError('tasks.json.tasks must be an array.');
  if (document.inputs !== undefined && !Array.isArray(document.inputs)) {
    throw new TypeError('tasks.json.inputs must be an array when present.');
  }
  const byLabel = new Map<string, Record<string, unknown>[]>();
  for (let index = 0; index < tasksValue.length; index += 1) {
    const task = asRecord(tasksValue[index], `tasks.json.tasks[${index}]`);
    const label = task.label ?? task.taskName;
    if (label === undefined) continue;
    if (typeof label !== 'string' || label.length === 0 || label.length > 512) {
      throw new TypeError(`tasks.json.tasks[${index}] has an invalid label.`);
    }
    const current = byLabel.get(label) ?? [];
    current.push(task);
    byLabel.set(label, current);
  }
  return Object.freeze({
    tasksByLabel: new Map([...byLabel].map(([label, tasks]) =>
      [label, Object.freeze([...tasks])] as const)),
    ...(document.inputs === undefined ? {} : { inputs: document.inputs }),
  });
};

const dependenciesFrom = (value: unknown, label: string): DependencySpec => {
  if (value === undefined) return Object.freeze({ present: false, names: Object.freeze([]) });
  const values = typeof value === 'string' ? [value] : value;
  if (!Array.isArray(values) || values.some((item) =>
    typeof item !== 'string' || item.length === 0 || item.length > 512)) {
    throw new TypeError(`${label} must be a task name or an array of task names.`);
  }
  const names = values as string[];
  if (new Set(names).size !== names.length) {
    throw new TypeError(`${label} contains duplicate task dependencies.`);
  }
  return Object.freeze({ present: true, names: Object.freeze([...names]) });
};

const sameNames = (left: readonly string[], right: readonly string[]): boolean =>
  left.length === right.length && left.every((name, index) => name === right[index]);

const effectiveConfiguration = (
  raw: Record<string, unknown> | undefined,
): Record<string, unknown> | undefined => {
  if (raw === undefined) return undefined;
  const overrideName = 'windows';
  const override = raw[overrideName];
  if (override === undefined) return raw;
  return Object.freeze({ ...raw, ...asRecord(override, `task.${overrideName}`) });
};

const scanVariables = (
  values: readonly unknown[],
  seen = new Set<object>(),
): VariableScan => {
  let nodes = 0;
  const visit = (value: unknown, depth: number): VariableScan => {
    if (depth > 64 || ++nodes > 100_000) return 'tooComplex';
    if (typeof value === 'string') {
      if (/\$\{input:[^}]+\}/u.test(value)) return 'inputVariable';
      if (/\$\{command:[^}]+\}/u.test(value)) return 'commandVariable';
      return undefined;
    }
    if (value === null || typeof value !== 'object') return undefined;
    if (seen.has(value)) return 'tooComplex';
    seen.add(value);
    let nestedValues: readonly unknown[];
    try {
      nestedValues = Array.isArray(value) ? value : Object.values(value);
    } catch {
      return 'tooComplex';
    }
    for (const nested of nestedValues) {
      const result = visit(nested, depth + 1);
      if (result !== undefined) return result;
    }
    seen.delete(value);
    return undefined;
  };
  for (const value of values) {
    const result = visit(value, 0);
    if (result !== undefined) return result;
  }
  return undefined;
};

const rootForCandidate = <TTask>(
  candidate: TaskCandidate<TTask>,
  context: WorkspacePathContext,
): InternalWorkspaceRoot | undefined => {
  if (candidate.scopeKind !== 'folder' || candidate.scopePath === undefined) return undefined;
  let key: string;
  try {
    key = toPathComparisonKey(candidate.scopePath);
  } catch {
    return undefined;
  }
  return context.roots.find((root) => root.lexicalComparisonKey === key);
};

const groupTasks = <TTask>(
  candidates: readonly TaskCandidate<TTask>[],
  context: WorkspacePathContext,
): ReadonlyMap<string, readonly RootedTask<TTask>[]> => {
  const grouped = new Map<string, RootedTask<TTask>[]>();
  for (const candidate of candidates) {
    const root = rootForCandidate(candidate, context);
    if (root === undefined || candidate.name.length === 0 || candidate.name.length > 512) continue;
    const key = taskKey(root.alias, candidate.name);
    const current = grouped.get(key) ?? [];
    current.push(Object.freeze({ candidate, root, key }));
    grouped.set(key, current);
  }
  return new Map([...grouped].map(([key, values]) => [key, Object.freeze(values)] as const));
};

const selectRootTask = <TTask>(
  target: TaskTarget,
  context: WorkspacePathContext,
  grouped: ReadonlyMap<string, readonly RootedTask<TTask>[]>,
): RootedTask<TTask> | TaskDiscoveryDenied => {
  if (target.taskRoot !== undefined) {
    const root = context.roots.find((candidate) => candidate.alias === target.taskRoot);
    if (root === undefined) {
      return fail({
        code: 'ROOT_NOT_FOUND',
        message: 'The requested task root alias does not exist in this workspace.',
        retryable: false,
      });
    }
    const candidates = grouped.get(taskKey(root.alias, target.taskName)) ?? [];
    if (candidates.length === 0) {
      return completionUnverifiable('The requested task could not be discovered in its root.');
    }
    if (candidates.length !== 1) {
      return invalidArgument('The requested task name is ambiguous within its root.');
    }
    return candidates[0]!;
  }
  const candidates = [...grouped.values()].flat().filter((candidate) =>
    candidate.candidate.name === target.taskName);
  if (candidates.length === 0) {
    return completionUnverifiable('The requested task could not be discovered.');
  }
  if (candidates.length !== 1) {
    return invalidArgument('taskRoot is required because the task name is not workspace-unique.');
  }
  return candidates[0]!;
};

const isDenied = <TTask>(
  value: RootedTask<TTask> | TaskDiscoveryDenied,
): value is TaskDiscoveryDenied => 'ok' in value && value.ok === false;

const isAborted = (signal: AbortSignal | undefined): boolean => signal?.aborted === true;

export class TaskDiscoveryPreflight<TTask = unknown> {
  readonly #host: TaskDiscoveryHost<TTask>;
  readonly #policyHost: CommandPolicyHost;

  constructor(host: TaskDiscoveryHost<TTask>, policyHost: CommandPolicyHost) {
    this.#host = host;
    this.#policyHost = policyHost;
  }

  async check(
    context: WorkspacePathContext,
    input: ExecuteCommandInput,
    signal?: AbortSignal,
  ): Promise<TaskDiscoveryDecision<TTask>> {
    const target = input.target;
    if (target.kind !== 'task') return notAllowed('This preflight accepts task targets only.');
    if (isAborted(signal)) {
      return fail({
        code: 'COMMAND_FAILED',
        message: 'Task discovery was cancelled before the target started.',
        retryable: false,
        details: Object.freeze({ targetKind: 'task', reason: 'cancelled', outcome: 'notStarted' }),
      });
    }
    let policy: CommandPolicy;
    let trusted: boolean;
    try {
      policy = new CommandPolicy(this.#policyHost.readCommandPolicyConfiguration());
      trusted = this.#policyHost.isWorkspaceTrusted();
    } catch (error) {
      const issue = error instanceof CommandPolicyConfigurationError || error instanceof Error
        ? error.message
        : 'Invalid task policy configuration.';
      return fail({
        code: 'COMMAND_NOT_ALLOWED',
        message: 'The command policy configuration is invalid, so task execution is disabled.',
        retryable: false,
      }, issue);
    }
    if (!trusted) {
      return interactive('workspaceTrust', 'The workspace is not trusted, so task discovery is closed.');
    }
    if (target.taskRoot !== undefined &&
        !context.roots.some((root) => root.alias === target.taskRoot)) {
      return fail({
        code: 'ROOT_NOT_FOUND',
        message: 'The requested task root alias does not exist in this workspace.',
        retryable: false,
      });
    }
    const potentiallyAllowed = policy.configuration.allowWorkspaceTasks ||
      policy.configuration.tasks.some((entry) =>
        entry.taskName === target.taskName &&
        (target.taskRoot === undefined || entry.rootAlias === target.taskRoot));
    if (!potentiallyAllowed) return notAllowed();

    let discovered: readonly TaskCandidate<TTask>[];
    try {
      discovered = await this.#host.fetchTasks();
    } catch {
      return completionUnverifiable('VS Code task discovery failed before the target started.');
    }
    if (isAborted(signal)) {
      return fail({
        code: 'COMMAND_FAILED',
        message: 'Task discovery was cancelled before the target started.',
        retryable: false,
        details: Object.freeze({ targetKind: 'task', reason: 'cancelled', outcome: 'notStarted' }),
      });
    }
    const grouped = groupTasks(discovered, context);
    const selected = selectRootTask(target, context, grouped);
    if (isDenied(selected)) return selected;
    if (policy.taskEntry(selected.root.alias, selected.candidate.name) === undefined) {
      return notAllowed();
    }

    let configuration: ParsedTaskConfiguration = Object.freeze({
      tasksByLabel: new Map<string, readonly Record<string, unknown>[]>(),
    });
    let readResult: TaskConfigurationReadResult;
    try {
      readResult = await this.#host.readTaskConfiguration(selected.root);
    } catch {
      return completionUnverifiable('The task configuration could not be read safely.');
    }
    if (readResult.status === 'failed') {
      return completionUnverifiable('The task configuration could not be read safely.', readResult.issue);
    }
    if (readResult.status === 'loaded') {
      try {
        configuration = parseTaskConfiguration(readResult.text);
      } catch (error) {
        return completionUnverifiable(
          'The task configuration could not be parsed without ambiguity.',
          error instanceof Error ? error.message : undefined,
        );
      }
    }

    const states = new Map<string, 'visiting' | 'done'>();
    const nodes: TaskPlanNode<TTask>[] = [];
    const timeoutCaps: number[] = [input.timeoutMs ?? 120_000];

    const visit = (task: RootedTask<TTask>): TaskDiscoveryDenied | undefined => {
      const state = states.get(task.key);
      if (state === 'done') return undefined;
      if (state === 'visiting') {
        return completionUnverifiable('The task dependency graph contains a cycle.');
      }
      const matching = grouped.get(task.key) ?? [];
      if (matching.length !== 1) {
        return completionUnverifiable('A task dependency is missing or ambiguous.');
      }
      const entry = policy.taskEntry(task.root.alias, task.candidate.name);
      if (entry === undefined) return notAllowed('A task dependency is not authorized.');
      if (task.candidate.isBackground) {
        return interactive('backgroundTask', 'Background tasks are not safely completion-verifiable.');
      }
      if (task.candidate.execution.kind === 'custom') {
        return interactive('customExecution', 'CustomExecution tasks are not allowed.');
      }
      if (task.candidate.execution.kind === 'missing' ||
          task.candidate.execution.kind === 'unknown') {
        return completionUnverifiable('The task has no supported ProcessExecution or ShellExecution.');
      }
      const rawMatches = configuration.tasksByLabel.get(task.candidate.name) ?? [];
      if (rawMatches.length > 1) {
        return completionUnverifiable('The task configuration contains duplicate task labels.');
      }
      let effectiveRaw: Record<string, unknown> | undefined;
      try {
        effectiveRaw = effectiveConfiguration(rawMatches[0]);
      } catch (error) {
        return completionUnverifiable(
          'The platform-specific task configuration is malformed.',
          error instanceof Error ? error.message : undefined,
        );
      }
      const variable = scanVariables([
        task.candidate.definition,
        task.candidate.execution,
        ...(effectiveRaw === undefined ? [] : [effectiveRaw]),
        ...(configuration.inputs === undefined ? [] : [configuration.inputs]),
      ]);
      if (variable === 'inputVariable' || variable === 'commandVariable') {
        return interactive(variable, 'The task or its configuration contains an interactive variable.');
      }
      if (variable === 'tooComplex') {
        return interactive(
          'unknownInteractivity',
          'The task configuration is too complex to prove non-interactive.',
        );
      }
      let definitionDependencies: DependencySpec;
      let configurationDependencies: DependencySpec;
      try {
        definitionDependencies = dependenciesFrom(
          asRecord(task.candidate.definition, 'Task.definition').dependsOn,
          'Task.definition.dependsOn',
        );
        configurationDependencies = dependenciesFrom(
          effectiveRaw?.dependsOn,
          'tasks.json task.dependsOn',
        );
      } catch (error) {
        return completionUnverifiable(
          'The task dependency declaration is malformed.',
          error instanceof Error ? error.message : undefined,
        );
      }
      if (definitionDependencies.present && configurationDependencies.present &&
          !sameNames(definitionDependencies.names, configurationDependencies.names)) {
        return completionUnverifiable('Task API and tasks.json dependency declarations disagree.');
      }
      const dependencyNames = configurationDependencies.present
        ? configurationDependencies.names
        : definitionDependencies.names;
      if (dependencyNames.length > 0 && !entry.allowDependencies) {
        return notAllowed('The task policy entry does not permit dependencies.');
      }
      states.set(task.key, 'visiting');
      const dependencyKeys: string[] = [];
      for (const dependencyName of dependencyNames) {
        const key = taskKey(task.root.alias, dependencyName);
        const candidates = grouped.get(key) ?? [];
        if (candidates.length !== 1) {
          return completionUnverifiable('A task dependency is missing or ambiguous.');
        }
        dependencyKeys.push(key);
        const denied = visit(candidates[0]!);
        if (denied !== undefined) return denied;
      }
      states.set(task.key, 'done');
      timeoutCaps.push(entry.maxTimeoutMs);
      nodes.push(Object.freeze({
        key: task.key,
        rootAlias: task.root.alias,
        taskName: task.candidate.name,
        task: task.candidate.handle,
        dependencies: Object.freeze(dependencyKeys),
      }));
      return undefined;
    };

    const denied = visit(selected);
    if (denied !== undefined) return denied;
    return Object.freeze({
      ok: true,
      plan: Object.freeze({
        rootKey: selected.key,
        nodes: Object.freeze(nodes),
        effectiveTimeoutMs: Math.min(...timeoutCaps),
      }),
    });
  }
}

const taskHostPlatform = (): TaskDiscoveryHost['platform'] => {
  if (process.platform === 'win32') {
    return 'win32';
  }
  throw new Error('Task discovery requires Windows.');
};

export const createVscodeTaskDiscoveryHost = (
  vscode: typeof import('vscode'),
): TaskDiscoveryHost<Task> => ({
  platform: taskHostPlatform(),
  fetchTasks: async () => (await vscode.tasks.fetchTasks()).map((task) => {
    const scopeKind = typeof task.scope === 'object'
      ? 'folder'
      : task.scope === vscode.TaskScope.Workspace
        ? 'workspace'
        : task.scope === vscode.TaskScope.Global ? 'global' : 'unknown';
    let execution: TaskExecutionInspection;
    if (task.execution instanceof vscode.ProcessExecution) {
      execution = Object.freeze({
        kind: 'process',
        process: task.execution.process,
        args: Object.freeze([...task.execution.args]),
        ...(task.execution.options === undefined ? {} : { options: task.execution.options }),
      });
    } else if (task.execution instanceof vscode.ShellExecution) {
      execution = Object.freeze({
        kind: 'shell',
        ...(task.execution.commandLine === undefined
          ? {}
          : { commandLine: task.execution.commandLine }),
        ...(task.execution.command === undefined ? {} : { command: task.execution.command }),
        ...(task.execution.args === undefined ? {} : { args: Object.freeze([...task.execution.args]) }),
        ...(task.execution.options === undefined ? {} : { options: task.execution.options }),
      });
    } else if (task.execution instanceof vscode.CustomExecution) {
      execution = Object.freeze({ kind: 'custom' });
    } else {
      execution = Object.freeze({ kind: task.execution === undefined ? 'missing' : 'unknown' });
    }
    return Object.freeze({
      handle: task,
      name: task.name,
      scopeKind,
      ...(typeof task.scope === 'object' && task.scope.uri.scheme === 'file'
        ? { scopePath: task.scope.uri.fsPath }
        : {}),
      definition: task.definition,
      execution,
      isBackground: task.isBackground,
    });
  }),
  readTaskConfiguration: async (root) => {
    const uri = vscode.Uri.joinPath(vscode.Uri.file(root.lexicalAbsolutePath), '.vscode', 'tasks.json');
    try {
      const bytes = await vscode.workspace.fs.readFile(uri);
      if (bytes.byteLength > MAX_TASK_CONFIGURATION_CHARS * 4) {
        return Object.freeze({ status: 'failed', issue: 'taskConfigurationTooLarge' });
      }
      return Object.freeze({
        status: 'loaded',
        text: new TextDecoder('utf-8', { fatal: true }).decode(bytes),
      });
    } catch (error) {
      if (error instanceof vscode.FileSystemError && error.code === 'FileNotFound') {
        return Object.freeze({ status: 'missing' });
      }
      return Object.freeze({
        status: 'failed',
        issue: error instanceof Error ? error.name : 'taskConfigurationReadFailed',
      });
    }
  },
});
