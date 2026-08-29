import {
  CAPABILITY_NAMES,
  SYMBOL_INFO_INCLUDES,
  type ToolName,
} from './dto.js';
import {
  cloneSchema,
  INPUT_SCHEMA_DEFS,
  JSON_SCHEMA_DIALECT,
  type JsonSchema,
} from './schema-definitions.js';

const nonEmptyString = (): JsonSchema => ({ type: 'string', minLength: 1 });
const positionInteger = (): JsonSchema => ({ type: 'integer', minimum: 1 });
const providerTimeoutProperty = (): JsonSchema => ({
  type: 'integer',
  minimum: 1_000,
  maximum: 300_000,
});

const resultWindowProperties = (): Record<string, JsonSchema> => ({
  resultStart: { type: 'integer', minimum: 1, default: 1 },
  resultEnd: { type: 'integer', minimum: 1 },
});

const pointProperties = (): Record<string, JsonSchema> => ({
  workspaceId: nonEmptyString(),
  file: nonEmptyString(),
  line: positionInteger(),
  column: positionInteger(),
});

const globProperties = (): Record<string, JsonSchema> => ({
  includeGlobs: {
    type: 'array',
    minItems: 1,
    maxItems: 20,
    items: nonEmptyString(),
  },
  excludeGlobs: {
    type: 'array',
    minItems: 1,
    maxItems: 20,
    items: nonEmptyString(),
  },
});

const contextLinesProperty = (): JsonSchema => ({
  type: 'integer',
  minimum: 0,
  maximum: 5,
  default: 0,
});

const inputSchema = (
  properties: Record<string, unknown>,
  required: readonly string[] = [],
  extras: Record<string, unknown> = {},
  definitions: readonly string[] = [],
): JsonSchema => ({
  $schema: JSON_SCHEMA_DIALECT,
  type: 'object',
  properties,
  ...(required.length === 0 ? {} : { required: [...required] }),
  additionalProperties: false,
  ...(definitions.length === 0
    ? {}
    : {
        $defs: Object.fromEntries(
          definitions.map((name) => [name, cloneSchema(INPUT_SCHEMA_DEFS[name])]),
        ),
      }),
  ...extras,
});

const previewApplySchema = (): JsonSchema =>
  inputSchema(
    {
      previewId: nonEmptyString(),
    },
    ['previewId'],
  );

