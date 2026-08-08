import {
  CAPABILITY_NAMES,
  SYMBOL_KINDS,
  type ErrorCode,
} from './dto.js';

export const JSON_SCHEMA_DIALECT = 'https://json-schema.org/draft/2020-12/schema';

export type JsonSchema = Record<string, unknown>;

export const schemaRef = (name: string): JsonSchema => ({ $ref: `#/$defs/${name}` });

const nonEmptyString = (): JsonSchema => ({ type: 'string', minLength: 1 });
const positiveInteger = (): JsonSchema => ({ type: 'integer', minimum: 1 });
const positionInteger = (): JsonSchema => ({ type: 'integer', minimum: 1 });

const nonEmptyStringArray = (maximum?: number): JsonSchema => ({
  type: 'array',
  minItems: 1,
  ...(maximum === undefined ? {} : { maxItems: maximum }),
  items: nonEmptyString(),
});

const objectSchema = (
  properties: Record<string, unknown>,
  required: readonly string[],
  additional: Record<string, unknown> = {},
): JsonSchema => ({
  type: 'object',
  properties,
  ...(required.length === 0 ? {} : { required: [...required] }),
  additionalProperties: false,
  ...additional,
});

const collectionSchema = (itemDefinition: string): JsonSchema =>
  objectSchema(
    {
      results: { type: 'array', items: schemaRef(itemDefinition) },
      available: { type: 'integer', minimum: 0 },
      warnings: nonEmptyStringArray(),
    },
    ['results', 'available'],
  );

const filesDetailsProperties = (): Record<string, unknown> => ({
  files: {
    type: 'array',
    minItems: 1,
    maxItems: 100,
    uniqueItems: true,
    items: nonEmptyString(),
  },
  additionalFiles: positiveInteger(),
});

const errorProperties = (
  code: ErrorCode,
  retryable: boolean,
  details?: JsonSchema,
): Record<string, unknown> => ({
  code: { const: code },
  message: nonEmptyString(),
  retryable: { const: retryable },
  action: nonEmptyString(),
  ...(details === undefined ? {} : { details }),
});

const simpleErrorSchema = (code: ErrorCode, retryable: boolean): JsonSchema =>
  objectSchema(errorProperties(code, retryable), ['code', 'message', 'retryable']);

const detailedErrorSchema = (
  code: ErrorCode,
  detailsDefinition: string,
): JsonSchema =>
  objectSchema(
    errorProperties(code, false, schemaRef(detailsDefinition)),
    ['code', 'message', 'retryable', 'details'],
  );

const workspaceDisconnectedSchemas = (): JsonSchema[] => [
  simpleErrorSchema('WORKSPACE_DISCONNECTED', true),
  objectSchema(
    errorProperties(
      'WORKSPACE_DISCONNECTED',
      true,
      objectSchema(
        {
          phase: { const: 'preflight' },
          outcome: { const: 'notStarted' },
        },
        ['phase', 'outcome'],
      ),
    ),
    ['code', 'message', 'retryable', 'details'],
  ),
  objectSchema(
    errorProperties(
      'WORKSPACE_DISCONNECTED',
      false,
      objectSchema(
        {
          phase: { enum: ['apply', 'command'] },
          outcome: { const: 'unknown' },
        },
        ['phase', 'outcome'],
      ),
    ),
    ['code', 'message', 'retryable', 'details'],
  ),
];

