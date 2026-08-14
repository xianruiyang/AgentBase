import type { TextDocument, Uri } from 'vscode';
import {
  BridgeServerSession,
  IPC_PROTOCOL_VERSION,
  REGISTRY_HEARTBEAT_INTERVAL_MS,
  REGISTRY_VERSION,
  RegistrationStore,
  RuntimeSecurityError,
  WorkspaceBoundaryError,
  WorkspaceIdentityController,
  authenticateIpcServerConnection,
  createIpcEndpoint,
  createRegistrationSecrets,
  createWorkspacePathContext,
  ensureRuntimeDirectory,
  hostPathPlatform,
  registrationComparison,
  resolveLogicalPath,
  systemRuntimePrimitives,
  systemWorkspacePathAccess,
  type BridgeRequestHandler,
  type InternalWorkspaceRoot,
  type RawByteConnection,
  type RawByteServer,
  type RegistrationRecord,
  type RegistrationRoot,
  type RuntimeDirectoryLayout,
  type RuntimePlatform,
  type RuntimePrimitives,
  type UnavailableReasonCode,
  type UsableRegistrationRecord,
  type WorkspaceFolderPathInput,
  type WorkspacePathAccess,
  type WorkspacePathContext,
  type WorkspaceRouteIdentity,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  ensureSecureRuntimeDirectory,
  verifySecureRegistryFile,
} from '@simplechat/vscode-lsp-mcp-win32-security';
import {
  MAX_BRIDGE_CONNECTIONS,
  createExtensionTransportServer,
} from './ipc-host.js';
import {
  createSymbolsBridgeHandler,
  type SymbolsBridgeHandler,
} from './symbols-provider.js';
import { createSymbolInfoBridgeHandler } from './symbol-info-provider.js';
import { createReferencesDiagnosticsBridgeHandler } from './references-diagnostics-provider.js';
import { createCapabilitiesBridgeHandler } from './capabilities-provider.js';
import { createHierarchyBridgeHandler } from './hierarchy-provider.js';
import {
  MutationApplyExecutor,
  createMutationApplyBridgeHandler,
  createVscodeMutationApplyHost,
  type MutationBridgeHandler,
} from './mutation-apply-provider.js';
import { DocumentEpochTracker } from './workspace-edit-normalizer.js';
import { WorkspaceExclusiveMutationGate } from './mutation-gate.js';
import {
  RenamePreviewExecutor,
  createRenamePreviewBridgeHandler,
  createVscodeRenamePreviewHost,
} from './rename-preview-provider.js';
import {
  createCodeActionBridgeHandler,
  createVscodeCodeActionProviderHost,
} from './code-action-provider.js';
import {
  CommandExecutionExecutor,
  createVscodeCommandExecutionHost,
} from './command-execution.js';
import { createCommandExecuteBridgeHandler } from './command-execution-provider.js';
import {
  CommandPolicyPreflight,
  createVscodeCommandPolicyHost,
} from './command-policy-provider.js';
import {
  TaskDiscoveryPreflight,
  createVscodeTaskDiscoveryHost,
} from './task-discovery.js';
import {
  FormatPreviewExecutor,
  createFormatPreviewBridgeHandler,
  createVscodeFormatPreviewHost,
} from './format-preview-provider.js';
import {
  PROVIDER_DEFAULT_TIMEOUT_MS,
  PROVIDER_MAX_TIMEOUT_MS,
  createVscodeProviderCallInterrupter,
} from './provider-runtime.js';

export interface ExtensionWorkspaceSnapshot {
  readonly folders: readonly WorkspaceFolderPathInput[];
  readonly remoteName?: string;
  readonly vscodeVersion: string;
  readonly workspaceName: string;
}

