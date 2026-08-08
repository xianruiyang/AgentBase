import assert from 'node:assert/strict';
import test from 'node:test';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import {
  TOOL_DEFINITIONS,
  TOOL_NAMES,
  assertToolOutput,
  decodeYamlText,
  type ToolName,
  type ToolResponseMap,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  createFoundationMcpServer,
  type CommandToolService,
  type FoundationToolService,
  type MutationToolService,
} from './mcp-server.js';

const service: FoundationToolService = {
  documentSymbols: (): Promise<ToolResponseMap['document_symbols']> => Promise.resolve({
    ok: true,
    data: {
      results: [{ kind: 'class', path: ['Widget'], line: 1, column: 1 }],
      available: 1,
    },
  }),
  listWorkspaces: (): Promise<ToolResponseMap['list_workspaces']> => Promise.resolve({
    ok: true,
    data: {
      results: [{ workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA', name: 'Fixture', roots: ['app'] }],
      available: 1,
    },
  }),
  healthCheck: (): Promise<ToolResponseMap['health_check']> => Promise.resolve({
    ok: true,
    data: { results: [{ target: 'server', status: 'healthy' }], available: 1 },
  }),
  getDiagnostics: (): Promise<ToolResponseMap['get_diagnostics']> => Promise.resolve({
    ok: true,
    data: {
      results: [{
        file: 'src/widget.ts',
        range: { startLine: 1, startColumn: 1, endLine: 1, endColumn: 7 },
        severity: 'error',
        message: 'Broken widget.',
      }],
      available: 1,
    },
  }),
  getCapabilities: (): Promise<ToolResponseMap['get_capabilities']> => Promise.resolve({
    ok: true,
    data: {
      results: [
        { name: 'documentSymbols', status: 'available' },
        { name: 'definition', status: 'unknown', reason: 'probe_returned_no_evidence' },
      ],
      available: 2,
    },
  }),
  getCallHierarchy: (): Promise<ToolResponseMap['get_call_hierarchy']> => Promise.resolve({
    ok: true,
    data: {
      results: [{
        relation: 'root', depth: 0,
        symbol: { name: 'middleCall', kind: 'function', file: 'src/hierarchy.ts', line: 4, column: 17 },
      }],
      available: 1,
    },
  }),
  getReferences: (): Promise<ToolResponseMap['get_references']> => Promise.resolve({
    ok: true,
    data: {
      results: [{ file: 'src/widget.ts', line: 2, column: 7 }],
      available: 1,
    },
  }),
  getTypeHierarchy: (): Promise<ToolResponseMap['get_type_hierarchy']> => Promise.resolve({
    ok: true,
    data: {
      results: [{
        relation: 'root', depth: 0,
        symbol: { name: 'MiddleType', kind: 'class', file: 'src/hierarchy.ts', line: 11, column: 14 },
      }],
      available: 1,
    },
  }),
  symbolInfo: (): Promise<ToolResponseMap['symbol_info']> => Promise.resolve({
    ok: true,
    data: {
      results: [{ type: 'definition', file: 'src/widget.ts', line: 1, column: 1 }],
      available: 1,
    },
  }),
  workspaceSymbols: (): Promise<ToolResponseMap['workspace_symbols']> => Promise.resolve({
    ok: true,
    data: {
      results: [{ name: 'Widget', kind: 'class', file: 'src/widget.ts', line: 1, column: 1 }],
      available: 1,
    },
  }),
};

const responseFromYaml = <K extends ToolName>(
  name: K,
  result: unknown,
): ToolResponseMap[K] => {
  assert.ok(result !== null && typeof result === 'object');
  const raw = result as { readonly content?: unknown; readonly structuredContent?: unknown };
  assert.equal(raw.structuredContent, undefined);
  assert.ok(Array.isArray(raw.content));
  assert.equal(raw.content.length, 1);
  const content = raw.content[0] as { readonly type?: unknown; readonly text?: unknown } | undefined;
  assert.equal(content?.type, 'text');
  assert.equal(typeof content?.text, 'string');
  if (typeof content?.text !== 'string') throw new Error(`${name} did not return YAML TextContent.`);
  const decoded = decodeYamlText(content.text);
  assertToolOutput(name, decoded);
  return decoded as unknown as ToolResponseMap[K];
};

test('official MCP SDK completes initialize, listTools, and foundation callTool', async () => {
  const server = createFoundationMcpServer(service);
  const client = new Client({ name: 'foundation-test', version: '1.0.0' });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  try {
    await server.connect(serverTransport);
    await client.connect(clientTransport);
    const listed = await client.listTools();
    assert.deepEqual(listed.tools.map((tool) => tool.name), [...TOOL_NAMES]);
    assert.deepEqual(listed.tools, TOOL_DEFINITIONS.map((definition) => ({
      name: definition.name,
      description: definition.description,
      inputSchema: definition.inputSchema,
      annotations: definition.annotations,
      execution: definition.execution,
    })));

    const called = await client.callTool({ name: 'list_workspaces', arguments: {} });
    assert.equal(called.isError, undefined);
    assert.deepEqual(responseFromYaml('list_workspaces', called), await service.listWorkspaces({}));

    const workspaceSymbols = await client.callTool({
      name: 'workspace_symbols',
      arguments: { workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA', query: 'Widget' },
    });
    assert.equal(workspaceSymbols.isError, undefined);
    responseFromYaml('workspace_symbols', workspaceSymbols);

    const documentSymbols = await client.callTool({
      name: 'document_symbols',
      arguments: { workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA', file: 'src/widget.ts' },
    });
    assert.equal(documentSymbols.isError, undefined);
    responseFromYaml('document_symbols', documentSymbols);

    const symbolInfo = await client.callTool({
      name: 'symbol_info',
      arguments: {
        workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA',
        file: 'src/widget.ts',
        line: 1,
        column: 1,
      },
    });
    assert.equal(symbolInfo.isError, undefined);
    responseFromYaml('symbol_info', symbolInfo);

    const references = await client.callTool({
      name: 'get_references',
      arguments: {
        workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA',
        file: 'src/widget.ts',
        line: 1,
        column: 1,
      },
    });
    assert.equal(references.isError, undefined);
    responseFromYaml('get_references', references);

    const diagnostics = await client.callTool({
      name: 'get_diagnostics',
      arguments: { workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA' },
    });
    assert.equal(diagnostics.isError, undefined);
    responseFromYaml('get_diagnostics', diagnostics);

    const capabilities = await client.callTool({
      name: 'get_capabilities',
      arguments: { workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA' },
    });
    assert.equal(capabilities.isError, undefined);
    responseFromYaml('get_capabilities', capabilities);

    const callHierarchy = await client.callTool({
      name: 'get_call_hierarchy',
      arguments: {
        workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA',
        file: 'src/hierarchy.ts',
        line: 4,
        column: 17,
      },
    });
    assert.equal(callHierarchy.isError, undefined);
    responseFromYaml('get_call_hierarchy', callHierarchy);

    const typeHierarchy = await client.callTool({
      name: 'get_type_hierarchy',
      arguments: {
        workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA',
        file: 'src/hierarchy.ts',
        line: 11,
        column: 14,
      },
    });
    assert.equal(typeHierarchy.isError, undefined);
    responseFromYaml('get_type_hierarchy', typeHierarchy);

    const invalid = await client.callTool({ name: 'list_workspaces', arguments: { extra: true } });
    assert.equal(invalid.isError, true);
    const invalidResponse = responseFromYaml('list_workspaces', invalid);
    assert.equal(invalidResponse.ok, false);
    if (invalidResponse.ok) throw new Error('Invalid input unexpectedly succeeded.');
    assert.match(invalidResponse.error.message, /additional properties/u);
  } finally {
    await client.close();
    await server.close();
  }
});

test('official MCP SDK dispatches execute_command with normalized defaults', async () => {
  let captured: unknown;
  const commandService: CommandToolService = {
    executeCommand: (input) => {
      captured = input;
      return Promise.resolve({ ok: true, data: { output: 'complete' } });
    },
  };
  const server = createFoundationMcpServer(service, undefined, commandService);
  const client = new Client({ name: 'command-test', version: '1.0.0' });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  try {
    await server.connect(serverTransport);
    await client.connect(clientTransport);
    const called = await client.callTool({
      name: 'execute_command',
      arguments: {
        workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA',
        target: { kind: 'task', taskName: 'build', taskRoot: 'root' },
      },
    });
    assert.equal(called.isError, undefined);
    assert.deepEqual(responseFromYaml('execute_command', called), {
      ok: true,
      data: { output: 'complete' },
    });
    assert.deepEqual(captured, {
      workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA',
      target: { kind: 'task', taskName: 'build', taskRoot: 'root' },
      saveBeforeRun: 'none',
      timeoutMs: 120_000,
      maxOutputChars: 20_000,
      retainOutputLog: false,
    });
  } finally {
    await client.close();
    await server.close();
  }
});

test('MCP request cancellation reaches the semantic tool service', async () => {
  let markStarted!: () => void;
  let markCancelled!: () => void;
  const started = new Promise<void>((resolve) => { markStarted = resolve; });
  const cancelled = new Promise<void>((resolve) => { markCancelled = resolve; });
  const cancellationService: FoundationToolService = {
    ...service,
    getTypeHierarchy: async (_input, signal) => {
      markStarted();
      await new Promise<void>((resolve) => {
        if (signal?.aborted === true) {
          markCancelled();
          resolve();
          return;
        }
        signal?.addEventListener('abort', () => {
          markCancelled();
          resolve();
        }, { once: true });
      });
      return {
        ok: false,
        error: {
          code: 'PROVIDER_UNAVAILABLE',
          message: 'Cancelled fixture request.',
          retryable: false,
        },
      };
    },
  };
  const server = createFoundationMcpServer(cancellationService);
  const client = new Client({ name: 'cancellation-test', version: '1.0.0' });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  try {
    await server.connect(serverTransport);
    await client.connect(clientTransport);
    const controller = new AbortController();
    const pending = client.callTool({
      name: 'get_type_hierarchy',
      arguments: {
        workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA',
        file: 'src/hierarchy.ts',
        line: 1,
        column: 1,
      },
    }, undefined, { signal: controller.signal, timeout: 10_000 });
    await started;
    controller.abort();
    await assert.rejects(pending);
    await cancelled;
  } finally {
    await client.close();
    await server.close();
  }
});

test('MCP dispatches rename, Code Action, and format mutation tools through the explicit service', async () => {
  const calls: string[] = [];
  const mutationService: MutationToolService = {
    renamePreview: (input): Promise<ToolResponseMap['rename_preview']> => {
      calls.push(`preview:${JSON.stringify(input)}`);
      return Promise.resolve({
        ok: true,
        data: {
          previewId: 'pv_AAAAAAAAAAAAAAAAAAAAAA',
          changes: [{
            kind: 'text',
            file: 'src/a.ts',
            edits: [{
              range: { startLine: 1, startColumn: 1, endLine: 1, endColumn: 4 },
              oldText: 'old',
              newText: 'next',
            }],
          }],
        },
      });
    },
    renameApply: (input): Promise<ToolResponseMap['rename_apply']> => {
      calls.push(`apply:${JSON.stringify(input)}`);
      return Promise.resolve({ ok: true, data: { changedFiles: ['src/a.ts'] } });
    },
    codeActions: (input): Promise<ToolResponseMap['code_actions']> => {
      calls.push(`actions:${JSON.stringify(input)}`);
      return Promise.resolve({
        ok: true,
        data: {
          actionSetId: 'as_AAAAAAAAAAAAAAAAAAAAAA',
          results: [{
            actionId: 'ac_AAAAAAAAAAAAAAAAAAAAAA',
            title: 'Add missing import',
            kind: 'quickfix',
          }],
          available: 1,
        },
      });
    },
    codeActionPreview: (input): Promise<ToolResponseMap['code_action_preview']> => {
      calls.push(`action-preview:${JSON.stringify(input)}`);
      return Promise.resolve({
        ok: true,
        data: {
          previewId: 'pv_BBBBBBBBBBBBBBBBBBBBBB',
          changes: [{
            kind: 'text',
            file: 'src/a.ts',
            edits: [{
              range: { startLine: 1, startColumn: 1, endLine: 1, endColumn: 1 },
              oldText: '',
              newText: "import { value } from './value.js';\n",
            }],
          }],
        },
      });
    },
    codeActionApply: (input): Promise<ToolResponseMap['code_action_apply']> => {
      calls.push(`action-apply:${JSON.stringify(input)}`);
      return Promise.resolve({ ok: true, data: { changedFiles: ['src/a.ts'] } });
    },
    formatPreview: (input): Promise<ToolResponseMap['format_preview']> => {
      calls.push(`format-preview:${JSON.stringify(input)}`);
      return Promise.resolve({
        ok: true,
        data: {
          previewId: 'pv_CCCCCCCCCCCCCCCCCCCCCC',
          changes: [{
            kind: 'text',
            file: 'src/a.ts',
            edits: [{
              range: { startLine: 1, startColumn: 1, endLine: 1, endColumn: 4 },
              oldText: 'old',
              newText: 'old',
            }],
          }],
        },
      });
    },
    formatApply: (input): Promise<ToolResponseMap['format_apply']> => {
      calls.push(`format-apply:${JSON.stringify(input)}`);
      return Promise.resolve({ ok: true, data: { changedFiles: ['src/a.ts'] } });
    },
  };
  const server = createFoundationMcpServer(service, mutationService);
  const client = new Client({ name: 'mutation-test', version: '1.0.0' });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  try {
    await server.connect(serverTransport);
    await client.connect(clientTransport);
    const preview = await client.callTool({
      name: 'rename_preview',
      arguments: {
        workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA',
        file: 'src/a.ts',
        line: 1,
        column: 2,
        newName: 'next',
        includeGlobs: ['src/**'],
      },
    });
    assert.equal(preview.isError, undefined);
    responseFromYaml('rename_preview', preview);
    const applied = await client.callTool({
      name: 'rename_apply',
      arguments: { previewId: 'pv_AAAAAAAAAAAAAAAAAAAAAA' },
    });
    assert.equal(applied.isError, undefined);
    responseFromYaml('rename_apply', applied);

    const actions = await client.callTool({
      name: 'code_actions',
      arguments: {
        workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA',
        file: 'src/a.ts',
        range: { startLine: 1, startColumn: 1, endLine: 1, endColumn: 4 },
        resultStart: 1,
        resultEnd: 10,
      },
    });
    assert.equal(actions.isError, undefined);
    responseFromYaml('code_actions', actions);
    const actionPreview = await client.callTool({
      name: 'code_action_preview',
      arguments: {
        actionSetId: 'as_AAAAAAAAAAAAAAAAAAAAAA',
        actionId: 'ac_AAAAAAAAAAAAAAAAAAAAAA',
      },
    });
    assert.equal(actionPreview.isError, undefined);
    responseFromYaml('code_action_preview', actionPreview);
    const actionApplied = await client.callTool({
      name: 'code_action_apply',
      arguments: { previewId: 'pv_BBBBBBBBBBBBBBBBBBBBBB' },
    });
    assert.equal(actionApplied.isError, undefined);
    responseFromYaml('code_action_apply', actionApplied);

    const formatPreview = await client.callTool({
      name: 'format_preview',
      arguments: {
        workspaceId: 'ws_AAAAAAAAAAAAAAAAAAAAAA',
        file: 'src/a.ts',
        range: { startLine: 1, startColumn: 1, endLine: 1, endColumn: 4 },
        options: { tabSize: 2 },
      },
    });
    assert.equal(formatPreview.isError, undefined);
    responseFromYaml('format_preview', formatPreview);
    const formatApplied = await client.callTool({
      name: 'format_apply',
      arguments: { previewId: 'pv_CCCCCCCCCCCCCCCCCCCCCC' },
    });
    assert.equal(formatApplied.isError, undefined);
    responseFromYaml('format_apply', formatApplied);
    assert.equal(calls.length, 7);

    const invalid = await client.callTool({
      name: 'rename_apply',
      arguments: { previewId: 'pv_AAAAAAAAAAAAAAAAAAAAAA', workspaceId: 'injected' },
    });
    assert.equal(invalid.isError, true);
    assert.equal(calls.length, 7);
  } finally {
    await client.close();
    await server.close();
  }
});
