import path from 'node:path';
import type { Task, TaskExecution, TextDocument } from 'vscode';
import {
  canonicalizeJson,
  isDeferredLifecycleCommand,
  logicalPathFromProviderLocation,
  resolveLogicalPath,
  toPathComparisonKey,
  truncateUnicodeCodePoints,
  WorkspaceBoundaryError,
  type CommandResult,
  type CommandFailedDetails,
  type ExecuteCommandInput,
  type JsonValue,
  type PublicCommandResultValue,
  type TaskOutputLog,
  type ToolError,
  type ToolResponseMap,
  type WorkspacePathAccess,
  type WorkspacePathContext,
  type WorkspaceRouteIdentity,
} from '@simplechat/vscode-lsp-mcp-protocol';
import { resolveCommandArguments, type CommandArgumentUriFactory } from './command-arguments.js';
import { CommandPolicyPreflight } from './command-policy-provider.js';
import {
  TaskDiscoveryPreflight,
  type TaskDiscoveryPlan,
} from './task-discovery.js';
import {
  WorkspaceExclusiveMutationGate,
  type WorkspaceMutationLease,
} from './mutation-gate.js';
import {
  prepareVscodeTaskOutputCapture,
  type CommandTaskOutputCapture,
} from './task-output-capture.js';

export type { CommandTaskOutputCapture } from './task-output-capture.js';

export interface CommandExecutionDisposable {
  dispose(): void;
}

export interface CommandExecutionDocument {
  readonly uri: { readonly scheme: string; readonly fsPath: string };
  readonly isDirty: boolean;
  save(): PromiseLike<boolean>;
}

export interface CommandTaskStartEvent<TExecution> {
  readonly execution: TExecution;
}

export interface CommandTaskProcessEndEvent<TExecution> {
  readonly execution: TExecution;
  readonly exitCode: number | undefined;
}

export interface CommandExecutionHost<
  TTask = unknown,
  TExecution = unknown,
  TDocument extends CommandExecutionDocument = CommandExecutionDocument,
  TUri = unknown,
> {
  readonly uri: CommandArgumentUriFactory<TUri>;
  activeDocument(): TDocument | undefined;
  documents(): readonly TDocument[];
  executeCommand(commandId: string, args: readonly unknown[]): PromiseLike<unknown>;
  isTaskExecution(value: unknown): value is TExecution;
  activeTaskExecutions(): readonly TExecution[];
  executeTask(task: TTask): PromiseLike<TExecution>;
  prepareTaskOutputCapture(
    context: WorkspacePathContext,
    task: TTask,
    taskName: string,
  ): PromiseLike<CommandTaskOutputCapture<TTask> | undefined>;
  taskKey(context: WorkspacePathContext, execution: TExecution): string | undefined;
  terminateTask(execution: TExecution): void;
  onTaskStart(listener: (event: CommandTaskStartEvent<TExecution>) => void): CommandExecutionDisposable;
  onTaskProcessStart(
    listener: (event: CommandTaskStartEvent<TExecution>) => void,
  ): CommandExecutionDisposable;
  onTaskProcessEnd(
    listener: (event: CommandTaskProcessEndEvent<TExecution>) => void,
  ): CommandExecutionDisposable;
  onTaskEnd(listener: (event: CommandTaskStartEvent<TExecution>) => void): CommandExecutionDisposable;
}

export interface CommandExecutionRuntime {
  now(): number;
  setTimer(callback: () => void, milliseconds: number): unknown;
  clearTimer(handle: unknown): void;
}

const systemRuntime: CommandExecutionRuntime = Object.freeze({
  now: Date.now,
  setTimer: (callback: () => void, milliseconds: number) => setTimeout(callback, milliseconds),
  clearTimer: (handle: unknown) => clearTimeout(handle as NodeJS.Timeout),
});

type WaitResult<T> =
  | { readonly status: 'completed'; readonly value: T }
  | { readonly status: 'rejected'; readonly error: unknown }
  | { readonly status: 'timeout' }
  | { readonly status: 'cancelled' };

const waitUntil = <T>(
  operation: PromiseLike<T>,
  deadlineAt: number,
  signal: AbortSignal | undefined,
  runtime: CommandExecutionRuntime,
): Promise<WaitResult<T>> => new Promise((resolve) => {
  let settled = false;
  const timerRef: { handle: unknown } = { handle: undefined };
  const finish = (result: WaitResult<T>): void => {
    if (settled) return;
    settled = true;
    runtime.clearTimer(timerRef.handle);
    signal?.removeEventListener('abort', abort);
    resolve(result);
  };
  const abort = (): void => finish(Object.freeze({ status: 'cancelled' }));
  const remaining = Math.max(0, deadlineAt - runtime.now());
  timerRef.handle = runtime.setTimer(
    () => finish(Object.freeze({ status: 'timeout' })),
    remaining,
  );
  signal?.addEventListener('abort', abort, { once: true });
  if (signal?.aborted === true) {
    abort();
    return;
  }
  Promise.resolve(operation).then(
    (value) => finish(Object.freeze({ status: 'completed', value })),
    (error: unknown) => finish(Object.freeze({ status: 'rejected', error })),
  );
});

