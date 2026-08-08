import type { ErrorObject, ValidateFunction } from 'ajv';
import type {
  CommandTarget,
  ExecuteCommandInput,
  JsonValue,
  ToolError,
} from './dto.js';
import type { JsonSchema } from './schema-definitions.js';
import { createProtocolAjv } from './validation.js';

export const COMMAND_POLICY_LOGICAL_PATH_KEYWORD =
  'x-vscode-lsp-mcp-logicalPath' as const;
export const COMMAND_POLICY_MAX_ENTRIES = 256;
export const COMMAND_POLICY_MAX_SCHEMA_BYTES = 65_536;

export type CommandRiskReason =
  | 'windowLifecycle'
  | 'extensionHostLifecycle'
  | 'vscodeLifecycle'
  | 'extensionManagement'
  | 'bridgeLifecycle'
  | 'inputBox'
  | 'quickPick'
  | 'filePicker'
  | 'authentication'
  | 'confirmation';

export interface CommandAllowlistEntry {
  readonly commandId: string;
  readonly nonInteractive: true;
  readonly completion: 'promise';
  readonly maxTimeoutMs: number;
  readonly argumentSchema?: JsonSchema;
}

export interface TaskAllowlistEntry {
  readonly rootAlias: string;
  readonly taskName: string;
  readonly nonInteractive: true;
  readonly allowDependencies: boolean;
  readonly maxTimeoutMs: number;
}

export interface CommandPolicyConfiguration {
  readonly allowStandardCommands: boolean;
  readonly allowWorkspaceTasks: boolean;
  readonly commands: readonly CommandAllowlistEntry[];
  readonly tasks: readonly TaskAllowlistEntry[];
}

export interface CommandPolicyAllowed {
  readonly ok: true;
  readonly entry: CommandAllowlistEntry;
  readonly arguments: readonly JsonValue[];
  readonly effectiveTimeoutMs: number;
}

export interface CommandPolicyDenied {
  readonly ok: false;
  readonly error: ToolError;
  readonly risk?: CommandRiskReason;
  readonly configurationIssue?: string;
}

export type CommandPolicyDecision = CommandPolicyAllowed | CommandPolicyDenied;

interface CompiledCommandEntry {
  readonly entry: CommandAllowlistEntry;
  readonly validateArguments?: ValidateFunction;
}

const STANDARD_COMMAND_TIMEOUT_MS = 120_000;
const LIFECYCLE_COMMAND_TIMEOUT_MS = 15_000;
const DEFAULT_TASK_TIMEOUT_MS = 600_000;

const STANDARD_COMMAND_IDS = new Set([
  'workbench.action.files.save',
  'workbench.action.files.saveAll',
  'workbench.action.debug.start',
  'workbench.action.debug.startDebug',
  'workbench.action.debug.run',
  'workbench.action.debug.continue',
  'workbench.action.debug.pause',
  'workbench.action.debug.restart',
  'workbench.action.debug.restartFrame',
  'workbench.action.debug.reverseContinue',
  'workbench.action.debug.stepBack',
  'workbench.action.debug.stepInto',
  'workbench.action.debug.stepOut',
  'workbench.action.debug.stepOver',
  'workbench.action.debug.stop',
  'workbench.action.debug.disconnect',
  'workbench.action.debug.disconnectAndSuspend',
  'workbench.action.debug.terminateThread',
  'workbench.action.reloadWindow',
  'workbench.action.restartExtensionHost',
]);

const DEFERRED_LIFECYCLE_COMMAND_IDS = new Set([
  'workbench.action.reloadWindow',
  'workbench.action.restartExtensionHost',
]);

export const isStandardUserCommand = (commandId: string): boolean =>
  STANDARD_COMMAND_IDS.has(commandId);

export const isDeferredLifecycleCommand = (commandId: string): boolean =>
  DEFERRED_LIFECYCLE_COMMAND_IDS.has(commandId);

const standardCommandEntry = (commandId: string): CompiledCommandEntry => Object.freeze({
  entry: Object.freeze({
    commandId,
    nonInteractive: true,
    completion: 'promise',
    maxTimeoutMs: isDeferredLifecycleCommand(commandId)
      ? LIFECYCLE_COMMAND_TIMEOUT_MS
      : STANDARD_COMMAND_TIMEOUT_MS,
  }),
});

const WINDOW_LIFECYCLE_COMMANDS = new Set([
  'vscode.openFolder',
  'workbench.action.closeFolder',
  'workbench.action.closeWindow',
  'workbench.action.reloadWindow',
]);