const toolErrorSchema = (): JsonSchema => {
  const nonRetryableSimpleCodes: ErrorCode[] = [
    'INVALID_ARGUMENT',
    'INVALID_RESULT_WINDOW',
    'ROOT_NOT_FOUND',
    'PATH_OUTSIDE_WORKSPACE',
    'DOCUMENT_NOT_FOUND',
    'POSITION_OUT_OF_RANGE',
    'PROVIDER_UNAVAILABLE',
    'PREVIEW_NOT_FOUND',
    'PREVIEW_EXPIRED',
    'RENAME_NO_EDITS',
    'ACTION_SET_NOT_FOUND',
    'COMMAND_NOT_ALLOWED',
  ];
  const retryableSimpleCodes: ErrorCode[] = [
    'WORKSPACE_NOT_FOUND',
    'PROVIDER_TIMEOUT',
    'INTERNAL_ERROR',
  ];

  return {
    oneOf: [
      ...nonRetryableSimpleCodes.map((code) => simpleErrorSchema(code, false)),
      ...retryableSimpleCodes.map((code) => simpleErrorSchema(code, true)),
      ...workspaceDisconnectedSchemas(),
      detailedErrorSchema('DOCUMENT_CHANGED', 'DocumentChangedDetails'),
      detailedErrorSchema('EDIT_CONFLICT', 'EditConflictDetails'),
      detailedErrorSchema('APPLY_FAILED', 'ApplyFailedDetails'),
      detailedErrorSchema('RENAME_SCOPE_VIOLATION', 'RenameScopeViolationDetails'),
      detailedErrorSchema('RENAME_IDENTITY_UNVERIFIED', 'RenameIdentityUnverifiedDetails'),
      detailedErrorSchema('PREVIEW_TOO_LARGE', 'PreviewTooLargeDetails'),
      detailedErrorSchema('ACTION_NOT_PREVIEWABLE', 'ActionNotPreviewableDetails'),
      detailedErrorSchema('INTERACTIVE_COMMAND', 'InteractiveCommandDetails'),
      detailedErrorSchema('COMMAND_TIMEOUT', 'CommandTimeoutDetails'),
      detailedErrorSchema('COMMAND_FAILED', 'CommandFailedDetails'),
    ],
  };
};

const rangeSchema = objectSchema(
  {
    startLine: positionInteger(),
    startColumn: positionInteger(),
    endLine: positionInteger(),
    endColumn: positionInteger(),
  },
  ['startLine', 'startColumn', 'endLine', 'endColumn'],
);

const hierarchySymbolSchema = objectSchema(
  {
    name: nonEmptyString(),
    kind: schemaRef('SymbolKind'),
    file: nonEmptyString(),
    line: positionInteger(),
    column: positionInteger(),
  },
  ['name', 'kind', 'file', 'line', 'column'],
);

const hierarchyParentRule: JsonSchema = {
  if: {
    properties: { depth: { const: 0 } },
    required: ['depth'],
  },
  then: { not: { required: ['parent'] } },
  else: { required: ['parent'] },
};

const previewHandleRule: JsonSchema = {
  if: {
    properties: { changes: { type: 'array', maxItems: 0 } },
    required: ['changes'],
  },
  then: { not: { required: ['previewId'] } },
  else: { required: ['previewId'] },
};

const actionSetHandleRule: JsonSchema = {
  if: {
    properties: { results: { type: 'array', maxItems: 0 } },
    required: ['results'],
  },
  then: { not: { required: ['actionSetId'] } },
  else: { required: ['actionSetId'] },
};

