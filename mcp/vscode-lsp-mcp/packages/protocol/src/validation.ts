import Ajv2020 from 'ajv/dist/2020.js';
import type { ErrorObject, ValidateFunction } from 'ajv';
import {
  CAPABILITY_NAMES,
  TOOL_NAMES,
  type JsonObject,
  type Range,
  type ToolInputMap,
  type ToolName,
  type ToolResponseMap,
} from './dto.js';
import { isSupportedLogicalGlob } from './collection.js';
import { getToolDefinition, TOOL_DEFINITIONS } from './tool-registry.js';

export type ProtocolValidationCode = 'INVALID_ARGUMENT' | 'INVALID_RESULT_WINDOW';

export class ProtocolValidationError extends Error {
  readonly code: ProtocolValidationCode;
  readonly toolName: ToolName;
  readonly direction: 'input' | 'output';
  readonly issues: readonly string[];

  constructor(options: {
    readonly code: ProtocolValidationCode;
    readonly toolName: ToolName;
    readonly direction: 'input' | 'output';
    readonly issues: readonly string[];
  }) {
    super(`${options.toolName} ${options.direction} validation failed: ${options.issues.join('; ')}`);
    this.name = 'ProtocolValidationError';
    this.code = options.code;
    this.toolName = options.toolName;
    this.direction = options.direction;
    this.issues = Object.freeze([...options.issues]);
  }
}

export const createProtocolAjv = (): Ajv2020 =>
  new Ajv2020({
    allErrors: true,
    allowUnionTypes: false,
    strict: true,
    strictRequired: false,
    useDefaults: false,
    validateFormats: false,
  });

const validator = createProtocolAjv();
const inputValidators = new Map<ToolName, ValidateFunction>();
const outputValidators = new Map<ToolName, ValidateFunction>();

for (const definition of TOOL_DEFINITIONS) {
  inputValidators.set(definition.name, validator.compile(definition.inputSchema));
  outputValidators.set(definition.name, validator.compile(definition.outputSchema));
}

const formatErrors = (errors: ErrorObject[] | null | undefined): string[] =>
  (errors ?? []).map((error) => {
    const location = error.instancePath.length === 0 ? '$' : `$${error.instancePath}`;
    return `${location} ${error.message ?? error.keyword}`;
  });

const getValidator = (
  validators: ReadonlyMap<ToolName, ValidateFunction>,
  toolName: ToolName,
): ValidateFunction => {
  const validate = validators.get(toolName);
  if (!validate) {
    throw new Error(`No validator registered for ${toolName}.`);
  }
  return validate;
};

export function assertToolInput<K extends ToolName>(
  toolName: K,
  value: unknown,
): asserts value is ToolInputMap[K] {
  const validate = getValidator(inputValidators, toolName);
  if (!validate(value)) {
    throw new ProtocolValidationError({
      code: 'INVALID_ARGUMENT',
      toolName,
      direction: 'input',
      issues: formatErrors(validate.errors),
    });
  }
}

export function assertToolOutput<K extends ToolName>(
  toolName: K,
  value: unknown,
): asserts value is ToolResponseMap[K] {
  const validate = getValidator(outputValidators, toolName);
  if (!validate(value)) {
    throw new ProtocolValidationError({
      code: 'INVALID_ARGUMENT',
      toolName,
      direction: 'output',
      issues: formatErrors(validate.errors),
    });
  }
}

const WINDOWED_TOOLS = new Set<ToolName>([
  'list_workspaces',
  'health_check',
  'get_capabilities',
  'workspace_symbols',
  'document_symbols',
  'symbol_info',
  'get_references',
  'get_call_hierarchy',
  'get_type_hierarchy',
  'get_diagnostics',
  'code_actions',
]);

const deepFreeze = <T>(value: T, seen = new Set<object>()): T => {
  if (value === null || typeof value !== 'object' || seen.has(value)) {
    return value;
  }
  seen.add(value);
  for (const nested of Object.values(value)) {
    deepFreeze(nested, seen);
  }
  return Object.freeze(value);
};

const failCrossField = (
  toolName: ToolName,
  code: ProtocolValidationCode,
  issue: string,
): never => {
  throw new ProtocolValidationError({
    code,
    toolName,
    direction: 'input',
    issues: [issue],
  });
};

const applyWindowDefaults = (toolName: ToolName, input: Record<string, unknown>): void => {
  const start = input.resultStart ?? 1;
  const end = input.resultEnd ?? ((start as number) + 19);

  if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end)) {
    failCrossField(toolName, 'INVALID_RESULT_WINDOW', 'result window must use safe integers');
  }

  const typedStart = start as number;
  const typedEnd = end as number;
  if (typedEnd < typedStart) {
    failCrossField(toolName, 'INVALID_RESULT_WINDOW', 'resultEnd must not precede resultStart');
  }
  if (typedEnd - typedStart + 1 > 100) {
    failCrossField(toolName, 'INVALID_RESULT_WINDOW', 'result window must contain at most 100 items');
  }

  input.resultStart = typedStart;
  input.resultEnd = typedEnd;
};