const EXTENSION_HOST_LIFECYCLE_COMMANDS = new Set([
  'workbench.action.restartExtensionHost',
]);

const VSCODE_LIFECYCLE_COMMANDS = new Set([
  'workbench.action.quit',
]);

const EXTENSION_MANAGEMENT_COMMANDS = new Set([
  'workbench.extensions.action.disableAll',
  'workbench.extensions.action.disableAllWorkspace',
  'workbench.extensions.action.disableGlobally',
  'workbench.extensions.action.disableWorkspace',
  'workbench.extensions.action.uninstallExtension',
  'workbench.extensions.uninstallExtension',
]);

const BRIDGE_LIFECYCLE_COMMANDS = new Set([
  'vscodeLspMcp.disable',
  'vscodeLspMcp.disconnectBridge',
  'vscodeLspMcp.restartBridge',
  'vscodeLspMcp.stopBridge',
  'vscodeLspMcp.uninstall',
]);

const INPUT_BOX_COMMANDS = new Set([
  'editor.action.rename',
  'workbench.action.gotoLine',
]);

const QUICK_PICK_COMMANDS = new Set([
  'workbench.action.debug.selectandstart',
  'workbench.action.openRecent',
  'workbench.action.quickOpen',
  'workbench.action.selectTheme',
  'workbench.action.showCommands',
  'workbench.action.tasks.build',
  'workbench.action.tasks.runTask',
  'workbench.action.tasks.test',
]);

const FILE_PICKER_COMMANDS = new Set([
  'workbench.action.addRootFolder',
  'workbench.action.files.openFile',
  'workbench.action.files.openFileFolder',
  'workbench.action.files.openFolder',
  'workbench.action.files.saveAs',
  'workbench.action.files.saveLocalFile',
]);

const AUTHENTICATION_COMMANDS = new Set([
  'workbench.action.accounts.manage',
  'workbench.action.accounts.signIn',
  'workbench.action.accounts.signOut',
]);

const CONFIRMATION_COMMANDS = new Set([
  'workbench.action.files.revert',
  'workbench.action.files.revertLocalFile',
  'workbench.extensions.action.installExtension',
]);

const riskSets: readonly [ReadonlySet<string>, CommandRiskReason][] = [
  [WINDOW_LIFECYCLE_COMMANDS, 'windowLifecycle'],
  [EXTENSION_HOST_LIFECYCLE_COMMANDS, 'extensionHostLifecycle'],
  [VSCODE_LIFECYCLE_COMMANDS, 'vscodeLifecycle'],
  [EXTENSION_MANAGEMENT_COMMANDS, 'extensionManagement'],
  [BRIDGE_LIFECYCLE_COMMANDS, 'bridgeLifecycle'],
  [INPUT_BOX_COMMANDS, 'inputBox'],
  [QUICK_PICK_COMMANDS, 'quickPick'],
  [FILE_PICKER_COMMANDS, 'filePicker'],
  [AUTHENTICATION_COMMANDS, 'authentication'],
  [CONFIRMATION_COMMANDS, 'confirmation'],
];

export const classifyCommandRisk = (commandId: string): CommandRiskReason | undefined => {
  for (const [commands, reason] of riskSets) {
    if (commands.has(commandId)) return reason;
  }
  if (commandId.startsWith('workbench.action.accounts.')) return 'authentication';
  if (commandId.startsWith('workbench.action.quickOpen')) return 'quickPick';
  if (commandId.startsWith('workbench.action.files.openFile')) return 'filePicker';
  if (commandId.startsWith('workbench.extensions.action.uninstall')) {
    return 'extensionManagement';
  }
  return undefined;
};

const asRecord = (value: unknown, label: string): Record<string, unknown> => {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new CommandPolicyConfigurationError(`${label} must be an object.`);
  }
  return value as Record<string, unknown>;
};

const exactFields = (
  value: Record<string, unknown>,
  allowed: readonly string[],
  label: string,
): void => {
  const fields = new Set(allowed);
  const unknown = Object.keys(value).find((field) => !fields.has(field));
  if (unknown !== undefined) {
    throw new CommandPolicyConfigurationError(`${label}.${unknown} is not supported.`);
  }
};

const boundedIdentifier = (value: unknown, label: string): string => {
  if (typeof value !== 'string' || value.length === 0 || value.length > 512 ||
      value.trim() !== value || /[\u0000-\u001f\u007f]/u.test(value)) {
    throw new CommandPolicyConfigurationError(`${label} must be a bounded exact identifier.`);
  }
  return value;
};

