import assert from 'node:assert/strict';
import test from 'node:test';
import Ajv2020 from 'ajv/dist/2020.js';
import {
  CAPABILITY_NAMES,
  JSON_SCHEMA_DIALECT,
  PUBLIC_SCHEMA_DEFS,
  ProtocolValidationError,
  TOOL_DEFINITIONS,
  TOOL_NAMES,
  assertToolInput,
  assertToolOutput,
  compileAllToolSchemasIndependently,
  normalizeToolInput,
  type ToolInputMap,
  type ToolName,
  type ToolOutputDataMap,
} from './index.js';

const validInputs: ToolInputMap = {
  list_workspaces: {},
  health_check: {},
  get_capabilities: { workspaceId: 'workspace-1' },
  workspace_symbols: { workspaceId: 'workspace-1', query: 'Widget' },
  document_symbols: { workspaceId: 'workspace-1', file: 'src/widget.ts' },
  symbol_info: {
    workspaceId: 'workspace-1',
    file: 'src/widget.ts',
    line: 1,
    column: 1,
  },
  get_references: {
    workspaceId: 'workspace-1',
    file: 'src/widget.ts',
    line: 1,
    column: 1,
  },
  get_call_hierarchy: {
    workspaceId: 'workspace-1',
    file: 'src/widget.ts',
    line: 1,
    column: 1,
  },
  get_type_hierarchy: {
    workspaceId: 'workspace-1',
    file: 'src/widget.ts',
    line: 1,
    column: 1,
  },
  get_diagnostics: { workspaceId: 'workspace-1' },
  rename_preview: {
    workspaceId: 'workspace-1',
    file: 'src/widget.ts',
    line: 1,
    column: 1,
    newName: 'RenamedWidget',
    includeGlobs: ['src/**'],
  },
  rename_apply: { previewId: 'pv_rename' },
  code_actions: {
    workspaceId: 'workspace-1',
    file: 'src/widget.ts',
    range: { startLine: 1, startColumn: 1, endLine: 1, endColumn: 1 },
  },
  code_action_preview: { actionSetId: 'as_1', actionId: 'ac_1' },
  code_action_apply: { previewId: 'pv_action' },
  format_preview: { workspaceId: 'workspace-1', file: 'src/widget.ts' },
  format_apply: { previewId: 'pv_format' },
  execute_command: {
    workspaceId: 'workspace-1',
    target: { kind: 'command', commandId: 'example.safeCommand' },
  },
};

const emptyCollection = { results: [], available: 0 } as const;

const validSuccessData: ToolOutputDataMap = {
  list_workspaces: emptyCollection,
  health_check: emptyCollection,
  get_capabilities: emptyCollection,
  workspace_symbols: emptyCollection,
  document_symbols: emptyCollection,
  symbol_info: emptyCollection,
  get_references: emptyCollection,
  get_call_hierarchy: emptyCollection,
  get_type_hierarchy: emptyCollection,
  get_diagnostics: emptyCollection,
  rename_preview: { changes: [] },
  rename_apply: { changedFiles: ['src/widget.ts'] },
  code_actions: { results: [], available: 0 },
  code_action_preview: { changes: [] },
  code_action_apply: { changedFiles: ['src/widget.ts'] },
  format_preview: { changes: [] },
  format_apply: { changedFiles: ['src/widget.ts'] },
  execute_command: {},
};

const invalidArgumentEnvelope = {
  ok: false,
  error: {
    code: 'INVALID_ARGUMENT',
    message: 'Invalid input.',
    retryable: false,
  },
} as const;

test('registry is the exact frozen 18-tool contract', () => {
  assert.equal(TOOL_DEFINITIONS.length, 18);
  assert.deepEqual(TOOL_DEFINITIONS.map((definition) => definition.name), TOOL_NAMES);
  assert.ok(TOOL_DEFINITIONS.every((definition) => definition.execution.taskSupport === 'forbidden'));
  assert.ok(Object.isFrozen(TOOL_DEFINITIONS));

  const destructiveTools = TOOL_DEFINITIONS
    .filter((definition) => definition.annotations.destructiveHint)
    .map((definition) => definition.name);
  assert.deepEqual(destructiveTools, [
    'rename_apply',
    'code_action_apply',
    'format_apply',
    'execute_command',
  ]);
});

