import {
  createFailClosedCommandPolicyDecision,
  type CommandPolicyDecision,
  type ExecuteCommandInput,
} from '@simplechat/vscode-lsp-mcp-protocol';

export interface CommandPolicyHost {
  isWorkspaceTrusted(): boolean;
  readCommandPolicyConfiguration(): unknown;
}

export class CommandPolicyPreflight {
  readonly #host: CommandPolicyHost;

  constructor(host: CommandPolicyHost) {
    this.#host = host;
  }

  check(input: ExecuteCommandInput): CommandPolicyDecision {
    if (input.target.kind !== 'command') {
      return Object.freeze({
        ok: false,
        error: Object.freeze({
          code: 'COMMAND_NOT_ALLOWED',
          message: 'Task policy validation is not available until task discovery completes.',
          retryable: false,
        }),
      });
    }
    const preflightInput = {
      target: input.target,
      ...(input.timeoutMs === undefined ? {} : { timeoutMs: input.timeoutMs }),
    };
    try {
      return createFailClosedCommandPolicyDecision(
        this.#host.readCommandPolicyConfiguration(),
        preflightInput,
        this.#host.isWorkspaceTrusted(),
      );
    } catch {
      return createFailClosedCommandPolicyDecision(null, preflightInput, true);
    }
  }
}

export interface VscodeCommandPolicyApi {
  readonly workspace: {
    readonly isTrusted: boolean;
    getConfiguration(section: string): {
      get<T>(key: string): T | undefined;
    };
  };
}

export const createVscodeCommandPolicyHost = (
  vscode: VscodeCommandPolicyApi,
): CommandPolicyHost => Object.freeze({
  isWorkspaceTrusted: () => vscode.workspace.isTrusted,
  readCommandPolicyConfiguration: () =>
    vscode.workspace.getConfiguration('vscodeLspMcp').get<unknown>('commandPolicy'),
});