const success = (data: CommandResult = Object.freeze({})): ToolResponseMap['execute_command'] =>
  Object.freeze({ ok: true, data: Object.freeze(data) });

const failure = (error: ToolError): ToolResponseMap['execute_command'] => Object.freeze({
  ok: false,
  error: Object.freeze(error),
});

const failed = (
  targetKind: 'command' | 'task',
  reason: 'saveFailed' | 'rejected' | 'cancelled' | 'completionUnverifiable' | 'alreadyRunning',
  outcome: 'notStarted' | 'failed' | 'terminated' | 'unknown',
  message: string,
  action?: string,
  outputLog?: TaskOutputLog,
): ToolResponseMap['execute_command'] => {
  const details: CommandFailedDetails = targetKind === 'task'
    ? Object.freeze({
        targetKind,
        reason,
        outcome,
        ...(outputLog === undefined ? {} : { outputLog }),
      })
    : Object.freeze({ targetKind, reason, outcome });
  return failure({
    code: 'COMMAND_FAILED',
    message,
    retryable: false,
    ...(action === undefined ? {} : { action }),
    details,
  });
};

const timedOut = (
  targetKind: 'command' | 'task',
  timeoutMs: number,
  outcome: 'notStarted' | 'terminated' | 'unknown',
  outputLog?: TaskOutputLog,
): ToolResponseMap['execute_command'] => failure({
  code: 'COMMAND_TIMEOUT',
  message: 'The command did not complete within its effective timeout.',
  retryable: false,
  details: targetKind === 'command'
    ? Object.freeze({ targetKind, timeoutMs, outcome: outcome === 'notStarted' ? 'notStarted' : 'unknown' })
    : Object.freeze({
        targetKind,
        timeoutMs,
        outcome,
        ...(outputLog === undefined ? {} : { outputLog }),
      }),
});

const nonZero = (
  exitCode: number,
  outputLog?: TaskOutputLog,
): ToolResponseMap['execute_command'] => failure({
  code: 'COMMAND_FAILED',
  message: 'The task process exited with a non-zero status.',
  retryable: false,
  details: Object.freeze({
    targetKind: 'task',
    reason: 'nonZeroExit',
    outcome: 'failed',
    exitCode,
    ...(outputLog === undefined ? {} : { outputLog }),
  }),
});

const phaseFailure = (
  input: ExecuteCommandInput,
  result: Exclude<WaitResult<unknown>, { readonly status: 'completed' }>,
  effectiveTimeoutMs: number,
): ToolResponseMap['execute_command'] => {
  const kind = input.target.kind;
  if (result.status === 'timeout') return timedOut(kind, effectiveTimeoutMs, 'notStarted');
  if (result.status === 'cancelled') {
    return failed(kind, 'cancelled', 'notStarted', 'The command was cancelled before it started.');
  }
  return failed(kind, 'rejected', 'notStarted', 'Command preflight failed before invocation.');
};

const argumentFailure = (error: unknown): ToolResponseMap['execute_command'] => {
  if (error instanceof WorkspaceBoundaryError) {
    if (error.code === 'WORKSPACE_UNAVAILABLE') {
      return failure({
        code: 'WORKSPACE_NOT_FOUND',
        message: 'The selected workspace is unavailable for logical-path resolution.',
        retryable: true,
      });
    }
    return failure({
      code: error.code,
      message: error.message,
      retryable: false,
    });
  }
  return failure({
    code: 'COMMAND_NOT_ALLOWED',
    message: 'The authorized command argument schema could not be transformed safely.',
    retryable: false,
  });
};