export interface ExtensionRegistrationServiceOptions {
  readonly createTransport: (
    endpoint: UsableRegistrationRecord['endpoint'],
  ) => Promise<RawByteServer>;
  readonly currentUserSid?: string;
  readonly heartbeatIntervalMs?: number;
  readonly layout: RuntimeDirectoryLayout;
  readonly now?: () => number;
  readonly pathAccess?: WorkspacePathAccess;
  readonly primitives: RuntimePrimitives;
  readonly readWorkspace: () => ExtensionWorkspaceSnapshot;
  readonly registry: RegistrationStore;
  readonly mutationHandler?: MutationBridgeHandler;
  readonly semanticHandler?: SymbolsBridgeHandler;
}

interface ResolvedWorkspaceUsable {
  readonly kind: 'usable';
  readonly context: WorkspacePathContext;
}

interface ResolvedWorkspaceUnavailable {
  readonly kind: 'unavailable';
  readonly reasonCode: UnavailableReasonCode;
  readonly stateKey: string;
}

type ResolvedWorkspace = ResolvedWorkspaceUsable | ResolvedWorkspaceUnavailable;

interface ActiveBridgeConnection {
  readonly raw: RawByteConnection;
  session?: BridgeServerSession;
  task?: Promise<void>;
}

interface ConnectionCapacityWaiter {
  readonly promise: Promise<void>;
  readonly resolve: () => void;
}

interface ActiveRegistration {
  record: RegistrationRecord;
  readonly context?: WorkspacePathContext;
  readonly server?: RawByteServer;
  readonly connections: Set<ActiveBridgeConnection>;
  readonly sessions: Set<BridgeServerSession>;
  capacityWaiter?: ConnectionCapacityWaiter;
  acceptTask?: Promise<void>;
}

const boundedName = (value: string, fallback: string): string => {
  const normalized = value.trim();
  return normalized.length === 0 ? fallback : normalized.slice(0, 512);
};

const unavailableStateKey = (
  reasonCode: UnavailableReasonCode,
  snapshot: ExtensionWorkspaceSnapshot,
): string => JSON.stringify({
  reasonCode,
  remoteName: snapshot.remoteName ?? null,
  folders: snapshot.folders.map((folder) => [
    folder.name,
    folder.uriScheme,
    folder.lexicalAbsolutePath,
  ]),
});

const resolveWorkspace = async (
  snapshot: ExtensionWorkspaceSnapshot,
  access: WorkspacePathAccess,
  primitives: RuntimePrimitives,
): Promise<ResolvedWorkspace> => {
  let reasonCode: UnavailableReasonCode | undefined;
  if (snapshot.folders.length === 0) {
    reasonCode = 'no_workspace_folders';
  } else if (snapshot.remoteName !== undefined) {
    reasonCode = 'cross_host_unavailable';
  } else if (snapshot.folders.some((folder) => folder.uriScheme !== 'file')) {
    reasonCode = 'unsupported_uri_scheme';
  }
  if (reasonCode !== undefined) {
    return Object.freeze({
      kind: 'unavailable',
      reasonCode,
      stateKey: unavailableStateKey(reasonCode, snapshot),
    });
  }

  try {
    const context = await createWorkspacePathContext(
      snapshot.folders,
      hostPathPlatform,
      access,
      primitives,
    );
    return Object.freeze({ kind: 'usable', context });
  } catch (error) {
    reasonCode = error instanceof WorkspaceBoundaryError &&
        error.message.includes('Duplicate canonical workspace roots')
      ? 'duplicate_canonical_root'
      : 'runtime_security_failed';
    return Object.freeze({
      kind: 'unavailable',
      reasonCode,
      stateKey: unavailableStateKey(reasonCode, snapshot),
    });
  }
};

const toRegistrationRoot = (root: InternalWorkspaceRoot): RegistrationRoot => Object.freeze({
  alias: root.alias,
  folderName: root.name,
  folderIndex: root.folderIndex,
  lexicalRoot: root.lexicalAbsolutePath,
  canonicalRoot: root.canonicalAbsolutePath,
  lexicalComparisonKey: root.lexicalComparisonKey,
  canonicalComparisonKey: root.canonicalComparisonKey,
});

