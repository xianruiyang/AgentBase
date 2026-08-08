import {
  isWorkspaceId,
  type WorkspaceMutationGate,
  type WorkspaceRouteIdentity,
} from '@simplechat/vscode-lsp-mcp-protocol';

const workspaceKey = (workspace: WorkspaceRouteIdentity): string =>
  `${workspace.workspaceId}\u0000${workspace.generation}`;

const assertWorkspace = (workspace: WorkspaceRouteIdentity): void => {
  if (!isWorkspaceId(workspace.workspaceId) || !Number.isSafeInteger(workspace.generation) ||
      workspace.generation < 1) {
    throw new TypeError('Mutation gate workspace identity is invalid.');
  }
};

const assertOperation = (operation: 'apply' | 'command'): void => {
  if (operation !== 'apply' && operation !== 'command') {
    throw new TypeError('Mutation gate operation is invalid.');
  }
};

export interface WorkspaceMutationLease {
  readonly workspace: WorkspaceRouteIdentity;
  readonly operation: 'apply' | 'command';
  release(): void;
}

export class WorkspaceExclusiveMutationGate implements WorkspaceMutationGate {
  readonly #tails = new Map<string, Promise<void>>();

  tryAcquire(
    workspace: WorkspaceRouteIdentity,
    operation: 'apply' | 'command',
  ): WorkspaceMutationLease | undefined {
    assertWorkspace(workspace);
    assertOperation(operation);
    const key = workspaceKey(workspace);
    if (this.#tails.has(key)) return undefined;
    let releaseTurn = (): void => undefined;
    const turn = new Promise<void>((resolve) => {
      releaseTurn = resolve;
    });
    this.#tails.set(key, turn);
    let released = false;
    return Object.freeze({
      workspace: Object.freeze({ ...workspace }),
      operation,
      release: (): void => {
        if (released) return;
        released = true;
        releaseTurn();
        if (this.#tails.get(key) === turn) this.#tails.delete(key);
      },
    });
  }

  async runExclusive<T>(
    workspace: WorkspaceRouteIdentity,
    operation: 'apply' | 'command',
    action: () => Promise<T>,
  ): Promise<T> {
    assertWorkspace(workspace);
    assertOperation(operation);
    const key = workspaceKey(workspace);
    const previous = this.#tails.get(key) ?? Promise.resolve();
    let release = (): void => undefined;
    const turn = new Promise<void>((resolve) => {
      release = resolve;
    });
    const tail = previous.catch(() => undefined).then(() => turn);
    this.#tails.set(key, tail);
    await previous.catch(() => undefined);
    try {
      return await action();
    } finally {
      release();
      if (this.#tails.get(key) === tail) this.#tails.delete(key);
    }
  }
}