const timeout = (value: unknown, label: string): number => {
  if (!Number.isSafeInteger(value) || (value as number) < 1_000 ||
      (value as number) > 600_000) {
    throw new CommandPolicyConfigurationError(`${label} must be an integer from 1000 to 600000.`);
  }
  return value as number;
};

const optionalBoolean = (value: unknown, label: string, fallback: boolean): boolean => {
  if (value === undefined) return fallback;
  if (typeof value !== 'boolean') {
    throw new CommandPolicyConfigurationError(`${label} must be a boolean.`);
  }
  return value;
};

const freezeDeep = <T>(value: T, seen = new Set<object>()): T => {
  if (value === null || typeof value !== 'object' || seen.has(value)) return value;
  seen.add(value);
  for (const nested of Object.values(value)) freezeDeep(nested, seen);
  return Object.freeze(value);
};

const schemaText = (value: unknown, label: string): string => {
  let text: string | undefined;
  try {
    text = JSON.stringify(value);
  } catch {
    throw new CommandPolicyConfigurationError(`${label} must be JSON-compatible.`);
  }
  if (text === undefined || text.length > COMMAND_POLICY_MAX_SCHEMA_BYTES) {
    throw new CommandPolicyConfigurationError(`${label} exceeds the bounded schema size.`);
  }
  return text;
};

const inspectSchema = (
  value: unknown,
  label: string,
  depth = 0,
  counter = { nodes: 0 },
): void => {
  if (depth > 32 || ++counter.nodes > 2_048) {
    throw new CommandPolicyConfigurationError(`${label} exceeds schema complexity limits.`);
  }
  if (Array.isArray(value)) {
    for (const nested of value) inspectSchema(nested, label, depth + 1, counter);
    return;
  }
  if (value === null || typeof value !== 'object') return;
  const record = value as Record<string, unknown>;
  const declaresObject = record.type === 'object' || record.properties !== undefined ||
    record.patternProperties !== undefined;
  if (declaresObject && record.additionalProperties !== false &&
      record.unevaluatedProperties !== false) {
    throw new CommandPolicyConfigurationError(
      `${label} contains an object schema that is not closed.`,
    );
  }
  if (record[COMMAND_POLICY_LOGICAL_PATH_KEYWORD] !== undefined &&
      (record[COMMAND_POLICY_LOGICAL_PATH_KEYWORD] !== true || record.type !== 'string')) {
    throw new CommandPolicyConfigurationError(
      `${label} logical-path annotations must be true on string schemas.`,
    );
  }
  for (const nested of Object.values(record)) {
    inspectSchema(nested, label, depth + 1, counter);
  }
};

const formatAjvErrors = (errors: ErrorObject[] | null | undefined): string =>
  (errors ?? []).slice(0, 4).map((error) => {
    const path = error.instancePath.length === 0 ? '$' : `$${error.instancePath}`;
    return `${path} ${error.message ?? error.keyword}`;
  }).join('; ');

const compileArgumentSchema = (
  value: unknown,
  label: string,
): { readonly schema: JsonSchema; readonly validate: ValidateFunction } => {
  const record = asRecord(value, label);
  schemaText(record, label);
  if (record.type !== 'array') {
    throw new CommandPolicyConfigurationError(`${label} must describe the arguments array.`);
  }
  inspectSchema(record, label);
  const schema = structuredClone(record) as JsonSchema;
  const ajv = createProtocolAjv();
  ajv.addKeyword({
    keyword: COMMAND_POLICY_LOGICAL_PATH_KEYWORD,
    schemaType: 'boolean',
    validate: (enabled: boolean, data: unknown) => !enabled || typeof data === 'string',
  });
  let validate: ValidateFunction;
  try {
    validate = ajv.compile(schema);
  } catch (error) {
    const message = error instanceof Error ? error.message : 'unknown schema error';
    throw new CommandPolicyConfigurationError(`${label} is not a valid Draft 2020-12 schema: ${message}`);
  }
  return Object.freeze({ schema: freezeDeep(schema), validate });
};