const outputFrom = (value: unknown, maximumCodePoints: number): CommandResult => {
  if (value === undefined) return Object.freeze({});
  if (typeof value === 'string') {
    if (value.length === 0) return Object.freeze({});
    const truncated = truncateUnicodeCodePoints(value, maximumCodePoints);
    return Object.freeze({
      output: truncated.value,
      ...(truncated.truncated ? { outputTruncated: true as const } : {}),
    });
  }
  let canonical: JsonValue;
  let text: string;
  try {
    canonical = canonicalizeJson(value);
    text = JSON.stringify(canonical);
  } catch {
    return Object.freeze({
      warnings: Object.freeze(['The command returned a value that is not JSON-compatible; result was omitted.']),
    });
  }
  if ([...text].length > maximumCodePoints) {
    return Object.freeze({
      warnings: Object.freeze(['The command returned a JSON value larger than maxOutputChars; result was omitted.']),
    });
  }
  const publicValue = canonical === true ||
      (typeof canonical === 'number' && Number.isFinite(canonical)) ||
      (Array.isArray(canonical) && canonical.length > 0) ||
      (canonical !== null && typeof canonical === 'object' && Object.keys(canonical).length > 0)
    ? canonical as PublicCommandResultValue
    : undefined;
  return publicValue === undefined
    ? Object.freeze({
        warnings: Object.freeze(['The command returned a JSON value with no public result representation; result was omitted.']),
      })
    : Object.freeze({ result: publicValue });
};

const isInside = (root: string, target: string): string | undefined => {
  const api = path.win32;
  const relative = api.relative(root, target);
  return relative !== '' && !api.isAbsolute(relative) && relative !== '..' &&
      !relative.startsWith(`..${api.sep}`)
    ? relative
    : undefined;
};

const missingDocumentLogicalPath = async (
  context: WorkspacePathContext,
  absolutePath: string,
  access: WorkspacePathAccess,
): Promise<string | undefined> => {
  const api = path.win32;
  const candidates = context.roots.flatMap((root) => {
    const relative = isInside(root.lexicalAbsolutePath, absolutePath);
    return relative === undefined ? [] : [{ root, relative }];
  }).sort((left, right) => right.root.lexicalComparisonKey.length - left.root.lexicalComparisonKey.length);
  for (const candidate of candidates) {
    const relative = candidate.relative.split(api.sep).join('/');
    const logical = context.roots.length === 1 ? relative : `${candidate.root.alias}/${relative}`;
    try {
      await resolveLogicalPath(context, logical, access, { allowMissing: true });
      return logical;
    } catch {
      continue;
    }
  }
  return undefined;
};

const documentLogicalPath = async (
  context: WorkspacePathContext,
  document: CommandExecutionDocument,
  access: WorkspacePathAccess,
): Promise<string | undefined> => {
  if (document.uri.scheme !== 'file') return undefined;
  try {
    return (await logicalPathFromProviderLocation(context, {
      uriScheme: 'file',
      lexicalAbsolutePath: document.uri.fsPath,
    }, access)).logicalPath;
  } catch {
    return await missingDocumentLogicalPath(context, document.uri.fsPath, access);
  }
};

interface SaveCandidate<TDocument> {
  readonly document: TDocument;
  readonly logicalPath: string;
}

const saveBeforeRun = async <TDocument extends CommandExecutionDocument>(
  mode: 'none' | 'active' | 'all',
  context: WorkspacePathContext,
  host: Pick<CommandExecutionHost<unknown, unknown, TDocument>, 'activeDocument' | 'documents'>,
  access: WorkspacePathAccess,
  shouldContinue: () => boolean,
): Promise<boolean> => {
  if (mode === 'none') return true;
  const documents = mode === 'active'
    ? (() => {
        const active = host.activeDocument();
        return active === undefined ? [] : [active];
      })()
    : host.documents();
  const candidates: SaveCandidate<TDocument>[] = [];
  for (const document of documents) {
    if (!shouldContinue()) return false;
    if (!document.isDirty || document.uri.scheme !== 'file') continue;
    const logicalPath = await documentLogicalPath(context, document, access);
    if (logicalPath !== undefined) candidates.push({ document, logicalPath });
  }
  candidates.sort((left, right) => left.logicalPath < right.logicalPath ? -1 :
    left.logicalPath > right.logicalPath ? 1 : 0);
  for (const candidate of candidates) {
    if (!shouldContinue()) return false;
    if (!await candidate.document.save()) return false;
    if (!shouldContinue()) return false;
  }
  return true;
};

type TaskTerminal =
  | { readonly kind: 'success' }
  | { readonly kind: 'nonZero'; readonly exitCode: number }
  | { readonly kind: 'failed'; readonly reason: 'rejected' | 'completionUnverifiable' | 'alreadyRunning'; readonly outcome: 'notStarted' | 'failed' | 'unknown' };

interface TrackedExecution<TExecution> {
  readonly execution: TExecution;
  readonly key: string;
  readonly owned: boolean;
  started: boolean;
  processStarted: boolean;
  exitCode?: number;
  ended: boolean;
}