test('all 36 schemas compile independently as Draft 2020-12 objects', () => {
  const compiled = compileAllToolSchemasIndependently();
  assert.equal(compiled.length, 36);
  assert.equal(new Set(compiled.map((item) => `${item.toolName}:${item.direction}`)).size, 36);

  for (const definition of TOOL_DEFINITIONS) {
    assert.equal(definition.inputSchema.$schema, JSON_SCHEMA_DIALECT);
    assert.equal(definition.inputSchema.type, 'object');
    assert.equal(definition.inputSchema.additionalProperties, false);
    assert.equal(definition.outputSchema.$schema, JSON_SCHEMA_DIALECT);
    assert.equal(definition.outputSchema.type, 'object');
    assert.ok(Array.isArray(definition.outputSchema.oneOf));
  }
});

test('every public definition compiles as a standalone Draft 2020-12 entry point', () => {
  for (const name of Object.keys(PUBLIC_SCHEMA_DEFS)) {
    const ajv = new Ajv2020({ allErrors: true, strict: true, strictRequired: false });
    assert.doesNotThrow(
      () =>
        ajv.compile({
          $schema: JSON_SCHEMA_DIALECT,
          $defs: PUBLIC_SCHEMA_DEFS,
          $ref: `#/$defs/${name}`,
        }),
      name,
    );
  }
});

test('every tool accepts its minimal input and rejects unknown input fields', () => {
  for (const toolName of TOOL_NAMES) {
    assert.doesNotThrow(() => assertToolInput(toolName, validInputs[toolName]));
    assert.throws(
      () => assertToolInput(toolName, { ...validInputs[toolName], unknownField: true }),
      ProtocolValidationError,
      toolName,
    );
  }
});

test('every output schema accepts success and error envelopes and rejects extra fields', () => {
  for (const toolName of TOOL_NAMES) {
    assert.doesNotThrow(() =>
      assertToolOutput(toolName, { ok: true, data: validSuccessData[toolName] }),
    );
    assert.doesNotThrow(() => assertToolOutput(toolName, invalidArgumentEnvelope));
    assert.throws(
      () => assertToolOutput(toolName, { ok: true, data: validSuccessData[toolName], debug: true }),
      ProtocolValidationError,
      toolName,
    );
  }
});

test('normalization applies explicit defaults without mutating caller input', () => {
  const source = { resultStart: 7 };
  const normalizedWindow = normalizeToolInput('list_workspaces', source);
  assert.deepEqual(source, { resultStart: 7 });
  assert.deepEqual(normalizedWindow, { resultStart: 7, resultEnd: 26 });
  assert.ok(Object.isFrozen(normalizedWindow));

  assert.deepEqual(normalizeToolInput('list_workspaces', { resultEnd: 5 }), {
    resultStart: 1,
    resultEnd: 5,
  });
  assert.deepEqual(normalizeToolInput('get_capabilities', { workspaceId: 'workspace-1' }), {
    workspaceId: 'workspace-1',
    capabilities: [...CAPABILITY_NAMES],
    resultStart: 1,
    resultEnd: 20,
  });
  assert.deepEqual(normalizeToolInput('get_references', {
    workspaceId: 'workspace-1',
    file: 'src/widget.ts',
    line: 1,
    column: 1,
    timeoutMs: 90_000,
  }), {
    workspaceId: 'workspace-1',
    file: 'src/widget.ts',
    line: 1,
    column: 1,
    contextLines: 0,
    timeoutMs: 90_000,
    resultStart: 1,
    resultEnd: 20,
  });
  assert.throws(
    () => assertToolInput('get_references', {
      workspaceId: 'workspace-1',
      file: 'src/widget.ts',
      line: 1,
      column: 1,
      timeoutMs: 90_001,
    }),
    ProtocolValidationError,
  );
  assert.deepEqual(normalizeToolInput('rename_preview', {
    workspaceId: 'workspace-1',
    file: 'src/widget.ts',
    line: 1,
    column: 1,
    newName: 'nextWidget',
    includeGlobs: ['src/**'],
    timeoutMs: 90_000,
  }), {
    workspaceId: 'workspace-1',
    file: 'src/widget.ts',
    line: 1,
    column: 1,
    newName: 'nextWidget',
    includeGlobs: ['src/**'],
    timeoutMs: 90_000,
  });
  assert.throws(
    () => assertToolInput('rename_preview', {
      workspaceId: 'workspace-1',
      file: 'src/widget.ts',
      line: 1,
      column: 1,
      newName: 'nextWidget',
      includeGlobs: ['src/**'],
      timeoutMs: 90_001,
    }),
    ProtocolValidationError,
  );
  assert.deepEqual(normalizeToolInput('symbol_info', {
    workspaceId: 'workspace-1',
    file: 'src/widget.ts',
    line: 1,
    column: 1,
    excludeGlobs: ['Saved/**'],
  }), {
    workspaceId: 'workspace-1',
    file: 'src/widget.ts',
    line: 1,
    column: 1,
    excludeGlobs: ['Saved/**'],
    include: ['definition'],
    contextLines: 0,
    resultStart: 1,
    resultEnd: 20,
  });
  assert.throws(
    () => assertToolInput('get_references', {
      workspaceId: 'workspace-1',
      file: 'src/widget.ts',
      line: 1,
      column: 1,
      includeDeclaration: false,
    }),
    ProtocolValidationError,
  );
  assert.deepEqual(normalizeToolInput('get_diagnostics', { workspaceId: 'workspace-1' }), {
    workspaceId: 'workspace-1',
    scope: 'modifiedFiles',
    severities: ['error', 'warning', 'information', 'hint'],
    includeRelatedInformation: false,
    resultStart: 1,
    resultEnd: 20,
  });
  assert.deepEqual(normalizeToolInput('get_diagnostics', {
    workspaceId: 'workspace-1',
    files: ['src/widget.ts'],
  }), {
    workspaceId: 'workspace-1',
    files: ['src/widget.ts'],
    scope: 'files',
    severities: ['error', 'warning', 'information', 'hint'],
    includeRelatedInformation: false,
    resultStart: 1,
    resultEnd: 20,
  });
  assert.deepEqual(
    normalizeToolInput('execute_command', {
      workspaceId: 'workspace-1',
      target: { kind: 'command', commandId: 'example.safeCommand' },
    }),
    {
      workspaceId: 'workspace-1',
      target: { kind: 'command', commandId: 'example.safeCommand', arguments: [] },
      saveBeforeRun: 'none',
      timeoutMs: 120_000,
      maxOutputChars: 20_000,
      retainOutputLog: false,
    },
  );
});

