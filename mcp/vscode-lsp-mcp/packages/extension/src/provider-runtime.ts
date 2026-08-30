import type { TextDocument } from 'vscode';
import {
  WorkspaceBoundaryError,
  resolveLogicalPath,
  systemRuntimePrimitives,
  systemWorkspacePathAccess,
  type WorkspacePathAccess,
  type WorkspacePathContext,
} from '@simplechat/vscode-lsp-mcp-protocol';

export const PUBLIC_PROVIDER_COMMANDS = Object.freeze([
  'vscode.executeWorkspaceSymbolProvider',
  'vscode.executeDocumentSymbolProvider',
  'vscode.executeDeclarationProvider',
  'vscode.executeDefinitionProvider',
  'vscode.executeTypeDefinitionProvider',
  'vscode.executeImplementationProvider',
  'vscode.executeHoverProvider',
  'vscode.executeSignatureHelpProvider',
  'vscode.executeReferenceProvider',
  'vscode.prepareCallHierarchy',
  'vscode.provideIncomingCalls',
  'vscode.provideOutgoingCalls',
  'vscode.prepareTypeHierarchy',
  'vscode.provideSupertypes',
  'vscode.provideSubtypes',
  'vscode.prepareRename',
  'vscode.executeDocumentRenameProvider',
  'vscode.executeCodeActionProvider',
  'vscode.executeFormatDocumentProvider',
  'vscode.executeFormatRangeProvider',
] as const);

export type PublicProviderCommand = (typeof PUBLIC_PROVIDER_COMMANDS)[number];

const providerCommandSet = new Set<string>(PUBLIC_PROVIDER_COMMANDS);

export const isPublicProviderCommand = (value: string): value is PublicProviderCommand =>
  providerCommandSet.has(value);

export const PROVIDER_DEFAULT_TIMEOUT_MS = 60_000;
export const PROVIDER_MAX_TIMEOUT_MS = 300_000;
export const PROVIDER_DEFAULT_POLL_DELAYS_MS = Object.freeze([0, 100, 250, 500] as const);

export type ProviderInvocationPhase =
  | 'documentActivation'
  | 'pollDelay'
  | 'providerCall';

export type ProviderInvocationFailureReason =
  | 'documentActivationFailed'
  | 'providerArgumentsInvalid'
  | 'providerCallFailed'
  | 'providerResultInvalid';

interface ProviderInvocationBase {
  readonly attempts: number;
  readonly command: PublicProviderCommand;
  readonly elapsedMs: number;
}

export type ProviderInvocationResult<T> =
  | (ProviderInvocationBase & {
      readonly status: 'completed';
      readonly value: T;
    })
  | (ProviderInvocationBase & {
      readonly reason: 'commandUnavailable';
      readonly status: 'unavailable';
    })
  | (ProviderInvocationBase & {
      readonly reason: 'pollLimitReached' | 'providerCallInFlight';
      readonly status: 'notReady';
    })
  | (ProviderInvocationBase & {
      readonly phase: ProviderInvocationPhase;
      readonly status: 'cancelled' | 'timedOut';
    })
  | (ProviderInvocationBase & {
      readonly phase: ProviderInvocationPhase;
      readonly reason: ProviderInvocationFailureReason;
      readonly status: 'failed';
    });

export type ProviderCommandClassification<T> =
  | { readonly status: 'ready'; readonly value: T }
  | { readonly status: 'notReady' }
  | { readonly status: 'invalid' };

export interface ProviderCommandAdapter<TInput, TResult> {
  readonly command: PublicProviderCommand;
  readonly requiresDocument: boolean;
  buildArguments(input: TInput, document: TextDocument | undefined): readonly unknown[];
  classifyResult(value: unknown): ProviderCommandClassification<TResult>;
}

export interface ProviderInvocationOptions {
  readonly logicalFile?: string;
  readonly pollDelaysMs?: readonly number[];
  readonly signal?: AbortSignal;
  readonly timeoutMs?: number;
}

export interface VscodeProviderHost {
  executeCommand(command: string, ...args: readonly unknown[]): PromiseLike<unknown>;
  interruptProviderCall?(request: ProviderCallInterruption): PromiseLike<void> | void;
  openTextDocument(path: string): PromiseLike<TextDocument>;
}

export interface ProviderCallInterruption {
  readonly command: PublicProviderCommand;
  readonly document: TextDocument;
  readonly status: 'cancelled' | 'timedOut';
}