class TaskRunTracker<TTask, TExecution> {
  readonly #context: WorkspacePathContext;
  readonly #host: CommandExecutionHost<TTask, TExecution>;
  readonly #plan: TaskDiscoveryPlan<TTask>;
  readonly #planKeys: ReadonlySet<string>;
  readonly #byExecution = new Map<TExecution, TrackedExecution<TExecution>>();
  readonly #byKey = new Map<string, TrackedExecution<TExecution>>();
  readonly #disposables: CommandExecutionDisposable[] = [];
  readonly #terminal: Promise<TaskTerminal>;
  readonly #settled: Promise<void>;
  #resolveTerminal: (value: TaskTerminal) => void = () => undefined;
  #resolveSettled = (): void => undefined;
  #terminalValue: TaskTerminal | undefined;
  #dispatchSettled = false;
  #invoking = false;
  #disposed = false;

  constructor(
    context: WorkspacePathContext,
    plan: TaskDiscoveryPlan<TTask>,
    host: CommandExecutionHost<TTask, TExecution>,
  ) {
    this.#context = context;
    this.#plan = plan;
    this.#host = host;
    this.#planKeys = new Set(plan.nodes.map((node) => node.key));
    this.#terminal = new Promise((resolve) => { this.#resolveTerminal = resolve; });
    this.#settled = new Promise((resolve) => { this.#resolveSettled = resolve; });
  }

  get terminal(): Promise<TaskTerminal> { return this.#terminal; }
  get settled(): Promise<void> { return this.#settled; }

  start(): void {
    try {
      this.#disposables.push(
        this.#host.onTaskStart((event) => this.#onStart(event.execution)),
        this.#host.onTaskProcessStart((event) => this.#onProcessStart(event.execution)),
        this.#host.onTaskProcessEnd((event) => this.#onProcessEnd(event.execution, event.exitCode)),
        this.#host.onTaskEnd((event) => this.#onEnd(event.execution)),
      );
      for (const execution of this.#host.activeTaskExecutions()) {
        const key = this.#host.taskKey(this.#context, execution);
        if (key !== undefined && this.#planKeys.has(key)) {
          this.#track(execution, key, false).started = true;
        }
      }
    } catch {
      this.#dispatchSettled = true;
      this.#finish({ kind: 'failed', reason: 'completionUnverifiable', outcome: 'notStarted' });
      this.#checkSettled();
      return;
    }
    if (this.#byKey.size > 0) {
      this.#dispatchSettled = true;
      this.#finish({ kind: 'failed', reason: 'alreadyRunning', outcome: 'unknown' });
      this.#checkSettled();
      return;
    }
    const root = this.#plan.nodes.find((node) => node.key === this.#plan.rootKey);
    if (root === undefined) {
      this.#dispatchSettled = true;
      this.#finish({ kind: 'failed', reason: 'completionUnverifiable', outcome: 'notStarted' });
      this.#checkSettled();
      return;
    }
    this.#invoking = true;
    let invocation: Promise<TExecution>;
    try {
      invocation = Promise.resolve(this.#host.executeTask(root.task));
    } catch {
      this.#dispatchSettled = true;
      this.#finish({ kind: 'failed', reason: 'rejected', outcome: 'notStarted' });
      this.#checkSettled();
      return;
    }
    invocation.then(
      (execution) => {
        this.#dispatchSettled = true;
        const key = this.#host.taskKey(this.#context, execution);
        const tracked = this.#byExecution.get(execution);
        if (key !== this.#plan.rootKey || (tracked !== undefined && tracked.key !== key)) {
          this.#finish({ kind: 'failed', reason: 'completionUnverifiable', outcome: 'unknown' });
        } else if (tracked === undefined) {
          this.#track(execution, this.#plan.rootKey, true);
        }
        this.#checkSettled();
      },
      () => {
        this.#dispatchSettled = true;
        this.#finish({
          kind: 'failed',
          reason: 'rejected',
          outcome: this.#byExecution.size === 0 ? 'notStarted' : 'unknown',
        });
        this.#checkSettled();
      },
    );
  }