const parseCommandEntry = (
  value: unknown,
  index: number,
): CompiledCommandEntry => {
  const label = `commandPolicy.commands[${index}]`;
  const record = asRecord(value, label);
  exactFields(
    record,
    ['commandId', 'nonInteractive', 'completion', 'maxTimeoutMs', 'argumentSchema'],
    label,
  );
  if (record.nonInteractive !== true || record.completion !== 'promise') {
    throw new CommandPolicyConfigurationError(
      `${label} must declare nonInteractive=true and completion=promise.`,
    );
  }
  const compiled = record.argumentSchema === undefined
    ? undefined
    : compileArgumentSchema(record.argumentSchema, `${label}.argumentSchema`);
  const entry = freezeDeep({
    commandId: boundedIdentifier(record.commandId, `${label}.commandId`),
    nonInteractive: true,
    completion: 'promise',
    maxTimeoutMs: timeout(record.maxTimeoutMs, `${label}.maxTimeoutMs`),
    ...(compiled === undefined ? {} : { argumentSchema: compiled.schema }),
  } satisfies CommandAllowlistEntry);
  return Object.freeze({
    entry,
    ...(compiled === undefined ? {} : { validateArguments: compiled.validate }),
  });
};

const parseTaskEntry = (value: unknown, index: number): TaskAllowlistEntry => {
  const label = `commandPolicy.tasks[${index}]`;
  const record = asRecord(value, label);
  exactFields(
    record,
    ['rootAlias', 'taskName', 'nonInteractive', 'allowDependencies', 'maxTimeoutMs'],
    label,
  );
  if (record.nonInteractive !== true || typeof record.allowDependencies !== 'boolean') {
    throw new CommandPolicyConfigurationError(
      `${label} must declare nonInteractive=true and a boolean allowDependencies.`,
    );
  }
  return Object.freeze({
    rootAlias: boundedIdentifier(record.rootAlias, `${label}.rootAlias`),
    taskName: boundedIdentifier(record.taskName, `${label}.taskName`),
    nonInteractive: true,
    allowDependencies: record.allowDependencies,
    maxTimeoutMs: timeout(record.maxTimeoutMs, `${label}.maxTimeoutMs`),
  });
};

const boundedArray = (value: unknown, label: string): readonly unknown[] => {
  if (value === undefined) return Object.freeze([]);
  if (!Array.isArray(value) || value.length > COMMAND_POLICY_MAX_ENTRIES) {
    throw new CommandPolicyConfigurationError(
      `${label} must be an array with at most ${COMMAND_POLICY_MAX_ENTRIES} entries.`,
    );
  }
  return value;
};

const containsVariable = (
  value: JsonValue,
): 'inputVariable' | 'commandVariable' | undefined => {
  if (typeof value === 'string') {
    if (/\$\{input:[^}]+\}/u.test(value)) return 'inputVariable';
    if (/\$\{command:[^}]+\}/u.test(value)) return 'commandVariable';
    return undefined;
  }
  if (Array.isArray(value)) {
    for (const nested of value) {
      const found = containsVariable(nested);
      if (found !== undefined) return found;
    }
    return undefined;
  }
  if (value !== null && typeof value === 'object') {
    for (const nested of Object.values(value)) {
      const found = containsVariable(nested);
      if (found !== undefined) return found;
    }
  }
  return undefined;
};

export const classifyCommandArgumentVariable = (
  values: readonly JsonValue[],
): 'inputVariable' | 'commandVariable' | undefined => {
  for (const value of values) {
    const found = containsVariable(value);
    if (found !== undefined) return found;
  }
  return undefined;
};

const denied = (
  error: ToolError,
  extra: Pick<CommandPolicyDenied, 'risk' | 'configurationIssue'> = {},
): CommandPolicyDenied => Object.freeze({
  ok: false,
  error: freezeDeep(error),
  ...extra,
});

const interactiveDenied = (
  reason: 'inputVariable' | 'commandVariable' | 'uiInteraction' | 'workspaceTrust',
  risk?: CommandRiskReason,
): CommandPolicyDenied => denied({
  code: 'INTERACTIVE_COMMAND',
  message: 'The command was rejected before invocation because it is not safely non-interactive.',
  retryable: false,
  details: Object.freeze({ targetKind: 'command', reason }),
}, risk === undefined ? {} : { risk });

export class CommandPolicyConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'CommandPolicyConfigurationError';
  }
}

export class CommandPolicy {
  readonly #commands: ReadonlyMap<string, CompiledCommandEntry>;
  readonly configuration: CommandPolicyConfiguration;