export const INPUT_SCHEMAS: Readonly<Record<ToolName, JsonSchema>> = {
  list_workspaces: inputSchema({
    ...resultWindowProperties(),
  }),
  health_check: inputSchema(
    {
      workspaceId: nonEmptyString(),
      file: nonEmptyString(),
      ...resultWindowProperties(),
    },
    [],
    {
      dependentRequired: { file: ['workspaceId'] },
    },
  ),
  get_capabilities: inputSchema(
    {
      workspaceId: nonEmptyString(),
      file: nonEmptyString(),
      capabilities: {
        type: 'array',
        minItems: 1,
        uniqueItems: true,
        items: { enum: [...CAPABILITY_NAMES] },
      },
      ...resultWindowProperties(),
    },
    ['workspaceId'],
  ),
  workspace_symbols: inputSchema(
    {
      workspaceId: nonEmptyString(),
      query: { type: 'string', minLength: 1, maxLength: 500 },
      kinds: {
        type: 'array',
        minItems: 1,
        uniqueItems: true,
        items: { $ref: '#/$defs/SymbolKind' },
      },
      ...globProperties(),
      contextLines: contextLinesProperty(),
      ...resultWindowProperties(),
    },
    ['workspaceId', 'query'],
    {},
    ['SymbolKind'],
  ),
  document_symbols: inputSchema(
    {
      workspaceId: nonEmptyString(),
      file: nonEmptyString(),
      kinds: {
        type: 'array',
        minItems: 1,
        uniqueItems: true,
        items: { $ref: '#/$defs/SymbolKind' },
      },
      maxDepth: { type: 'integer', minimum: 0, maximum: 100 },
      nameEquals: nonEmptyString(),
      pathEquals: {
        type: 'array',
        minItems: 1,
        maxItems: 101,
        items: nonEmptyString(),
      },
      includeRange: { type: 'boolean', default: false },
      contextLines: contextLinesProperty(),
      ...resultWindowProperties(),
    },
    ['workspaceId', 'file'],
    {},
    ['SymbolKind'],
  ),
  symbol_info: inputSchema(
    {
      ...pointProperties(),
      ...globProperties(),
      include: {
        type: 'array',
        minItems: 1,
        uniqueItems: true,
        default: ['definition'],
        items: { enum: [...SYMBOL_INFO_INCLUDES] },
      },
      contextLines: contextLinesProperty(),
      ...resultWindowProperties(),
    },
    ['workspaceId', 'file', 'line', 'column'],
  ),
  get_references: inputSchema(
    {
      ...pointProperties(),
      ...globProperties(),
      contextLines: contextLinesProperty(),
      timeoutMs: providerTimeoutProperty(),
      ...resultWindowProperties(),
    },
    ['workspaceId', 'file', 'line', 'column'],
  ),
  verify_symbol_candidates: inputSchema(
    {
      ...pointProperties(),
      candidates: {
        type: 'array',
        minItems: 1,
        maxItems: 100,
        uniqueItems: true,
        items: {
          type: 'object',
          properties: {
            file: nonEmptyString(),
            line: positionInteger(),
            column: positionInteger(),
          },
          required: ['file', 'line', 'column'],
          additionalProperties: false,
        },
      },
      timeoutMs: providerTimeoutProperty(),
    },
    ['workspaceId', 'file', 'line', 'column', 'candidates'],
  ),
  get_call_hierarchy: inputSchema(
    {
      ...pointProperties(),
      direction: { enum: ['incoming', 'outgoing', 'both'], default: 'both' },
      maxDepth: { type: 'integer', minimum: 0, maximum: 5, default: 1 },
      ...resultWindowProperties(),
    },
    ['workspaceId', 'file', 'line', 'column'],
  ),
  get_type_hierarchy: inputSchema(
    {
      ...pointProperties(),
      direction: { enum: ['supertypes', 'subtypes', 'both'], default: 'both' },
      maxDepth: { type: 'integer', minimum: 0, maximum: 5, default: 1 },
      ...resultWindowProperties(),
    },
    ['workspaceId', 'file', 'line', 'column'],
  ),
  get_diagnostics: inputSchema(
    {
      workspaceId: nonEmptyString(),
      scope: { enum: ['files', 'modifiedFiles', 'workspace'], default: 'modifiedFiles' },
      files: {
        type: 'array',
        minItems: 1,
        maxItems: 200,
        uniqueItems: true,
        items: nonEmptyString(),
      },
      severities: {
        type: 'array',
        minItems: 1,
        uniqueItems: true,
        default: ['error', 'warning', 'information', 'hint'],
        items: { enum: ['error', 'warning', 'information', 'hint'] },
      },
      sources: {
        type: 'array',
        minItems: 1,
        maxItems: 50,
        uniqueItems: true,
        items: nonEmptyString(),
      },
      includeRelatedInformation: { type: 'boolean', default: false },
      ...resultWindowProperties(),
    },
    ['workspaceId'],
  ),
  rename_preview: inputSchema(
    {
      ...pointProperties(),
      newName: { type: 'string', minLength: 1, maxLength: 1_000 },
      ...globProperties(),
      timeoutMs: providerTimeoutProperty(),
    },
    ['workspaceId', 'file', 'line', 'column', 'newName', 'includeGlobs'],
  ),
  rename_apply: previewApplySchema(),
  code_actions: inputSchema(
    {
      workspaceId: nonEmptyString(),
      file: nonEmptyString(),
      range: { $ref: '#/$defs/Range' },
      onlyKinds: {
        type: 'array',
        minItems: 1,
        maxItems: 50,
        uniqueItems: true,
        items: nonEmptyString(),
      },
      ...resultWindowProperties(),
    },
    ['workspaceId', 'file', 'range'],
    {},
    ['Range'],
  ),
  code_action_preview: inputSchema(
    {
      actionSetId: nonEmptyString(),
      actionId: nonEmptyString(),
    },
    ['actionSetId', 'actionId'],
  ),
  code_action_apply: previewApplySchema(),
  format_preview: inputSchema(
    {
      workspaceId: nonEmptyString(),
      file: nonEmptyString(),
      range: { $ref: '#/$defs/Range' },
      options: {
        type: 'object',
        minProperties: 1,
        properties: {
          tabSize: { type: 'integer', minimum: 1, maximum: 32 },
          insertSpaces: { type: 'boolean' },
        },
        additionalProperties: false,
      },
    },
    ['workspaceId', 'file'],
    {},
    ['Range'],
  ),
  format_apply: previewApplySchema(),
  execute_command: inputSchema(
    {
      workspaceId: nonEmptyString(),
      target: {
        oneOf: [
          {
            type: 'object',
            properties: {
              kind: { const: 'command' },
              commandId: nonEmptyString(),
              arguments: { type: 'array', default: [], items: true },
            },
            required: ['kind', 'commandId'],
            additionalProperties: false,
          },
          {
            type: 'object',
            properties: {
              kind: { const: 'task' },
              taskName: nonEmptyString(),
              taskRoot: nonEmptyString(),
            },
            required: ['kind', 'taskName'],
            additionalProperties: false,
          },
        ],
      },
      saveBeforeRun: { enum: ['none', 'active', 'all'], default: 'none' },
      timeoutMs: {
        type: 'integer',
        minimum: 1_000,
        maximum: 600_000,
        default: 120_000,
      },
      maxOutputChars: {
        type: 'integer',
        minimum: 1_000,
        maximum: 200_000,
        default: 20_000,
      },
      retainOutputLog: { type: 'boolean', default: false },
    },
    ['workspaceId', 'target'],
  ),
};