export class ExtensionRegistrationService {
  readonly #options: ExtensionRegistrationServiceOptions;
  readonly #identity: WorkspaceIdentityController;
  readonly #activationStartedAt: number;
  readonly #pathAccess: WorkspacePathAccess;
  #active: ActiveRegistration | undefined;
  #heartbeat: NodeJS.Timeout | undefined;
  #refreshChain = Promise.resolve();
  #started = false;
  #stopping = false;

  constructor(options: ExtensionRegistrationServiceOptions) {
    this.#options = options;
    this.#identity = new WorkspaceIdentityController(options.primitives);
    this.#pathAccess = options.pathAccess ?? systemWorkspacePathAccess;
    this.#activationStartedAt = (options.now ?? Date.now)();
    if (!Number.isSafeInteger(this.#activationStartedAt) || this.#activationStartedAt < 1) {
      throw new RangeError('Extension activation timestamp must be a positive safe integer.');
    }
  }

  get instanceId(): string {
    return this.#identity.instanceId;
  }

  currentRecord(): RegistrationRecord | undefined {
    return this.#active?.record;
  }

  async start(): Promise<void> {
    if (this.#started) {
      return;
    }
    this.#started = true;
    await this.refresh();
    const interval = this.#options.heartbeatIntervalMs ?? REGISTRY_HEARTBEAT_INTERVAL_MS;
    if (!Number.isSafeInteger(interval) || interval < 1) {
      throw new RangeError('Heartbeat interval must be a positive safe integer.');
    }
    this.#heartbeat = setInterval(() => {
      void this.#publishHeartbeat().catch(() => undefined);
    }, interval);
    this.#heartbeat.unref();
  }

  refresh(): Promise<void> {
    const action = (): Promise<void> => this.#refreshNow();
    this.#refreshChain = this.#refreshChain.then(action, action);
    return this.#refreshChain;
  }

  async #refreshNow(): Promise<void> {
    if (!this.#started || this.#stopping) {
      return;
    }
    const snapshot = this.#options.readWorkspace();
    const resolved = await resolveWorkspace(snapshot, this.#pathAccess, this.#options.primitives);
    const identityUpdate = resolved.kind === 'usable'
      ? this.#identity.observeRoots(resolved.context.roots)
      : this.#identity.observeUnavailable(resolved.stateKey);

    const retryingFailedTransport = resolved.kind === 'usable' &&
      this.#active?.record.kind === 'unavailable' &&
      this.#active.record.reasonCode === 'transport_start_failed';
    if (!identityUpdate.changed && this.#active !== undefined && !retryingFailedTransport) {
      await this.#publishHeartbeat(snapshot);
      return;
    }

    await this.#retireActive();
    const now = this.#now();
    const common = {
      registryVersion: REGISTRY_VERSION,
      protocolVersion: IPC_PROTOCOL_VERSION,
      instanceId: identityUpdate.snapshot.instanceId,
      workspaceId: identityUpdate.snapshot.workspaceId,
      workspaceGeneration: identityUpdate.snapshot.generation,
      workspaceName: boundedName(snapshot.workspaceName, 'Untitled Workspace'),
      extensionHostPid: process.pid,
      activationStartedAt: this.#activationStartedAt,
      publishedAt: now,
      updatedAt: now,
    } as const;
    const secrets = createRegistrationSecrets(this.#options.primitives);

    if (resolved.kind === 'unavailable') {
      const record: RegistrationRecord = Object.freeze({
        ...common,
        kind: 'unavailable',
        recordNonce: secrets.recordNonce,
        reasonCode: resolved.reasonCode,
      });
      await this.#options.registry.publish(record);
      this.#active = { record, connections: new Set(), sessions: new Set() };
      return;
    }

    let endpoint: UsableRegistrationRecord['endpoint'];
    let server: RawByteServer;
    try {
      endpoint = createIpcEndpoint(
        this.#options.layout,
        identityUpdate.snapshot.instanceId,
        this.#options.primitives,
        this.#options.currentUserSid,
      );
      server = await this.#options.createTransport(endpoint);
    } catch {
      const reasonCode: UnavailableReasonCode = 'transport_start_failed';
      const record: RegistrationRecord = Object.freeze({
        ...common,
        kind: 'unavailable',
        recordNonce: secrets.recordNonce,
        reasonCode,
      });
      await this.#options.registry.publish(record);
      this.#active = { record, connections: new Set(), sessions: new Set() };
      return;
    }

    const record: UsableRegistrationRecord = Object.freeze({
      ...common,
      kind: 'usable',
      recordNonce: secrets.recordNonce,
      endpoint,
      authToken: secrets.authToken,
      rootsFingerprint: identityUpdate.snapshot.rootsFingerprint,
      roots: Object.freeze(resolved.context.roots.map(toRegistrationRoot)),
      vscodeVersion: boundedName(snapshot.vscodeVersion, 'unknown').slice(0, 128),
    });
    const active: ActiveRegistration = {
      record,
      context: resolved.context,
      server,
      connections: new Set(),
      sessions: new Set(),
    };
    try {
      await this.#options.registry.publish(record);
    } catch (error) {
      await server.close().catch(() => undefined);
      throw error;
    }
    this.#active = active;
    active.acceptTask = this.#acceptLoop(active);
  }

  #now(): number {
    const now = (this.#options.now ?? Date.now)();
    if (!Number.isSafeInteger(now) || now < this.#activationStartedAt) {
      throw new RangeError('Extension clock returned an invalid wall-clock timestamp.');
    }
    return now;
  }

  async #publishHeartbeat(snapshot = this.#options.readWorkspace()): Promise<void> {
    const active = this.#active;
    if (active === undefined || this.#stopping) {
      return;
    }
    const updatedAt = Math.max(active.record.updatedAt, this.#now());
    const record = Object.freeze({
      ...active.record,
      workspaceName: boundedName(snapshot.workspaceName, 'Untitled Workspace'),
      updatedAt,
    }) as RegistrationRecord;
    await this.#options.registry.publish(record);
    active.record = record;
  }

  #bridgeHandler(active: ActiveRegistration): BridgeRequestHandler {
    return async (request, signal) => {
      if (active.context === undefined) {
        throw new Error('Unsupported bridge request.');
      }
      if (request.method === 'bridge.health') {
        const file = request.params.file;
        if (file === undefined) {
          return { status: 'healthy' };
        }
        if (typeof file !== 'string' || file.length === 0) {
          return { status: 'unavailable', issue: 'INVALID_ARGUMENT' };
        }
        try {
          await resolveLogicalPath(active.context, file, this.#pathAccess);
          return { status: 'healthy' };
        } catch (error) {
          return {
            status: 'unavailable',
            issue: error instanceof WorkspaceBoundaryError ? error.code : 'INTERNAL_ERROR',
          };
        }
      }
      if (active.record.kind === 'usable') {
        const workspace: WorkspaceRouteIdentity = Object.freeze({
          workspaceId: active.record.workspaceId,
          generation: active.record.workspaceGeneration,
        });
        const mutation = await this.#options.mutationHandler?.(
          active.context,
          workspace,
          request,
          signal,
        );
        if (mutation !== undefined) return mutation;
      }
      const semantic = await this.#options.semanticHandler?.(active.context, request, signal);
      if (semantic !== undefined) return semantic;
      throw new Error('Unsupported bridge request.');
    };
  }

  async #acceptLoop(active: ActiveRegistration): Promise<void> {
    const server = active.server;
    const record = active.record;
    if (server === undefined || record.kind !== 'usable') {
      return;
    }
    while (!this.#stopping && this.#active === active) {
      if (!await this.#waitForConnectionCapacity(active)) {
        return;
      }
      let raw;
      try {
        raw = await server.accept();
      } catch {
        return;
      }
      if (this.#active !== active || this.#stopping) {
        await raw.close().catch(() => undefined);
        return;
      }
      const connection: ActiveBridgeConnection = { raw };
      active.connections.add(connection);
      let authenticated;
      try {
        authenticated = await authenticateIpcServerConnection(raw, {
          instanceId: record.instanceId,
          workspaceId: record.workspaceId,
          workspaceGeneration: record.workspaceGeneration,
          token: record.authToken,
        });
      } catch {
        await this.#releaseConnection(active, connection);
        continue;
      }
      if (this.#active !== active || this.#stopping) {
        await authenticated.close().catch(() => undefined);
        await this.#releaseConnection(active, connection);
        return;
      }
      const session = new BridgeServerSession(authenticated, this.#bridgeHandler(active));
      connection.session = session;
      active.sessions.add(session);
      const task = this.#runSession(active, connection, session);
      connection.task = task;
      void task;
    }
  }

  async #waitForConnectionCapacity(active: ActiveRegistration): Promise<boolean> {
    while (!this.#stopping && this.#active === active &&
        active.connections.size >= MAX_BRIDGE_CONNECTIONS) {
      if (active.capacityWaiter === undefined) {
        let resolve = (): void => undefined;
        const promise = new Promise<void>((ready) => {
          resolve = ready;
        });
        active.capacityWaiter = { promise, resolve };
      }
      await active.capacityWaiter.promise;
    }
    return !this.#stopping && this.#active === active;
  }

  #wakeConnectionCapacity(active: ActiveRegistration): void {
    const waiter = active.capacityWaiter;
    delete active.capacityWaiter;
    waiter?.resolve();
  }

  async #releaseConnection(
    active: ActiveRegistration,
    connection: ActiveBridgeConnection,
  ): Promise<void> {
    await connection.raw.close().catch(() => undefined);
    active.connections.delete(connection);
    this.#wakeConnectionCapacity(active);
  }

  async #runSession(
    active: ActiveRegistration,
    connection: ActiveBridgeConnection,
    session: BridgeServerSession,
  ): Promise<void> {
    try {
      await session.run();
    } catch {
      // Protocol and disconnect failures are isolated to the established session.
    } finally {
      active.sessions.delete(session);
      await this.#releaseConnection(active, connection);
    }
  }

  async #retireActive(): Promise<void> {
    const active = this.#active;
    if (active === undefined) {
      return;
    }
    this.#active = undefined;
    this.#wakeConnectionCapacity(active);
    const connections = [...active.connections];
    await active.server?.close().catch(() => undefined);
    await Promise.all(connections.map(async (connection) => {
      await connection.session?.close().catch(() => undefined);
      await connection.raw.close().catch(() => undefined);
    }));
    await active.acceptTask?.catch(() => undefined);
    await Promise.all(connections.map((connection) => connection.task?.catch(() => undefined)));
    await this.#options.registry.comparisonAndDelete(registrationComparison(active.record));
  }

  async stop(): Promise<void> {
    if (this.#stopping) {
      await this.#refreshChain.catch(() => undefined);
      return;
    }
    this.#stopping = true;
    if (this.#heartbeat !== undefined) {
      clearInterval(this.#heartbeat);
      this.#heartbeat = undefined;
    }
    await this.#refreshChain.catch(() => undefined);
    await this.#retireActive();
  }
}