  terminateOwned(): void {
    for (const tracked of this.#byExecution.values()) {
      if (tracked.owned && !tracked.ended) {
        try { this.#host.terminateTask(tracked.execution); } catch { /* best effort */ }
      }
    }
  }

  allTrackedEnded(): boolean {
    return this.#dispatchSettled && [...this.#byExecution.values()].every((tracked) => tracked.ended);
  }

  #track(execution: TExecution, key: string, owned: boolean): TrackedExecution<TExecution> {
    const existingForExecution = this.#byExecution.get(execution);
    if (existingForExecution !== undefined) return existingForExecution;
    const existingForKey = this.#byKey.get(key);
    if (existingForKey !== undefined && existingForKey.execution !== execution) {
      this.#finish({ kind: 'failed', reason: 'alreadyRunning', outcome: 'unknown' });
      const duplicate: TrackedExecution<TExecution> = {
        execution,
        key,
        owned,
        started: false,
        processStarted: false,
        ended: false,
      };
      this.#byExecution.set(execution, duplicate);
      return duplicate;
    }
    const tracked: TrackedExecution<TExecution> = {
      execution,
      key,
      owned,
      started: false,
      processStarted: false,
      ended: false,
    };
    this.#byExecution.set(execution, tracked);
    this.#byKey.set(key, tracked);
    return tracked;
  }

  #eventExecution(execution: TExecution): TrackedExecution<TExecution> | undefined {
    const existing = this.#byExecution.get(execution);
    if (existing !== undefined) return existing;
    const key = this.#host.taskKey(this.#context, execution);
    if (!this.#invoking || key === undefined || !this.#planKeys.has(key)) return undefined;
    return this.#track(execution, key, true);
  }

  #onStart(execution: TExecution): void {
    const tracked = this.#eventExecution(execution);
    if (tracked !== undefined) tracked.started = true;
  }

  #onProcessStart(execution: TExecution): void {
    const tracked = this.#eventExecution(execution);
    if (tracked !== undefined) tracked.processStarted = true;
  }

  #onProcessEnd(execution: TExecution, exitCode: number | undefined): void {
    const tracked = this.#eventExecution(execution);
    if (tracked === undefined) return;
    if (!Number.isInteger(exitCode)) {
      this.#finish({ kind: 'failed', reason: 'completionUnverifiable', outcome: 'failed' });
      return;
    }
    const verifiedExitCode = exitCode as number;
    tracked.exitCode = verifiedExitCode;
    if (verifiedExitCode !== 0) this.#finish({ kind: 'nonZero', exitCode: verifiedExitCode });
  }

  #onEnd(execution: TExecution): void {
    const tracked = this.#eventExecution(execution);
    if (tracked === undefined) return;
    tracked.ended = true;
    if (tracked.exitCode === undefined) {
      this.#finish({ kind: 'failed', reason: 'completionUnverifiable', outcome: 'failed' });
    } else if (tracked.key === this.#plan.rootKey) {
      const complete = this.#plan.nodes.every((node) => {
        const state = this.#byKey.get(node.key);
        return state?.started === true && state.ended && state.exitCode === 0;
      });
      this.#finish(complete
        ? { kind: 'success' }
        : { kind: 'failed', reason: 'completionUnverifiable', outcome: 'failed' });
    }
    this.#checkSettled();
  }

  #finish(value: TaskTerminal): void {
    if (this.#terminalValue !== undefined) return;
    this.#terminalValue = value;
    this.#resolveTerminal(value);
    if (value.kind !== 'success') this.terminateOwned();
  }

  #checkSettled(): void {
    if (!this.allTrackedEnded() || this.#disposed) return;
    this.#disposed = true;
    for (const disposable of this.#disposables) disposable.dispose();
    this.#resolveSettled();
  }
}

interface ExecutorOptions<TTask> {
  readonly gate: WorkspaceExclusiveMutationGate;
  readonly pathAccess: WorkspacePathAccess;
  readonly policy: CommandPolicyPreflight;
  readonly taskDiscovery: TaskDiscoveryPreflight<TTask>;
  readonly runtime?: CommandExecutionRuntime;
}

export class CommandExecutionExecutor<
  TTask = unknown,
  TExecution = unknown,
  TDocument extends CommandExecutionDocument = CommandExecutionDocument,
  TUri = unknown,