test('cross-field validation rejects invalid windows, ranges, globs, and diagnostic scope', () => {
  const expectCode = (action: () => unknown, code: string): void => {
    assert.throws(action, (error: unknown) => {
      assert.ok(error instanceof ProtocolValidationError);
      assert.equal(error.code, code);
      return true;
    });
  };

  expectCode(
    () => normalizeToolInput('list_workspaces', { resultStart: 5, resultEnd: 4 }),
    'INVALID_RESULT_WINDOW',
  );
  expectCode(
    () => normalizeToolInput('list_workspaces', { resultStart: 1, resultEnd: 101 }),
    'INVALID_RESULT_WINDOW',
  );
  expectCode(
    () =>
      normalizeToolInput('rename_preview', {
        workspaceId: 'workspace-1',
        file: 'src/widget.ts',
        line: 1,
        column: 1,
        newName: 'RenamedWidget',
      }),
    'INVALID_ARGUMENT',
  );
  expectCode(
    () =>
      normalizeToolInput('rename_preview', {
        workspaceId: 'workspace-1',
        file: 'src/widget.ts',
        line: 1,
        column: 1,
        newName: 'RenamedWidget',
        includeGlobs: ['src/{a,b}.ts'],
      }),
    'INVALID_ARGUMENT',
  );
  expectCode(
    () =>
      normalizeToolInput('format_preview', {
        workspaceId: 'workspace-1',
        file: 'src/widget.ts',
        range: { startLine: 2, startColumn: 1, endLine: 1, endColumn: 1 },
      }),
    'INVALID_ARGUMENT',
  );
  expectCode(
    () =>
      normalizeToolInput('symbol_info', {
        workspaceId: 'workspace-1',
        file: 'src/widget.ts',
        line: 1,
        column: 1,
        excludeGlobs: ['Saved/{a,b}.ts'],
      }),
    'INVALID_ARGUMENT',
  );
  expectCode(
    () =>
      normalizeToolInput('get_diagnostics', {
        workspaceId: 'workspace-1',
        scope: 'files',
      }),
    'INVALID_ARGUMENT',
  );
  expectCode(
    () =>
      normalizeToolInput('workspace_symbols', {
        workspaceId: 'workspace-1',
        query: 'Widget',
        includeGlobs: ['src/{a,b}.ts'],
      }),
    'INVALID_ARGUMENT',
  );
  expectCode(
    () =>
      normalizeToolInput('workspace_symbols', {
        workspaceId: 'workspace-1',
        query: 'Widget',
        includeGlobs: ['src/[z-a].ts'],
      }),
    'INVALID_ARGUMENT',
  );
  expectCode(
    () =>
      normalizeToolInput('get_diagnostics', {
        workspaceId: 'workspace-1',
        scope: 'workspace',
        files: ['src/widget.ts'],
      }),
    'INVALID_ARGUMENT',
  );
});