export interface ProviderRuntimeOptions {
  readonly defaultTimeoutMs?: number;
  readonly host: VscodeProviderHost;
  readonly now?: () => number;
  readonly pathAccess?: WorkspacePathAccess;
}

class InvocationInterrupted extends Error {
  readonly status: 'cancelled' | 'timedOut';

  constructor(status: InvocationInterrupted['status']) {
    super(status === 'cancelled' ? 'Provider invocation was cancelled.' : 'Provider invocation timed out.');
    this.name = 'InvocationInterrupted';
    this.status = status;
  }
}

const validateTimeout = (value: number): number => {
  if (!Number.isSafeInteger(value) || value < 1 || value > PROVIDER_MAX_TIMEOUT_MS) {
    throw new RangeError(`Provider timeout must be an integer from 1 through ${PROVIDER_MAX_TIMEOUT_MS}.`);
  }
  return value;
};

const validatePollDelays = (value: readonly number[]): readonly number[] => {
  if (value.length < 1 || value.length > 16 || value[0] !== 0) {
    throw new RangeError('Provider poll delays must contain 1 through 16 entries and start with zero.');
  }
  for (const delay of value) {
    if (!Number.isSafeInteger(delay) || delay < 0 || delay > 5_000) {
      throw new RangeError('Each provider poll delay must be an integer from zero through 5000.');
    }
  }
  return Object.freeze([...value]);
};

const isUnavailableCommandError = (error: unknown, command: string): boolean =>
  error instanceof Error && error.message === `command '${command}' not found`;

export const classifyArrayProviderResult = <T>(
  value: unknown,
): ProviderCommandClassification<readonly T[]> => {
  if (value === undefined) {
    return { status: 'notReady' };
  }
  return Array.isArray(value)
    ? { status: 'ready', value: Object.freeze([...value]) as readonly T[] }
    : { status: 'invalid' };
};

export const classifyDefinedProviderResult = <T>(
  value: unknown,
): ProviderCommandClassification<T> => value === undefined
  ? { status: 'notReady' }
  : { status: 'ready', value: value as T };

export class ProviderRuntime {
  readonly #host: VscodeProviderHost;
  readonly #defaultTimeoutMs: number;
  readonly #nowSource: () => number;
  readonly #pathAccess: WorkspacePathAccess;
  readonly #providerCalls = new Map<PublicProviderCommand, Promise<unknown>>();