> {
  readonly #host: CommandExecutionHost<TTask, TExecution, TDocument, TUri>;
  readonly #gate: WorkspaceExclusiveMutationGate;
  readonly #pathAccess: WorkspacePathAccess;
  readonly #policy: CommandPolicyPreflight;
  readonly #taskDiscovery: TaskDiscoveryPreflight<TTask>;
  readonly #runtime: CommandExecutionRuntime;

  constructor(
    host: CommandExecutionHost<TTask, TExecution, TDocument, TUri>,
    options: ExecutorOptions<TTask>,
  ) {
    this.#host = host;
    this.#gate = options.gate;
    this.#pathAccess = options.pathAccess;
    this.#policy = options.policy;
    this.#taskDiscovery = options.taskDiscovery;
    this.#runtime = options.runtime ?? systemRuntime;
  }

  async execute(
    context: WorkspacePathContext,
    workspace: WorkspaceRouteIdentity,
    input: ExecuteCommandInput,
    signal?: AbortSignal,
  ): Promise<ToolResponseMap['execute_command']> {
    const startedAt = this.#runtime.now();
    let effectiveTimeoutMs: number;
    let commandArguments: readonly unknown[] | undefined;
    let taskPlan: TaskDiscoveryPlan<TTask> | undefined;
    if (input.target.kind === 'command') {
      const decision = this.#policy.check(input);
      if (!decision.ok) return failure(decision.error);
      effectiveTimeoutMs = decision.effectiveTimeoutMs;
      const argumentResolution = await waitUntil(
        resolveCommandArguments(
          decision.arguments,
          decision.entry.argumentSchema,
          context,
          this.#pathAccess,
          this.#host.uri,
        ),
        startedAt + effectiveTimeoutMs,
        signal,
        this.#runtime,
      );
      if (argumentResolution.status !== 'completed') {
        if (argumentResolution.status === 'rejected') {
          return argumentFailure(argumentResolution.error);
        }
        return phaseFailure(input, argumentResolution, effectiveTimeoutMs);
      }
      commandArguments = argumentResolution.value;
    } else {
      const discovery = await waitUntil(
        this.#taskDiscovery.check(context, input, signal),
        startedAt + (input.timeoutMs ?? 120_000),
        signal,
        this.#runtime,
      );
      if (discovery.status !== 'completed') {
        return phaseFailure(input, discovery, input.timeoutMs ?? 120_000);
      }
      if (!discovery.value.ok) return failure(discovery.value.error);
      effectiveTimeoutMs = discovery.value.plan.effectiveTimeoutMs;
      taskPlan = discovery.value.plan;
    }
    const deadlineAt = startedAt + effectiveTimeoutMs;
    let savePhaseActive = true;
    const saveOperation = saveBeforeRun(
        input.saveBeforeRun ?? 'none',
        context,
        this.#host,
        this.#pathAccess,
        () => savePhaseActive && signal?.aborted !== true && this.#runtime.now() < deadlineAt,
      );
    const save = await waitUntil(
      saveOperation,
      deadlineAt,
      signal,
      this.#runtime,
    );
    if (save.status !== 'completed') {
      savePhaseActive = false;
      if (save.status === 'cancelled') {
        return failed(input.target.kind, 'cancelled', 'notStarted', 'The command was cancelled while saving documents.');
      }
      return failed(
        input.target.kind,
        'saveFailed',
        'notStarted',
        'A workspace document could not be saved before command execution.',
        'Some documents may already have been saved; review dirty editors before retrying.',
      );
    }
    if (!save.value) {
      return failed(
        input.target.kind,
        'saveFailed',
        'notStarted',
        'A workspace document could not be saved before command execution.',
        'Some documents may already have been saved; review dirty editors before retrying.',
      );
    }
    if (this.#runtime.now() >= deadlineAt) {
      return timedOut(input.target.kind, effectiveTimeoutMs, 'notStarted');
    }
    if (signal?.aborted === true) {
      return failed(input.target.kind, 'cancelled', 'notStarted', 'The command was cancelled before invocation.');
    }
    const lease = this.#gate.tryAcquire(workspace, 'command');
    if (lease === undefined) {
      return failed(
        input.target.kind,
        'alreadyRunning',
        'unknown',
        'Another workspace mutation is already running or has an unknown outcome.',
      );
    }
    return input.target.kind === 'command'
      ? await this.#executeCommand(input, commandArguments ?? [], effectiveTimeoutMs, deadlineAt, lease, signal)
      : await this.#executeTask(
          context,
          taskPlan!,
          input.retainOutputLog ?? false,
          effectiveTimeoutMs,
          deadlineAt,
          lease,
          signal,
        );
  }

  async #executeCommand(
    input: ExecuteCommandInput,
    args: readonly unknown[],
    effectiveTimeoutMs: number,
    deadlineAt: number,
    lease: WorkspaceMutationLease,
    signal: AbortSignal | undefined,
  ): Promise<ToolResponseMap['execute_command']> {
    if (input.target.kind !== 'command') throw new TypeError('Command target expected.');
    if (signal?.aborted === true) {
      lease.release();
      return failed('command', 'cancelled', 'notStarted', 'The command was cancelled before invocation.');
    }
    if (isDeferredLifecycleCommand(input.target.commandId)) {
      const commandId = input.target.commandId;
      this.#runtime.setTimer(() => {
        try {
          void Promise.resolve(this.#host.executeCommand(commandId, args)).catch(
            () => undefined,
          );
        } catch {
          // The response has already been returned; the next health check reports lifecycle failure.
        }
      }, 250);
      lease.release();
      return success(Object.freeze({
        result: true,
        warnings: Object.freeze([
          'VS Code lifecycle command accepted and scheduled; reconnect and call list_workspaces after the window or Extension Host reloads.',
        ]),
      }));
    }
    const ended = new Set<TExecution>();
    let returnedTask: TExecution | undefined;
    let resolveTaskEnd = (): void => undefined;
    const taskEnded = new Promise<void>((resolve) => { resolveTaskEnd = resolve; });
    const disposable = this.#host.onTaskEnd((event) => {
      ended.add(event.execution);
      if (returnedTask === event.execution) resolveTaskEnd();
    });
    let invocation: Promise<unknown>;
    try {
      invocation = Promise.resolve(this.#host.executeCommand(input.target.commandId, args));
    } catch {
      disposable.dispose();
      lease.release();
      return failed('command', 'rejected', 'failed', 'The command invocation threw before returning its promise.');
    }
    const result = await waitUntil(invocation, deadlineAt, signal, this.#runtime);
    if (result.status === 'timeout' || result.status === 'cancelled') {
      void invocation.then(
        (value) => {
          if (!this.#host.isTaskExecution(value)) {
            disposable.dispose();
            lease.release();
            return;
          }
          returnedTask = value;
          if (ended.has(value) || !this.#host.activeTaskExecutions().includes(value)) {
            disposable.dispose();
            lease.release();
            return;
          }
          try { this.#host.terminateTask(value); } catch { /* best effort */ }
          void taskEnded.then(() => {
            disposable.dispose();
            lease.release();
          });
        },
        () => {
          disposable.dispose();
          lease.release();
        },
      );
      return result.status === 'timeout'
        ? timedOut('command', effectiveTimeoutMs, 'unknown')
        : failed('command', 'cancelled', 'unknown', 'The command was cancelled after invocation.');
    }
    if (result.status === 'rejected') {
      disposable.dispose();
      lease.release();
      return failed('command', 'rejected', 'failed', 'The command promise rejected.');
    }
    if (this.#host.isTaskExecution(result.value)) {
      returnedTask = result.value;
      const alreadyEnded = ended.has(returnedTask) ||
        !this.#host.activeTaskExecutions().includes(returnedTask);
      if (!alreadyEnded) {
        try { this.#host.terminateTask(returnedTask); } catch { /* best effort */ }
        void taskEnded.then(() => {
          disposable.dispose();
          lease.release();
        });
      } else {
        disposable.dispose();
        lease.release();
      }
      return failed(
        'command',
        'completionUnverifiable',
        alreadyEnded ? 'failed' : 'unknown',
        'The command returned a TaskExecution, which proves only launch rather than completion.',
      );
    }
    disposable.dispose();
    lease.release();
    return success(outputFrom(result.value, input.maxOutputChars ?? 20_000));
  }

  async #executeTask(
    context: WorkspacePathContext,
    plan: TaskDiscoveryPlan<TTask>,
    retainOutputLog: boolean,
    effectiveTimeoutMs: number,
    deadlineAt: number,
    lease: WorkspaceMutationLease,
    signal: AbortSignal | undefined,
  ): Promise<ToolResponseMap['execute_command']> {
    if (plan.nodes.length === 0) throw new TypeError('Task plan is empty.');
    if (signal?.aborted === true) {
      lease.release();
      return failed('task', 'cancelled', 'notStarted', 'The task was cancelled before invocation.');
    }
    const rootNode = plan.nodes.find((node) => node.key === plan.rootKey);
    if (rootNode === undefined) throw new TypeError('Task plan root is missing.');
    let capture: CommandTaskOutputCapture<TTask> | undefined;
    if (plan.nodes.length === 1) {
      try {
        capture = await this.#host.prepareTaskOutputCapture(context, rootNode.task, rootNode.taskName);
      } catch {
        capture = undefined;
      }
    }
    const effectivePlan = capture === undefined ? plan : Object.freeze({
      ...plan,
      nodes: Object.freeze(plan.nodes.map((node) => node.key === plan.rootKey
        ? Object.freeze({ ...node, task: capture!.task })
        : node)),
    });
    const finishCapture = async (retain: boolean): Promise<TaskOutputLog | undefined> => {
      try {
        return capture === undefined ? undefined : await capture.finish(retain);
      } catch {
        return undefined;
      }
    };
    const tracker = new TaskRunTracker(context, effectivePlan, this.#host);
    tracker.start();
    const result = await waitUntil(tracker.terminal, deadlineAt, signal, this.#runtime);
    if (result.status === 'completed') {
      const terminal = result.value;
      const releaseWhenSettled = (): void => {
        if (tracker.allTrackedEnded()) lease.release();
        else void tracker.settled.then(() => lease.release());
      };
      releaseWhenSettled();
      if (terminal.kind === 'success') {
        const outputLog = await finishCapture(retainOutputLog);
        return success(outputLog === undefined ? undefined : { outputLog });
      }
      const outputLog = await finishCapture(
        terminal.kind === 'nonZero' || terminal.outcome !== 'notStarted',
      );
      if (terminal.kind === 'nonZero') return nonZero(terminal.exitCode, outputLog);
      return failed(
        'task',
        terminal.reason,
        terminal.outcome,
        terminal.reason === 'alreadyRunning'
          ? 'The same canonical task is already running.'
          : terminal.reason === 'rejected'
            ? 'VS Code rejected the task invocation.'
            : 'Task completion could not be verified from process and task events.',
        undefined,
        outputLog,
      );
    }
    if (result.status === 'rejected') {
      lease.release();
      await finishCapture(false);
      return failed('task', 'completionUnverifiable', 'unknown', 'Task completion tracking failed.');
    }
    tracker.terminateOwned();
    const termination = await waitUntil(
      tracker.settled,
      this.#runtime.now() + 5_000,
      undefined,
      this.#runtime,
    );
    const terminated = termination.status === 'completed';
    if (terminated) lease.release();
    else void tracker.settled.then(() => lease.release());
    if (result.status === 'timeout') {
      const outputLog = terminated ? await finishCapture(true) : undefined;
      return timedOut('task', effectiveTimeoutMs, terminated ? 'terminated' : 'unknown', outputLog);
    }
    const outputLog = terminated ? await finishCapture(true) : undefined;
    return failed(
      'task',
      'cancelled',
      terminated ? 'terminated' : 'unknown',
      'The task was cancelled after invocation.',
      undefined,
      outputLog,
    );
  }
}

const taskScopeKey = (
  context: WorkspacePathContext,
  task: Task,
): string | undefined => {
  if (typeof task.scope !== 'object' || task.scope.uri.scheme !== 'file') return undefined;
  let scope: string;
  try {
    scope = toPathComparisonKey(task.scope.uri.fsPath);
  } catch {
    return undefined;
  }
  const root = context.roots.find((candidate) => candidate.lexicalComparisonKey === scope);
  return root === undefined ? undefined : `${root.alias}\u0000${task.name}`;
};

export const createVscodeCommandExecutionHost = (
  vscode: typeof import('vscode'),
  pathAccess: WorkspacePathAccess,
): CommandExecutionHost<Task, TaskExecution, TextDocument, import('vscode').Uri> => Object.freeze({
  uri: Object.freeze({ file: (absolutePath: string) => vscode.Uri.file(absolutePath) }),
  activeDocument: () => vscode.window.activeTextEditor?.document,
  documents: () => vscode.workspace.textDocuments,
  executeCommand: (commandId: string, args: readonly unknown[]) =>
    vscode.commands.executeCommand(commandId, ...args),
  isTaskExecution: (value: unknown): value is TaskExecution =>
    value !== null && typeof value === 'object' &&
    'task' in value && 'terminate' in value && typeof value.terminate === 'function',
  activeTaskExecutions: () => vscode.tasks.taskExecutions,
  executeTask: (task: Task) => vscode.tasks.executeTask(task),
  prepareTaskOutputCapture: (
    context: WorkspacePathContext,
    task: Task,
    taskName: string,
  ) =>
    prepareVscodeTaskOutputCapture(vscode, context, task, taskName, pathAccess),
  taskKey: (context: WorkspacePathContext, execution: TaskExecution) =>
    taskScopeKey(context, execution.task),
  terminateTask: (execution: TaskExecution) => execution.terminate(),
  onTaskStart: (listener: (event: CommandTaskStartEvent<TaskExecution>) => void) =>
    vscode.tasks.onDidStartTask(listener),
  onTaskProcessStart: (listener: (event: CommandTaskStartEvent<TaskExecution>) => void) =>
    vscode.tasks.onDidStartTaskProcess(listener),
  onTaskProcessEnd: (listener: (event: CommandTaskProcessEndEvent<TaskExecution>) => void) =>
    vscode.tasks.onDidEndTaskProcess(listener),
  onTaskEnd: (listener: (event: CommandTaskStartEvent<TaskExecution>) => void) =>
    vscode.tasks.onDidEndTask(listener),
});