test('rename safety errors have bounded, machine-readable details', () => {
  assert.doesNotThrow(() => assertToolOutput('rename_preview', {
    ok: false,
    error: {
      code: 'RENAME_SCOPE_VIOLATION',
      message: 'Rename escaped scope.',
      retryable: false,
      details: { files: ['Saved/copy.cpp'], totalFiles: 2 },
    },
  }));
  assert.doesNotThrow(() => assertToolOutput('rename_preview', {
    ok: false,
    error: {
      code: 'RENAME_IDENTITY_UNVERIFIED',
      message: 'Rename identity is ambiguous.',
      retryable: false,
      details: {
        reason: 'mismatchedSymbol',
        checkedEdits: 2,
        totalEdits: 5,
        files: ['src/other.cpp'],
      },
    },
  }));
  assert.doesNotThrow(() => assertToolOutput('rename_preview', {
    ok: false,
    error: {
      code: 'RENAME_IDENTITY_UNVERIFIED',
      message: 'Rename identity verification timed out.',
      retryable: false,
      details: {
        reason: 'providerTimedOut',
        checkedEdits: 1,
        totalEdits: 5,
        files: ['src/slow.cpp'],
      },
    },
  }));
  assert.doesNotThrow(() => assertToolOutput('rename_preview', {
    ok: false,
    error: {
      code: 'RENAME_NO_EDITS',
      message: 'Rename produced no edits.',
      retryable: false,
    },
  }));
  assert.doesNotThrow(() => assertToolOutput('rename_preview', {
    ok: false,
    error: {
      code: 'PREVIEW_TOO_LARGE',
      message: 'Rename is too large.',
      retryable: false,
      details: {
        changedFiles: 51,
        edits: 600,
        textCharacters: 80_000,
        serializedBytes: 100_000,
        limits: {
          changedFiles: 50,
          edits: 100,
          textCharacters: 50_000,
          serializedBytes: 65_536,
        },
      },
    },
  }));
});

test('preview and action-set handles are present exactly when results are non-empty', () => {
  const range = { startLine: 1, startColumn: 1, endLine: 1, endColumn: 1 };
  const change = {
    kind: 'text',
    file: 'src/widget.ts',
    edits: [{ range, oldText: '', newText: 'x' }],
  };

  assert.throws(
    () => assertToolOutput('rename_preview', { ok: true, data: { changes: [change] } }),
    ProtocolValidationError,
  );
  assert.throws(
    () =>
      assertToolOutput('rename_preview', {
        ok: true,
        data: { previewId: 'pv_unused', changes: [] },
      }),
    ProtocolValidationError,
  );
  assert.doesNotThrow(() =>
    assertToolOutput('rename_preview', {
      ok: true,
      data: { previewId: 'pv_used', changes: [change] },
    }),
  );

  assert.throws(
    () =>
      assertToolOutput('code_actions', {
        ok: true,
        data: { results: [{ actionId: 'ac_1', title: 'Fix' }], available: 1 },
      }),
    ProtocolValidationError,
  );
  assert.throws(
    () =>
      assertToolOutput('code_actions', {
        ok: true,
        data: { actionSetId: 'as_unused', results: [], available: 0 },
      }),
    ProtocolValidationError,
  );
});