  constructor(options: ProviderRuntimeOptions) {
    this.#host = options.host;
    this.#defaultTimeoutMs = validateTimeout(
      options.defaultTimeoutMs ?? PROVIDER_DEFAULT_TIMEOUT_MS,
    );
    this.#nowSource = options.now ?? systemRuntimePrimitives.monotonicNowMs;
    this.#pathAccess = options.pathAccess ?? systemWorkspacePathAccess;
  }

  #now(): number {
    const value = this.#nowSource();
    if (!Number.isFinite(value) || value < 0 || value > Number.MAX_SAFE_INTEGER) {
      throw new RangeError('Provider runtime clock returned an invalid timestamp.');
    }
    return value;
  }

  #base(command: PublicProviderCommand, startedAt: number, attempts: number): ProviderInvocationBase {
    return Object.freeze({
      attempts,
      command,
      elapsedMs: Math.max(0, Math.round(this.#now() - startedAt)),
    });
  }

  async #runPhase<T>(
    operation: () => PromiseLike<T> | T,
    deadlineAt: number,
    signal: AbortSignal | undefined,
  ): Promise<T> {
    if (signal?.aborted === true) {
      throw new InvocationInterrupted('cancelled');
    }
    const remaining = deadlineAt - this.#now();
    if (remaining <= 0) {
      throw new InvocationInterrupted('timedOut');
    }
    return new Promise<T>((resolve, reject) => {
      let settled = false;
      const finish = (action: () => void): void => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        signal?.removeEventListener('abort', onAbort);
        action();
      };
      const onAbort = (): void => finish(() => reject(new InvocationInterrupted('cancelled')));
      const timer = setTimeout(
        () => finish(() => reject(new InvocationInterrupted('timedOut'))),
        remaining,
      );
      signal?.addEventListener('abort', onAbort, { once: true });
      void Promise.resolve().then(operation).then(
        (value) => finish(() => resolve(value)),
        (error: unknown) => finish(() => reject(error)),
      );
    });
  }

  async #wait(
    delayMs: number,
    deadlineAt: number,
    signal: AbortSignal | undefined,
  ): Promise<void> {
    if (delayMs === 0) return;
    if (signal?.aborted === true) {
      throw new InvocationInterrupted('cancelled');
    }
    const remaining = deadlineAt - this.#now();
    if (remaining <= 0) {
      throw new InvocationInterrupted('timedOut');
    }
    await new Promise<void>((resolve, reject) => {
      let settled = false;
      const finish = (action: () => void): void => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        signal?.removeEventListener('abort', onAbort);
        action();
      };
      const onAbort = (): void => finish(() => reject(new InvocationInterrupted('cancelled')));
      const expires = delayMs >= remaining;
      const timer = setTimeout(
        () => finish(() => expires
          ? reject(new InvocationInterrupted('timedOut'))
          : resolve()),
        Math.min(delayMs, remaining),
      );
      signal?.addEventListener('abort', onAbort, { once: true });
    });
  }

  #interrupted<TResult>(
    error: InvocationInterrupted,
    phase: ProviderInvocationPhase,
    command: PublicProviderCommand,
    startedAt: number,
    attempts: number,
  ): ProviderInvocationResult<TResult> {
    return Object.freeze({
      ...this.#base(command, startedAt, attempts),
      phase,
      status: error.status,
    });
  }

  #failed<TResult>(
    reason: ProviderInvocationFailureReason,
    phase: ProviderInvocationPhase,
    command: PublicProviderCommand,
    startedAt: number,
    attempts: number,
  ): ProviderInvocationResult<TResult> {
    return Object.freeze({
      ...this.#base(command, startedAt, attempts),
      phase,
      reason,
      status: 'failed',
    });
  }

  async #interruptAndDrain(
    command: PublicProviderCommand,
    document: TextDocument | undefined,
    status: ProviderCallInterruption['status'],
    providerCall: Promise<unknown>,
  ): Promise<void> {
    if (document === undefined || this.#host.interruptProviderCall === undefined) return;
    void Promise.resolve()
      .then(() => this.#host.interruptProviderCall?.({ command, document, status }))
      .catch(() => undefined);
    await new Promise<void>((resolve) => {
      let settled = false;
      const finish = (): void => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve();
      };
      const timer = setTimeout(finish, 3_000);
      void providerCall.then(finish, finish);
    });
  }

  async invoke<TInput, TResult>(
    context: WorkspacePathContext,
    adapter: ProviderCommandAdapter<TInput, TResult>,
    input: TInput,
    options: ProviderInvocationOptions = {},
  ): Promise<ProviderInvocationResult<TResult>> {
    if (!isPublicProviderCommand(adapter.command)) {
      throw new RangeError('Provider command is outside the public allowlist.');
    }
    const timeoutMs = validateTimeout(options.timeoutMs ?? this.#defaultTimeoutMs);
    const pollDelays = validatePollDelays(options.pollDelaysMs ?? PROVIDER_DEFAULT_POLL_DELAYS_MS);
    const startedAt = this.#now();
    const deadlineAt = startedAt + timeoutMs;
    if (!Number.isFinite(deadlineAt) || deadlineAt > Number.MAX_SAFE_INTEGER) {
      throw new RangeError('Provider deadline exceeds the safe timestamp range.');
    }
    let attempts = 0;

    let document: TextDocument | undefined;
    if (options.logicalFile !== undefined) {
      try {
        const resolved = await this.#runPhase(
          () => resolveLogicalPath(context, options.logicalFile as string, this.#pathAccess),
          deadlineAt,
          options.signal,
        );
        document = await this.#runPhase(
          () => this.#host.openTextDocument(resolved.lexicalAbsolutePath),
          deadlineAt,
          options.signal,
        );
      } catch (error) {
        if (error instanceof WorkspaceBoundaryError) throw error;
        if (error instanceof InvocationInterrupted) {
          return this.#interrupted(error, 'documentActivation', adapter.command, startedAt, attempts);
        }
        return this.#failed('documentActivationFailed', 'documentActivation', adapter.command, startedAt, attempts);
      }
    } else if (adapter.requiresDocument) {
      throw new RangeError('Provider command requires a logical file.');
    }

    if (this.#providerCalls.has(adapter.command)) {
      return Object.freeze({
        ...this.#base(adapter.command, startedAt, attempts),
        reason: 'providerCallInFlight',
        status: 'notReady',
      });
    }

    for (const delayMs of pollDelays) {
      try {
        await this.#wait(delayMs, deadlineAt, options.signal);
      } catch (error) {
        if (error instanceof InvocationInterrupted) {
          return this.#interrupted(error, 'pollDelay', adapter.command, startedAt, attempts);
        }
        throw error;
      }

      let args: readonly unknown[];
      try {
        args = adapter.buildArguments(input, document);
      } catch {
        return this.#failed('providerArgumentsInvalid', 'providerCall', adapter.command, startedAt, attempts);
      }
      attempts += 1;
      let rawResult: unknown;
      let providerCall: Promise<unknown> | undefined;
      try {
        providerCall = Promise.resolve().then(
          () => this.#host.executeCommand(adapter.command, ...args),
        );
        this.#providerCalls.set(adapter.command, providerCall);
        const releaseProviderCall = (): void => {
          if (this.#providerCalls.get(adapter.command) === providerCall) {
            this.#providerCalls.delete(adapter.command);
          }
        };
        void providerCall.then(releaseProviderCall, releaseProviderCall);
        rawResult = await this.#runPhase(
          () => providerCall,
          deadlineAt,
          options.signal,
        );
      } catch (error) {
        if (error instanceof InvocationInterrupted) {
          if (providerCall !== undefined) {
            await this.#interruptAndDrain(
              adapter.command,
              document,
              error.status,
              providerCall,
            );
          }
          return this.#interrupted(error, 'providerCall', adapter.command, startedAt, attempts);
        }
        if (isUnavailableCommandError(error, adapter.command)) {
          return Object.freeze({
            ...this.#base(adapter.command, startedAt, attempts),
            reason: 'commandUnavailable',
            status: 'unavailable',
          });
        }
        return this.#failed('providerCallFailed', 'providerCall', adapter.command, startedAt, attempts);
      }

      let classified: ProviderCommandClassification<TResult>;
      try {
        classified = adapter.classifyResult(rawResult);
      } catch {
        return this.#failed('providerResultInvalid', 'providerCall', adapter.command, startedAt, attempts);
      }
      if (classified.status === 'invalid') {
        return this.#failed('providerResultInvalid', 'providerCall', adapter.command, startedAt, attempts);
      }
      if (classified.status === 'ready') {
        return Object.freeze({
          ...this.#base(adapter.command, startedAt, attempts),
          status: 'completed',
          value: classified.value,
        });
      }
    }

    return Object.freeze({
      ...this.#base(adapter.command, startedAt, attempts),
      reason: 'pollLimitReached',
      status: 'notReady',
    });
  }
}

