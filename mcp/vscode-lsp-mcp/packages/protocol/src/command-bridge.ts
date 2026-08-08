import { canonicalizeJson } from './codec.js';
import type { ExecuteCommandInput, JsonValue, ToolResponseMap } from './dto.js';
import type { WorkspaceRouteIdentity } from './runtime.js';
import { assertToolOutput, normalizeToolInput } from './validation.js';
import { isWorkspaceId } from './workspace-identity.js';

export const COMMAND_EXECUTE_BRIDGE_METHOD = 'command.execute' as const;

export interface CommandExecuteBridgeRequest extends Omit<ExecuteCommandInput, 'workspaceId'> {
  readonly workspace: WorkspaceRouteIdentity;
  readonly saveBeforeRun: 'none' | 'active' | 'all';
  readonly timeoutMs: number;
  readonly maxOutputChars: number;
  readonly retainOutputLog: boolean;
}

const asRecord = (value: unknown, label: string): Record<string, unknown> => {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object.`);
  }
  return value as Record<string, unknown>;
};

const exactFields = (
  value: Record<string, unknown>,
  fields: readonly string[],
  label: string,
): void => {
  const allowed = new Set(fields);
  if (Object.keys(value).some((field) => !allowed.has(field))) {
    throw new TypeError(`${label} contains an unknown field.`);
  }
};

const parseWorkspace = (value: unknown): WorkspaceRouteIdentity => {
  const record = asRecord(value, 'command execute bridge request.workspace');
  exactFields(record, ['workspaceId', 'generation'], 'command execute bridge request.workspace');
  if (typeof record.workspaceId !== 'string' || !isWorkspaceId(record.workspaceId) ||
      !Number.isSafeInteger(record.generation) || (record.generation as number) < 1) {
    throw new TypeError('Command execute workspace identity is invalid.');
  }
  return Object.freeze({
    workspaceId: record.workspaceId,
    generation: record.generation as number,
  });
};

export const parseCommandExecuteBridgeRequest = (
  value: unknown,
): CommandExecuteBridgeRequest => {
  const record = asRecord(value, 'command execute bridge request');
  exactFields(
    record,
    ['workspace', 'target', 'saveBeforeRun', 'timeoutMs', 'maxOutputChars', 'retainOutputLog'],
    'command execute bridge request',
  );
  const workspace = parseWorkspace(record.workspace);
  const input = normalizeToolInput('execute_command', {
    workspaceId: workspace.workspaceId,
    target: record.target,
    ...(record.saveBeforeRun === undefined ? {} : { saveBeforeRun: record.saveBeforeRun }),
    ...(record.timeoutMs === undefined ? {} : { timeoutMs: record.timeoutMs }),
    ...(record.maxOutputChars === undefined ? {} : { maxOutputChars: record.maxOutputChars }),
    ...(record.retainOutputLog === undefined ? {} : { retainOutputLog: record.retainOutputLog }),
  });
  return Object.freeze({
    workspace,
    target: input.target,
    saveBeforeRun: input.saveBeforeRun ?? 'none',
    timeoutMs: input.timeoutMs ?? 120_000,
    maxOutputChars: input.maxOutputChars ?? 20_000,
    retainOutputLog: input.retainOutputLog ?? false,
  });
};

export const parseCommandExecuteBridgeResponse = (
  value: unknown,
): ToolResponseMap['execute_command'] => {
  assertToolOutput('execute_command', value);
  const canonical = canonicalizeJson(value);
  const freeze = (nested: JsonValue): JsonValue => {
    if (nested !== null && typeof nested === 'object' && !Object.isFrozen(nested)) {
      for (const child of Array.isArray(nested) ? nested : Object.values(nested)) freeze(child);
      Object.freeze(nested);
    }
    return nested;
  };
  return freeze(canonical) as unknown as ToolResponseMap['execute_command'];
};