export const PUBLIC_SCHEMA_DEFS: Record<string, JsonSchema> = {
  SymbolKind: { enum: [...SYMBOL_KINDS] },
  CapabilityName: { enum: [...CAPABILITY_NAMES] },
  Range: rangeSchema,
  Workspace: objectSchema(
    {
      workspaceId: nonEmptyString(),
      name: nonEmptyString(),
      roots: {
        type: 'array',
        minItems: 1,
        uniqueItems: true,
        items: nonEmptyString(),
      },
    },
    ['workspaceId', 'name', 'roots'],
  ),
  HealthResult: objectSchema(
    {
      target: nonEmptyString(),
      status: { enum: ['healthy', 'degraded', 'unavailable', 'timedOut'] },
      issues: nonEmptyStringArray(),
    },
    ['target', 'status'],
  ),
  Capability: objectSchema(
    {
      name: schemaRef('CapabilityName'),
      status: { enum: ['available', 'unavailable', 'unknown', 'timedOut'] },
      reason: nonEmptyString(),
    },
    ['name', 'status'],
  ),
  SymbolHit: objectSchema(
    {
      name: nonEmptyString(),
      kind: schemaRef('SymbolKind'),
      file: nonEmptyString(),
      line: positionInteger(),
      column: positionInteger(),
      container: nonEmptyString(),
      snippet: nonEmptyString(),
    },
    ['name', 'kind', 'file', 'line', 'column'],
  ),
  DocumentSymbol: objectSchema(
    {
      kind: schemaRef('SymbolKind'),
      path: nonEmptyStringArray(),
      line: positionInteger(),
      column: positionInteger(),
      snippet: nonEmptyString(),
    },
    ['kind', 'path', 'line', 'column'],
  ),
  HoverInfo: objectSchema(
    {
      type: { const: 'hover' },
      text: nonEmptyString(),
    },
    ['type', 'text'],
  ),
  LocationInfo: objectSchema(
    {
      type: { enum: ['declaration', 'definition', 'typeDefinition', 'implementation'] },
      file: nonEmptyString(),
      line: positionInteger(),
      column: positionInteger(),
      snippet: nonEmptyString(),
    },
    ['type', 'file', 'line', 'column'],
  ),
  SignatureParameter: objectSchema(
    {
      label: nonEmptyString(),
      documentation: nonEmptyString(),
    },
    ['label'],
  ),
  SignatureInfo: objectSchema(
    {
      type: { const: 'signatureHelp' },
      label: nonEmptyString(),
      activeParameter: { type: 'integer', minimum: 0 },
      documentation: nonEmptyString(),
      parameters: {
        type: 'array',
        minItems: 1,
        items: schemaRef('SignatureParameter'),
      },
    },
    ['type', 'label'],
  ),
  SymbolInfoResult: {
    oneOf: [schemaRef('HoverInfo'), schemaRef('LocationInfo'), schemaRef('SignatureInfo')],
  },
  ReferenceHit: objectSchema(
    {
      file: nonEmptyString(),
      line: positionInteger(),
      column: positionInteger(),
      snippet: nonEmptyString(),
    },
    ['file', 'line', 'column'],
  ),
  HierarchySymbol: hierarchySymbolSchema,
  CallHierarchyEntry: objectSchema(
    {
      relation: { enum: ['root', 'incoming', 'outgoing'] },
      depth: { type: 'integer', minimum: 0 },
      symbol: schemaRef('HierarchySymbol'),
      parent: schemaRef('HierarchySymbol'),
      callSites: {
        type: 'array',
        minItems: 1,
        items: schemaRef('Range'),
      },
    },
    ['relation', 'depth', 'symbol'],
    { allOf: [hierarchyParentRule] },
  ),
  TypeHierarchyEntry: objectSchema(
    {
      relation: { enum: ['root', 'supertype', 'subtype'] },
      depth: { type: 'integer', minimum: 0 },
      symbol: schemaRef('HierarchySymbol'),
      parent: schemaRef('HierarchySymbol'),
    },
    ['relation', 'depth', 'symbol'],
    { allOf: [hierarchyParentRule] },
  ),
  DiagnosticRelatedInformation: objectSchema(
    {
      file: nonEmptyString(),
      range: schemaRef('Range'),
      message: nonEmptyString(),
    },
    ['file', 'range', 'message'],
  ),
  Diagnostic: objectSchema(
    {
      file: nonEmptyString(),
      range: schemaRef('Range'),
      severity: { enum: ['error', 'warning', 'information', 'hint'] },
      message: nonEmptyString(),
      code: {
        oneOf: [nonEmptyString(), { type: 'integer' }],
      },
      source: nonEmptyString(),
      tags: {
        type: 'array',
        minItems: 1,
        uniqueItems: true,
        items: { enum: ['unnecessary', 'deprecated'] },
      },
      relatedInformation: {
        type: 'array',
        minItems: 1,
        items: schemaRef('DiagnosticRelatedInformation'),
      },
    },
    ['file', 'range', 'severity', 'message'],
  ),
  TextEdit: objectSchema(
    {
      range: schemaRef('Range'),
      oldText: { type: 'string' },
      newText: { type: 'string' },
    },
    ['range', 'oldText', 'newText'],
  ),
  TextChange: objectSchema(
    {
      kind: { const: 'text' },
      file: nonEmptyString(),
      edits: {
        type: 'array',
        minItems: 1,
        items: schemaRef('TextEdit'),
      },
    },
    ['kind', 'file', 'edits'],
  ),
  Preview: objectSchema(
    {
      previewId: nonEmptyString(),
      changes: { type: 'array', items: schemaRef('TextChange') },
      warnings: nonEmptyStringArray(),
    },
    ['changes'],
    { allOf: [previewHandleRule] },
  ),
  ApplyResult: objectSchema(
    {
      changedFiles: {
        type: 'array',
        minItems: 1,
        uniqueItems: true,
        items: nonEmptyString(),
      },
    },
    ['changedFiles'],
  ),
  CodeAction: objectSchema(
    {
      actionId: nonEmptyString(),
      title: nonEmptyString(),
      kind: nonEmptyString(),
    },
    ['actionId', 'title'],
  ),
  CodeActionSet: objectSchema(
    {
      actionSetId: nonEmptyString(),
      results: { type: 'array', items: schemaRef('CodeAction') },
      available: { type: 'integer', minimum: 0 },
      warnings: nonEmptyStringArray(),
    },
    ['results', 'available'],
    { allOf: [actionSetHandleRule] },
  ),
  JsonValue: {
    oneOf: [
      { type: 'null' },
      { type: 'boolean' },
      { type: 'number' },
      { type: 'string' },
      { type: 'array', items: schemaRef('JsonValue') },
      { type: 'object', additionalProperties: schemaRef('JsonValue') },
    ],
  },
  PublicCommandResultValue: {
    oneOf: [
      { const: true },
      { type: 'number' },
      { type: 'array', minItems: 1, items: schemaRef('JsonValue') },
      {
        type: 'object',
        minProperties: 1,
        additionalProperties: schemaRef('JsonValue'),
      },
    ],
  },
  CommandResult: objectSchema(
    {
      result: schemaRef('PublicCommandResultValue'),
      output: nonEmptyString(),
      outputTruncated: { const: true },
      warnings: nonEmptyStringArray(),
      outputLog: schemaRef('TaskOutputLog'),
    },
    [],
    {
      allOf: [
        { not: { required: ['result', 'output'] } },
        {
          if: { required: ['outputTruncated'] },
          then: { required: ['output'] },
        },
      ],
    },
  ),
  TaskOutputLog: objectSchema(
    {
      path: nonEmptyString(),
      lineCount: { type: 'integer', minimum: 0 },
      byteCount: { type: 'integer', minimum: 0 },
      encoding: { const: 'utf-8' },
      truncated: { type: 'boolean' },
    },
    ['path', 'lineCount', 'byteCount', 'encoding', 'truncated'],
  ),
  WorkspaceDisconnectedDetails: {
    oneOf: [
      objectSchema(
        {
          phase: { const: 'preflight' },
          outcome: { const: 'notStarted' },
        },
        ['phase', 'outcome'],
      ),
      objectSchema(
        {
          phase: { enum: ['apply', 'command'] },
          outcome: { const: 'unknown' },
        },
        ['phase', 'outcome'],
      ),
    ],
  },
  DocumentChangedDetails: objectSchema(
    {
      reason: { enum: ['content', 'version', 'existence', 'workspace'] },
      ...filesDetailsProperties(),
    },
    ['reason'],
  ),
  EditConflictDetails: objectSchema(
    {
      reason: {
        enum: [
          'overlappingEdits',
          'rangeOutOfBounds',
          'unsupportedEdit',
          'ambiguousOperationOrder',
        ],
      },
      ...filesDetailsProperties(),
    },
    ['reason'],
  ),
  ApplyFailedDetails: objectSchema(
    {
      stage: { enum: ['apply', 'readback'] },
      outcome: { enum: ['notApplied', 'unknown', 'postconditionFailed'] },
    },
    ['stage', 'outcome'],
  ),
  RenameScopeViolationDetails: objectSchema(
    {
      files: {
        type: 'array',
        minItems: 1,
        maxItems: 10,
        uniqueItems: true,
        items: nonEmptyString(),
      },
      additionalFiles: positiveInteger(),
      totalFiles: positiveInteger(),
    },
    ['files', 'totalFiles'],
  ),
  RenameIdentityUnverifiedDetails: objectSchema(
    {
      reason: {
        enum: [
          'targetUnresolved',
          'editUnresolved',
          'mismatchedSymbol',
          'textMismatch',
          'budgetExceeded',
          'providerFailed',
          'providerTimedOut',
        ],
      },
      checkedEdits: { type: 'integer', minimum: 0 },
      totalEdits: positiveInteger(),
      files: {
        type: 'array',
        minItems: 1,
        maxItems: 10,
        uniqueItems: true,
        items: nonEmptyString(),
      },
      additionalFiles: positiveInteger(),
    },
    ['reason', 'checkedEdits', 'totalEdits'],
  ),
  PreviewTooLargeDetails: objectSchema(
    {
      changedFiles: { type: 'integer', minimum: 0 },
      edits: { type: 'integer', minimum: 0 },
      textCharacters: { type: 'integer', minimum: 0 },
      serializedBytes: { type: 'integer', minimum: 0 },
      limits: objectSchema(
        {
          changedFiles: positiveInteger(),
          edits: positiveInteger(),
          textCharacters: positiveInteger(),
          serializedBytes: positiveInteger(),
        },
        ['changedFiles', 'edits', 'textCharacters', 'serializedBytes'],
      ),
    },
    ['changedFiles', 'edits', 'textCharacters', 'serializedBytes', 'limits'],
  ),
  ActionNotPreviewableDetails: objectSchema(
    {
      reason: {
        enum: [
          'missingEdit',
          'containsCommand',
          'resourceOperationsUnsupported',
          'unsupportedEdit',
          'cachedActionInvalid',
        ],
      },
    },
    ['reason'],
  ),
  InteractiveCommandDetails: objectSchema(
    {
      targetKind: { enum: ['command', 'task'] },
      reason: {
        enum: [
          'inputVariable',
          'commandVariable',
          'uiInteraction',
          'workspaceTrust',
          'customExecution',
          'backgroundTask',
          'unknownInteractivity',
        ],
      },
    },
    ['targetKind', 'reason'],
  ),
  CommandTimeoutDetails: {
    oneOf: [
      objectSchema(
        {
          targetKind: { const: 'command' },
          timeoutMs: { type: 'integer', minimum: 1_000, maximum: 600_000 },
          outcome: { enum: ['notStarted', 'unknown'] },
        },
        ['targetKind', 'timeoutMs', 'outcome'],
      ),
      objectSchema(
        {
          targetKind: { const: 'task' },
          timeoutMs: { type: 'integer', minimum: 1_000, maximum: 600_000 },
          outcome: { enum: ['notStarted', 'terminated', 'unknown'] },
          outputLog: schemaRef('TaskOutputLog'),
        },
        ['targetKind', 'timeoutMs', 'outcome'],
      ),
    ],
  },
  CommandFailedDetails: objectSchema(
    {
      targetKind: { enum: ['command', 'task'] },
      reason: {
        enum: [
          'saveFailed',
          'rejected',
          'nonZeroExit',
          'cancelled',
          'completionUnverifiable',
          'alreadyRunning',
        ],
      },
      outcome: { enum: ['notStarted', 'failed', 'terminated', 'unknown'] },
      exitCode: {
        type: 'integer',
        not: { const: 0 },
      },
      outputLog: schemaRef('TaskOutputLog'),
    },
    ['targetKind', 'reason', 'outcome'],
    {
      allOf: [
        {
          if: {
            properties: { reason: { const: 'nonZeroExit' } },
            required: ['reason'],
          },
          then: {
            required: ['exitCode'],
            properties: { outcome: { const: 'failed' } },
          },
          else: { not: { required: ['exitCode'] } },
        },
        {
          if: { required: ['outputLog'] },
          then: {
            properties: { targetKind: { const: 'task' } },
            required: ['targetKind'],
          },
        },
      ],
    },
  ),
  ToolError: toolErrorSchema(),
  WorkspaceCollection: collectionSchema('Workspace'),
  HealthResultCollection: collectionSchema('HealthResult'),
  CapabilityCollection: collectionSchema('Capability'),
  SymbolHitCollection: collectionSchema('SymbolHit'),
  DocumentSymbolCollection: collectionSchema('DocumentSymbol'),
  SymbolInfoResultCollection: collectionSchema('SymbolInfoResult'),
  ReferenceHitCollection: collectionSchema('ReferenceHit'),
  CallHierarchyEntryCollection: collectionSchema('CallHierarchyEntry'),
  TypeHierarchyEntryCollection: collectionSchema('TypeHierarchyEntry'),
  DiagnosticCollection: collectionSchema('Diagnostic'),
};

const requirePublicDefinition = (name: string): JsonSchema => {
  const definition = PUBLIC_SCHEMA_DEFS[name];
  if (!definition) {
    throw new Error(`Missing public schema definition: ${name}`);
  }
  return definition;
};

export const INPUT_SCHEMA_DEFS: Record<string, JsonSchema> = {
  Range: requirePublicDefinition('Range'),
  SymbolKind: requirePublicDefinition('SymbolKind'),
  JsonValue: requirePublicDefinition('JsonValue'),
};

export const cloneSchema = <T>(schema: T): T => structuredClone(schema);