const comparePosition = (
  leftLine: number,
  leftColumn: number,
  rightLine: number,
  rightColumn: number,
): number => leftLine - rightLine || leftColumn - rightColumn;

const validateRangeOrder = (toolName: ToolName, range: Range): void => {
  if (
    comparePosition(
      range.endLine,
      range.endColumn,
      range.startLine,
      range.startColumn,
    ) < 0
  ) {
    failCrossField(toolName, 'INVALID_ARGUMENT', 'range end must not precede range start');
  }
};

const validateGlobFields = (toolName: ToolName, input: Record<string, unknown>): void => {
  for (const field of ['includeGlobs', 'excludeGlobs'] as const) {
    const patterns = input[field] as string[] | undefined;
    if (patterns?.some((pattern) => !isSupportedLogicalGlob(pattern))) {
      failCrossField(
        toolName,
        'INVALID_ARGUMENT',
        `${field} contains an unsupported or malformed glob`,
      );
    }
  }
};

const applyToolDefaults = (toolName: ToolName, input: Record<string, unknown>): void => {
  if (WINDOWED_TOOLS.has(toolName)) {
    applyWindowDefaults(toolName, input);
  }

  switch (toolName) {
    case 'list_workspaces':
    case 'health_check':
    case 'rename_apply':
    case 'code_action_preview':
    case 'code_action_apply':
    case 'format_apply':
      break;
    case 'rename_preview':
      validateGlobFields(toolName, input);
      break;
    case 'get_capabilities':
      input.capabilities ??= [...CAPABILITY_NAMES];
      break;
    case 'workspace_symbols':
      input.contextLines ??= 0;
      validateGlobFields(toolName, input);
      break;
    case 'document_symbols':
      input.contextLines ??= 0;
      break;
    case 'symbol_info':
      input.include ??= ['definition'];
      input.contextLines ??= 0;
      validateGlobFields(toolName, input);
      break;
    case 'get_references':
      input.contextLines ??= 0;
      validateGlobFields(toolName, input);
      break;
    case 'verify_symbol_candidates':
      break;
    case 'get_call_hierarchy':
      input.direction ??= 'both';
      input.maxDepth ??= 1;
      break;
    case 'get_type_hierarchy':
      input.direction ??= 'both';
      input.maxDepth ??= 1;
      break;
    case 'get_diagnostics':
      input.scope ??= input.files === undefined ? 'modifiedFiles' : 'files';
      if (input.scope === 'files' && input.files === undefined) {
        throw new ProtocolValidationError({
          code: 'INVALID_ARGUMENT',
          toolName,
          direction: 'input',
          issues: ['$.files is required when $.scope is files'],
        });
      }
      if (input.scope !== 'files' && input.files !== undefined) {
        throw new ProtocolValidationError({
          code: 'INVALID_ARGUMENT',
          toolName,
          direction: 'input',
          issues: ['$.files is only allowed when $.scope is files'],
        });
      }
      input.severities ??= ['error', 'warning', 'information', 'hint'];
      input.includeRelatedInformation ??= false;
      break;
    case 'code_actions':
      validateRangeOrder(toolName, input.range as Range);
      break;
    case 'format_preview':
      if (input.range !== undefined) {
        validateRangeOrder(toolName, input.range as Range);
      }
      break;
    case 'execute_command': {
      input.saveBeforeRun ??= 'none';
      input.timeoutMs ??= 120_000;
      input.maxOutputChars ??= 20_000;
      input.retainOutputLog ??= false;
      const target = input.target as Record<string, unknown>;
      if (target.kind === 'command') {
        target.arguments ??= [];
      }
      break;
    }
    default: {
      const exhaustive: never = toolName;
      throw new Error(`Unhandled tool defaults: ${exhaustive}`);
    }
  }
};

export const normalizeToolInput = <K extends ToolName>(
  toolName: K,
  value: unknown,
): Readonly<ToolInputMap[K]> => {
  assertToolInput(toolName, value);
  const normalized = structuredClone(value) as unknown as Record<string, unknown>;
  applyToolDefaults(toolName, normalized);
  return deepFreeze(normalized) as Readonly<ToolInputMap[K]>;
};

export interface SchemaCompilationResult {
  readonly toolName: ToolName;
  readonly direction: 'input' | 'output';
}

export const compileAllToolSchemasIndependently = (): readonly SchemaCompilationResult[] => {
  const results: SchemaCompilationResult[] = [];
  for (const toolName of TOOL_NAMES) {
    const definition = getToolDefinition(toolName);
    createProtocolAjv().compile(definition.inputSchema);
    results.push({ toolName, direction: 'input' });
    createProtocolAjv().compile(definition.outputSchema);
    results.push({ toolName, direction: 'output' });
  }
  return Object.freeze(results);
};

export const isJsonObject = (value: unknown): value is JsonObject =>
  value !== null && typeof value === 'object' && !Array.isArray(value);