test('error details form a closed discriminator and retryability union', () => {
  const accepts = (error: unknown): void =>
    assert.doesNotThrow(() => assertToolOutput('rename_apply', { ok: false, error }));
  const rejects = (error: unknown): void =>
    assert.throws(
      () => assertToolOutput('rename_apply', { ok: false, error }),
      ProtocolValidationError,
    );

  accepts({
    code: 'WORKSPACE_DISCONNECTED',
    message: 'Disconnected before dispatch.',
    retryable: true,
    details: { phase: 'preflight', outcome: 'notStarted' },
  });
  accepts({
    code: 'WORKSPACE_DISCONNECTED',
    message: 'Disconnected after dispatch.',
    retryable: false,
    details: { phase: 'apply', outcome: 'unknown' },
  });
  rejects({
    code: 'WORKSPACE_DISCONNECTED',
    message: 'Unknown outcome cannot be retried.',
    retryable: true,
    details: { phase: 'apply', outcome: 'unknown' },
  });
  rejects({
    code: 'WORKSPACE_DISCONNECTED',
    message: 'Preflight cannot have an unknown outcome.',
    retryable: false,
    details: { phase: 'preflight', outcome: 'unknown' },
  });
  rejects({
    code: 'COMMAND_TIMEOUT',
    message: 'A command timeout cannot claim task termination.',
    retryable: false,
    details: { targetKind: 'command', timeoutMs: 10_000, outcome: 'terminated' },
  });
  rejects({
    code: 'DOCUMENT_CHANGED',
    message: 'Document changed.',
    retryable: false,
  });
  rejects({
    code: 'EDIT_CONFLICT',
    message: 'Conflict.',
    retryable: false,
    details: { reason: 'overlappingEdits', absolutePath: 'C:/secret.ts' },
  });
  accepts({
    code: 'COMMAND_FAILED',
    message: 'Task exited non-zero.',
    retryable: false,
    details: { targetKind: 'task', reason: 'nonZeroExit', outcome: 'failed', exitCode: 2 },
  });
  accepts({
    code: 'COMMAND_FAILED',
    message: 'Task exited non-zero with a retained output log.',
    retryable: false,
    details: {
      targetKind: 'task',
      reason: 'nonZeroExit',
      outcome: 'failed',
      exitCode: 2,
      outputLog: {
        path: '.vscode-lsp-mcp/task-logs/failed.log',
        lineCount: 4,
        byteCount: 128,
        encoding: 'utf-8',
        truncated: false,
      },
    },
  });
  rejects({
    code: 'COMMAND_FAILED',
    message: 'Zero is not a failure exit.',
    retryable: false,
    details: { targetKind: 'task', reason: 'nonZeroExit', outcome: 'failed', exitCode: 0 },
  });
  rejects({
    code: 'COMMAND_FAILED',
    message: 'Exit code is not valid for rejected.',
    retryable: false,
    details: { targetKind: 'command', reason: 'rejected', outcome: 'failed', exitCode: 2 },
  });
  rejects({
    code: 'COMMAND_FAILED',
    message: 'Command failures cannot claim task output.',
    retryable: false,
    details: {
      targetKind: 'command',
      reason: 'rejected',
      outcome: 'failed',
      outputLog: {
        path: '.vscode-lsp-mcp/task-logs/failed.log',
        lineCount: 1,
        byteCount: 4,
        encoding: 'utf-8',
        truncated: false,
      },
    },
  });
  rejects({
    code: 'APPLY_FAILED',
    message: 'Apply failed.',
    retryable: true,
    details: { stage: 'apply', outcome: 'notApplied' },
  });
  rejects({
    code: 'PREVIEW_NOT_FOUND',
    message: 'Missing.',
    retryable: false,
    details: { reason: 'hidden' },
  });
});

test('public output contract has no resource-change or internal snapshot branches', () => {
  const serialized = JSON.stringify(TOOL_DEFINITIONS.map((definition) => definition.outputSchema));
  for (const forbidden of [
    'CreateChange',
    'RenameChange',
    'DeleteChange',
    'WorkspaceChange',
    'documentVersion',
    'memoryContentSha256',
    'internalUri',
    'instanceId',
    'workspaceGeneration',
    'lexicalAbsolutePath',
    'canonicalAbsolutePath',
    'canonicalComparisonKey',
  ]) {
    assert.equal(serialized.includes(forbidden), false, forbidden);
  }
});

test('optional empty or false output fields are rejected while required false remains valid', () => {
  assert.doesNotThrow(() => assertToolOutput('execute_command', {
    ok: true,
    data: {
      outputLog: {
        path: '.vscode-lsp-mcp/task-logs/success.log',
        lineCount: 1,
        byteCount: 6,
        encoding: 'utf-8',
        truncated: false,
      },
    },
  }));
  assert.throws(
    () =>
      assertToolOutput('list_workspaces', {
        ok: true,
        data: { results: [], available: 0, warnings: [] },
      }),
    ProtocolValidationError,
  );
  assert.throws(
    () =>
      assertToolOutput('execute_command', {
        ok: true,
        data: { output: 'done', outputTruncated: false },
      }),
    ProtocolValidationError,
  );
  assert.doesNotThrow(() => assertToolOutput('list_workspaces', invalidArgumentEnvelope));
});

test('all minimal samples stay aligned with the frozen tool-name map', () => {
  assert.deepEqual(Object.keys(validInputs), [...TOOL_NAMES]);
  assert.deepEqual(Object.keys(validSuccessData), [...TOOL_NAMES]);

  for (const toolName of Object.keys(validInputs) as ToolName[]) {
    assert.ok(TOOL_NAMES.includes(toolName));
  }
});