export interface VscodeProviderApi {
  readonly commands: {
    executeCommand<T = unknown>(command: string, ...args: readonly unknown[]): PromiseLike<T>;
  };
  readonly workspace: {
    openTextDocument(path: string): PromiseLike<TextDocument>;
  };
}

const interruptibleCppProviderCommands = new Set<PublicProviderCommand>([
  'vscode.executeReferenceProvider',
  'vscode.executeDocumentRenameProvider',
]);

const cppLanguageIds = new Set(['c', 'cpp']);

const whitespaceProbeOffset = (text: string): number | undefined => {
  for (let index = 0; index < text.length; index += 1) {
    if (text[index] === ' ' || text[index] === '\t') return index;
  }
  return undefined;
};

export const createVscodeProviderCallInterrupter = (
  vscode: Pick<VscodeProviderApi, 'commands'>,
): NonNullable<VscodeProviderHost['interruptProviderCall']> => async (request) => {
  if (!interruptibleCppProviderCommands.has(request.command) ||
      !cppLanguageIds.has(request.document.languageId)) {
    return;
  }
  const offset = whitespaceProbeOffset(request.document.getText());
  if (offset === undefined) return;
  await vscode.commands.executeCommand(
    'vscode.prepareCallHierarchy',
    request.document.uri,
    request.document.positionAt(offset),
  );
};

export const createVscodeProviderRuntime = (
  vscode: VscodeProviderApi,
  pathAccess: WorkspacePathAccess = systemWorkspacePathAccess,
): ProviderRuntime => new ProviderRuntime({
  host: {
    executeCommand: (command, ...args) => vscode.commands.executeCommand(command, ...args),
    interruptProviderCall: createVscodeProviderCallInterrupter(vscode),
    openTextDocument: (path) => vscode.workspace.openTextDocument(path),
  },
  pathAccess,
});