  constructor(value: unknown = undefined) {
    const record: Record<string, unknown> = value === undefined
      ? Object.freeze({ commands: Object.freeze([]), tasks: Object.freeze([]) })
      : asRecord(value, 'commandPolicy');
    exactFields(
      record,
      ['allowStandardCommands', 'allowWorkspaceTasks', 'commands', 'tasks'],
      'commandPolicy',
    );
    const allowStandardCommands = optionalBoolean(
      record.allowStandardCommands,
      'commandPolicy.allowStandardCommands',
      true,
    );
    const allowWorkspaceTasks = optionalBoolean(
      record.allowWorkspaceTasks,
      'commandPolicy.allowWorkspaceTasks',
      true,
    );
    const commands = boundedArray(record.commands, 'commandPolicy.commands').map(parseCommandEntry);
    const tasks = boundedArray(record.tasks, 'commandPolicy.tasks').map(parseTaskEntry);
    const commandMap = new Map<string, CompiledCommandEntry>();
    for (const command of commands) {
      if (commandMap.has(command.entry.commandId)) {
        throw new CommandPolicyConfigurationError(
          `commandPolicy contains duplicate commandId ${command.entry.commandId}.`,
        );
      }
      commandMap.set(command.entry.commandId, command);
    }
    const taskKeys = new Set<string>();
    for (const task of tasks) {
      const key = `${task.rootAlias}\u0000${task.taskName}`;
      if (taskKeys.has(key)) {
        throw new CommandPolicyConfigurationError(
          `commandPolicy contains duplicate task ${task.rootAlias}:${task.taskName}.`,
        );
      }
      taskKeys.add(key);
    }
    this.#commands = commandMap;
    this.configuration = freezeDeep({
      allowStandardCommands,
      allowWorkspaceTasks,
      commands: commands.map((command) => command.entry),
      tasks,
    });
  }

  taskEntry(rootAlias: string, taskName: string): TaskAllowlistEntry | undefined {
    const configured = this.configuration.tasks.find((entry) =>
      entry.rootAlias === rootAlias && entry.taskName === taskName);
    if (configured !== undefined || !this.configuration.allowWorkspaceTasks) return configured;
    return Object.freeze({
      rootAlias,
      taskName,
      nonInteractive: true,
      allowDependencies: true,
      maxTimeoutMs: DEFAULT_TASK_TIMEOUT_MS,
    });
  }

  preflightCommand(
    input: Pick<ExecuteCommandInput, 'target' | 'timeoutMs'> & { readonly target: CommandTarget },
    workspaceTrusted: boolean,
  ): CommandPolicyDecision {
    if (!workspaceTrusted) return interactiveDenied('workspaceTrust');
    const variable = classifyCommandArgumentVariable(input.target.arguments ?? []);
    if (variable !== undefined) return interactiveDenied(variable);
    const standard = this.configuration.allowStandardCommands &&
        isStandardUserCommand(input.target.commandId)
      ? standardCommandEntry(input.target.commandId)
      : undefined;
    const risk = classifyCommandRisk(input.target.commandId);
    if (risk !== undefined && standard === undefined) {
      return interactiveDenied('uiInteraction', risk);
    }
    const compiled = standard ?? this.#commands.get(input.target.commandId);
    if (compiled === undefined) {
      return denied({
        code: 'COMMAND_NOT_ALLOWED',
        message: 'The command is neither a standard user command nor explicitly authorized.',
        retryable: false,
      });
    }
    const args = structuredClone(input.target.arguments ?? []) as JsonValue[];
    if (compiled.validateArguments === undefined) {
      if (args.length !== 0) {
        return denied({
          code: 'INVALID_ARGUMENT',
          message: 'This command authorization does not permit arguments.',
          retryable: false,
        });
      }
    } else if (!compiled.validateArguments(args)) {
      return denied({
        code: 'INVALID_ARGUMENT',
        message: `Command arguments do not match the configured closed schema: ${formatAjvErrors(compiled.validateArguments.errors)}`,
        retryable: false,
      });
    }
    const requestedTimeout = input.timeoutMs ?? 120_000;
    return Object.freeze({
      ok: true,
      entry: compiled.entry,
      arguments: freezeDeep(args),
      effectiveTimeoutMs: Math.min(requestedTimeout, compiled.entry.maxTimeoutMs),
    });
  }
}

export const createFailClosedCommandPolicyDecision = (
  value: unknown,
  input: Pick<ExecuteCommandInput, 'target' | 'timeoutMs'> & { readonly target: CommandTarget },
  workspaceTrusted: boolean,
): CommandPolicyDecision => {
  try {
    return new CommandPolicy(value).preflightCommand(input, workspaceTrusted);
  } catch (error) {
    const issue = error instanceof Error ? error.message : 'Invalid command policy configuration.';
    return denied({
      code: 'COMMAND_NOT_ALLOWED',
      message: 'The command policy configuration is invalid, so command execution is disabled.',
      retryable: false,
    }, { configurationIssue: issue });
  }
};