const runtimePlatform = (): RuntimePlatform => {
  if (process.platform === 'win32') {
    return 'win32';
  }
  throw new RuntimeSecurityError('unsupportedPlatform', 'The extension host requires Windows.');
};

export interface VscodeLifecycleHost {
  readonly Position: new (line: number, character: number) => unknown;
  readonly Range: new (
    startLine: number,
    startCharacter: number,
    endLine: number,
    endCharacter: number,
  ) => unknown;
  readonly commands: {
    executeCommand<T = unknown>(command: string, ...args: readonly unknown[]): PromiseLike<T>;
  };
  readonly env: { readonly remoteName?: string | undefined };
  readonly languages: {
    getDiagnostics(resource?: never): unknown;
  };
  readonly version: string;
  readonly workspace: {
    readonly name?: string | undefined;
    readonly workspaceFolders?: readonly {
      readonly name: string;
      readonly uri: { readonly scheme: string; readonly fsPath: string };
    }[] | undefined;
    readonly textDocuments: readonly TextDocument[];
    openTextDocument(path: string): PromiseLike<TextDocument>;
  };
}

export const createSystemExtensionRegistrationService = async (
  vscode: typeof import('vscode'),
): Promise<ExtensionRegistrationService> => {
  const configuredProviderTimeoutMs = vscode.workspace
    .getConfiguration('vscodeLspMcp')
    .get<unknown>('providerTimeoutMs', PROVIDER_DEFAULT_TIMEOUT_MS);
  const providerTimeoutMs = typeof configuredProviderTimeoutMs === 'number' &&
    Number.isSafeInteger(configuredProviderTimeoutMs) &&
    configuredProviderTimeoutMs >= 1_000 &&
    configuredProviderTimeoutMs <= PROVIDER_MAX_TIMEOUT_MS
    ? configuredProviderTimeoutMs
    : PROVIDER_DEFAULT_TIMEOUT_MS;
  const platform = runtimePlatform();
  const windowsInfo = ensureSecureRuntimeDirectory();
  const windowsSecurity = {
    ensureSecureRuntimeDirectory: () => ensureSecureRuntimeDirectory(),
    verifySecureRegistryFile,
  };
  const layout = await ensureRuntimeDirectory({
    platform,
    environment: process.env,
    windowsSecurity,
  });
  const registry = new RegistrationStore({
    layout,
    primitives: systemRuntimePrimitives,
    windowsSecurity,
  });
  const providerHost = {
    executeCommand: (command: string, ...args: readonly unknown[]) =>
      vscode.commands.executeCommand(command, ...args),
    interruptProviderCall: createVscodeProviderCallInterrupter(vscode),
    openTextDocument: (path: string) => vscode.workspace.openTextDocument(path),
    openProviderDocument: (uri: unknown) => vscode.workspace.openTextDocument(uri as never),
    readProviderText: async (uri: unknown) => {
      const providerUri = uri as Uri;
      const openDocument = vscode.workspace.textDocuments.find(
        (document) => document.uri.toString() === providerUri.toString(),
      );
      if (openDocument !== undefined) return openDocument.getText();
      const bytes = await vscode.workspace.fs.readFile(providerUri);
      return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    },
    findFiles: (rootAbsolutePath: string, includePattern: string, maximumResults: number) =>
      vscode.workspace.findFiles(
        new vscode.RelativePattern(rootAbsolutePath, includePattern),
        null,
        maximumResults,
      ),
    createPosition: (line: number, character: number) => new vscode.Position(line, character),
    createRange: (
      startLine: number,
      startCharacter: number,
      endLine: number,
      endCharacter: number,
    ) => new vscode.Range(startLine, startCharacter, endLine, endCharacter),
    getDiagnostics: (resource?: unknown) => resource === undefined
      ? vscode.languages.getDiagnostics()
      : vscode.languages.getDiagnostics(resource as never),
    getOpenDocuments: () => vscode.workspace.textDocuments,
  };
  const symbolsHandler = createSymbolsBridgeHandler(
    providerHost,
    systemWorkspacePathAccess,
    providerTimeoutMs,
  );
  const symbolInfoHandler = createSymbolInfoBridgeHandler(
    providerHost,
    systemWorkspacePathAccess,
    providerTimeoutMs,
  );
  const referencesDiagnosticsHandler = createReferencesDiagnosticsBridgeHandler(
    providerHost,
    systemWorkspacePathAccess,
    providerTimeoutMs,
  );
  const capabilitiesHandler = createCapabilitiesBridgeHandler(
    providerHost,
    systemWorkspacePathAccess,
    providerTimeoutMs,
  );
  const hierarchyHandler = createHierarchyBridgeHandler(
    providerHost,
    systemWorkspacePathAccess,
    providerTimeoutMs,
  );
  const mutationEpochTracker = new DocumentEpochTracker();
  const mutationGate = new WorkspaceExclusiveMutationGate();
  const mutationApplyExecutor = new MutationApplyExecutor(
    createVscodeMutationApplyHost(vscode),
    {
      epochTracker: mutationEpochTracker,
      gate: mutationGate,
      pathAccess: systemWorkspacePathAccess,
      primitives: systemRuntimePrimitives,
    },
  );
  const mutationApplyHandler = createMutationApplyBridgeHandler(mutationApplyExecutor);
  const commandPolicyHost = createVscodeCommandPolicyHost(vscode);
  const commandHandler = createCommandExecuteBridgeHandler(new CommandExecutionExecutor(
    createVscodeCommandExecutionHost(vscode, systemWorkspacePathAccess),
    {
      gate: mutationGate,
      pathAccess: systemWorkspacePathAccess,
      policy: new CommandPolicyPreflight(commandPolicyHost),
      taskDiscovery: new TaskDiscoveryPreflight(
        createVscodeTaskDiscoveryHost(vscode),
        commandPolicyHost,
      ),
    },
  ));
  const codeActionHandler = createCodeActionBridgeHandler(
    createVscodeCodeActionProviderHost(vscode),
    {
      applyExecutor: mutationApplyExecutor,
      defaultTimeoutMs: providerTimeoutMs,
      epochTracker: mutationEpochTracker,
      pathAccess: systemWorkspacePathAccess,
    },
  );
  const renamePreviewHandler = createRenamePreviewBridgeHandler(new RenamePreviewExecutor(
    createVscodeRenamePreviewHost(vscode),
    {
      epochTracker: mutationEpochTracker,
      defaultTimeoutMs: providerTimeoutMs,
      pathAccess: systemWorkspacePathAccess,
    },
  ));
  const formatPreviewHandler = createFormatPreviewBridgeHandler(new FormatPreviewExecutor(
    createVscodeFormatPreviewHost(vscode),
    {
      defaultTimeoutMs: providerTimeoutMs,
      epochTracker: mutationEpochTracker,
      pathAccess: systemWorkspacePathAccess,
    },
  ));
  const mutationHandler: MutationBridgeHandler = async (context, workspace, request, signal) =>
    (await commandHandler(context, workspace, request, signal)) ??
    (await codeActionHandler(context, workspace, request, signal)) ??
    (await renamePreviewHandler(context, workspace, request, signal)) ??
    (await formatPreviewHandler(context, workspace, request, signal)) ??
    mutationApplyHandler(context, workspace, request, signal);
  return new ExtensionRegistrationService({
    layout,
    registry,
    primitives: systemRuntimePrimitives,
    mutationHandler,
    semanticHandler: async (context, request, signal) =>
      (await capabilitiesHandler(context, request, signal)) ??
      (await hierarchyHandler(context, request, signal)) ??
      (await symbolsHandler(context, request, signal)) ??
      (await symbolInfoHandler(context, request, signal)) ??
      referencesDiagnosticsHandler(context, request, signal),
    currentUserSid: windowsInfo.currentUserSid,
    readWorkspace: () => {
      const folders = (vscode.workspace.workspaceFolders ?? []).map((folder) => ({
        name: folder.name,
        uriScheme: folder.uri.scheme,
        lexicalAbsolutePath: folder.uri.fsPath,
      }));
      return {
        folders,
        workspaceName: vscode.workspace.name ??
          (folders.map((folder) => folder.name).join(', ') || 'Untitled Workspace'),
        vscodeVersion: vscode.version,
        ...(vscode.env.remoteName === undefined ? {} : { remoteName: vscode.env.remoteName }),
      };
    },
    createTransport: (endpoint) => createExtensionTransportServer({
      endpoint,
    }),
  });
};
