import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  type CallToolResult,
  type Tool,
} from '@modelcontextprotocol/sdk/types.js';
import {
  ProtocolValidationError,
  TOOL_DEFINITIONS,
  TOOL_NAMES,
  encodeToolResponse,
  normalizeToolInput,
  type ToolEnvelope,
  type ToolName,
  type ToolOutputDataMap,
  type ToolResponseMap,
} from '@simplechat/vscode-lsp-mcp-protocol';

export interface FoundationToolService {
  documentSymbols(input: unknown, signal?: AbortSignal): Promise<ToolResponseMap['document_symbols']>;
  getCapabilities(input: unknown, signal?: AbortSignal): Promise<ToolResponseMap['get_capabilities']>;
  getCallHierarchy(input: unknown, signal?: AbortSignal): Promise<ToolResponseMap['get_call_hierarchy']>;
  getDiagnostics(input: unknown, signal?: AbortSignal): Promise<ToolResponseMap['get_diagnostics']>;
  getReferences(input: unknown, signal?: AbortSignal): Promise<ToolResponseMap['get_references']>;
  verifySymbolCandidates(
    input: unknown,
    signal?: AbortSignal,
  ): Promise<ToolResponseMap['verify_symbol_candidates']>;
  getTypeHierarchy(input: unknown, signal?: AbortSignal): Promise<ToolResponseMap['get_type_hierarchy']>;
  healthCheck(input: unknown): Promise<ToolResponseMap['health_check']>;
  listWorkspaces(input: unknown): Promise<ToolResponseMap['list_workspaces']>;
  symbolInfo(input: unknown, signal?: AbortSignal): Promise<ToolResponseMap['symbol_info']>;
  workspaceSymbols(input: unknown, signal?: AbortSignal): Promise<ToolResponseMap['workspace_symbols']>;
}

export interface MutationToolService {
  codeActionApply(input: unknown, signal?: AbortSignal): Promise<ToolResponseMap['code_action_apply']>;
  codeActionPreview(
    input: unknown,
    signal?: AbortSignal,
  ): Promise<ToolResponseMap['code_action_preview']>;
  codeActions(input: unknown, signal?: AbortSignal): Promise<ToolResponseMap['code_actions']>;
  formatApply(input: unknown, signal?: AbortSignal): Promise<ToolResponseMap['format_apply']>;
  formatPreview(input: unknown, signal?: AbortSignal): Promise<ToolResponseMap['format_preview']>;
  renameApply(input: unknown, signal?: AbortSignal): Promise<ToolResponseMap['rename_apply']>;
  renamePreview(input: unknown, signal?: AbortSignal): Promise<ToolResponseMap['rename_preview']>;
}

export interface CommandToolService {
  executeCommand(input: unknown, signal?: AbortSignal): Promise<ToolResponseMap['execute_command']>;
}

const isToolName = (value: string): value is ToolName =>
  (TOOL_NAMES as readonly string[]).includes(value);

const errorEnvelope = <K extends ToolName>(
  code: 'INTERNAL_ERROR' | 'INVALID_ARGUMENT' | 'INVALID_RESULT_WINDOW' | 'PROVIDER_UNAVAILABLE',
  message: string,
  retryable: boolean,
): ToolEnvelope<ToolOutputDataMap[K]> => ({
  ok: false,
  error: { code, message, retryable } as Extract<
    ToolResponseMap[K],
    { readonly ok: false }
  >['error'],
});

const encodeDynamic = (name: ToolName, response: ToolResponseMap[ToolName]): CallToolResult => {
  const encoded = encodeToolResponse(name, response);
  return {
    content: [...encoded.content],
    ...(!response.ok ? { isError: true } : {}),
  };
};

const callTool = async (
  service: FoundationToolService,
  mutationService: MutationToolService | undefined,
  commandService: CommandToolService | undefined,
  name: ToolName,
  input: unknown,
  signal?: AbortSignal,
): Promise<CallToolResult> => {
  try {
    const normalizedInput = normalizeToolInput(name, input);
    if (name === 'list_workspaces') {
      return encodeDynamic(name, await service.listWorkspaces(normalizedInput));
    }
    if (name === 'health_check') {
      return encodeDynamic(name, await service.healthCheck(normalizedInput));
    }
    if (name === 'get_capabilities') {
      return encodeDynamic(name, await service.getCapabilities(normalizedInput, signal));
    }
    if (name === 'workspace_symbols') {
      return encodeDynamic(name, await service.workspaceSymbols(normalizedInput, signal));
    }
    if (name === 'document_symbols') {
      return encodeDynamic(name, await service.documentSymbols(normalizedInput, signal));
    }
    if (name === 'symbol_info') {
      return encodeDynamic(name, await service.symbolInfo(normalizedInput, signal));
    }
    if (name === 'get_references') {
      return encodeDynamic(name, await service.getReferences(normalizedInput, signal));
    }
    if (name === 'verify_symbol_candidates') {
      return encodeDynamic(name, await service.verifySymbolCandidates(normalizedInput, signal));
    }
    if (name === 'get_call_hierarchy') {
      return encodeDynamic(name, await service.getCallHierarchy(normalizedInput, signal));
    }
    if (name === 'get_type_hierarchy') {
      return encodeDynamic(name, await service.getTypeHierarchy(normalizedInput, signal));
    }
    if (name === 'get_diagnostics') {
      return encodeDynamic(name, await service.getDiagnostics(normalizedInput, signal));
    }
    if (name === 'rename_preview' && mutationService !== undefined) {
      return encodeDynamic(name, await mutationService.renamePreview(normalizedInput, signal));
    }
    if (name === 'rename_apply' && mutationService !== undefined) {
      return encodeDynamic(name, await mutationService.renameApply(normalizedInput, signal));
    }
    if (name === 'code_actions' && mutationService !== undefined) {
      return encodeDynamic(name, await mutationService.codeActions(normalizedInput, signal));
    }
    if (name === 'code_action_preview' && mutationService !== undefined) {
      return encodeDynamic(name, await mutationService.codeActionPreview(normalizedInput, signal));
    }
    if (name === 'code_action_apply' && mutationService !== undefined) {
      return encodeDynamic(name, await mutationService.codeActionApply(normalizedInput, signal));
    }
    if (name === 'format_preview' && mutationService !== undefined) {
      return encodeDynamic(name, await mutationService.formatPreview(normalizedInput, signal));
    }
    if (name === 'format_apply' && mutationService !== undefined) {
      return encodeDynamic(name, await mutationService.formatApply(normalizedInput, signal));
    }
    if (name === 'execute_command' && commandService !== undefined) {
      return encodeDynamic(name, await commandService.executeCommand(normalizedInput, signal));
    }
    return encodeDynamic(name, errorEnvelope(
      'PROVIDER_UNAVAILABLE',
      'This tool is not implemented by the current delivery phase.',
      false,
    ) as ToolResponseMap[ToolName]);
  } catch (error) {
    if (error instanceof ProtocolValidationError) {
      return encodeDynamic(name, errorEnvelope(
        error.code,
        `Tool input validation failed: ${error.issues.join('; ')}.`,
        false,
      ) as ToolResponseMap[ToolName]);
    }
    return encodeDynamic(name, errorEnvelope(
      'INTERNAL_ERROR',
      'The MCP server could not complete the request.',
      true,
    ) as ToolResponseMap[ToolName]);
  }
};

const publicTool = (definition: (typeof TOOL_DEFINITIONS)[number]): Tool => ({
  name: definition.name,
  description: definition.description,
  inputSchema: definition.inputSchema as Tool['inputSchema'],
  annotations: definition.annotations,
  execution: definition.execution,
});

export const createFoundationMcpServer = (
  service: FoundationToolService,
  mutationService?: MutationToolService,
  commandService?: CommandToolService,
): Server => {
  const server = new Server(
    { name: 'vscode-lsp-mcp', version: '0.0.0' },
    { capabilities: { tools: {} } },
  );
  server.setRequestHandler(ListToolsRequestSchema, () => ({
    tools: TOOL_DEFINITIONS.map(publicTool),
  }));
  server.setRequestHandler(CallToolRequestSchema, async (request, extra) => {
    const name = request.params.name;
    if (!isToolName(name)) {
      return {
        content: [{ type: 'text', text: 'Unknown MCP tool.' }],
        isError: true,
      };
    }
    return callTool(
      service,
      mutationService,
      commandService,
      name,
      request.params.arguments ?? {},
      extra.signal,
    );
  });
  return server;
};
