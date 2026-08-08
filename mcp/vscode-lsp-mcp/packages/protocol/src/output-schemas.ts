import type { ToolName } from './dto.js';
import {
  cloneSchema,
  JSON_SCHEMA_DIALECT,
  PUBLIC_SCHEMA_DEFS,
  type JsonSchema,
} from './schema-definitions.js';

export const OUTPUT_SUCCESS_DEFINITION_NAMES: Readonly<Record<ToolName, string>> = {
  list_workspaces: 'WorkspaceCollection',
  health_check: 'HealthResultCollection',
  get_capabilities: 'CapabilityCollection',
  workspace_symbols: 'SymbolHitCollection',
  document_symbols: 'DocumentSymbolCollection',
  symbol_info: 'SymbolInfoResultCollection',
  get_references: 'ReferenceHitCollection',
  get_call_hierarchy: 'CallHierarchyEntryCollection',
  get_type_hierarchy: 'TypeHierarchyEntryCollection',
  get_diagnostics: 'DiagnosticCollection',
  rename_preview: 'Preview',
  rename_apply: 'ApplyResult',
  code_actions: 'CodeActionSet',
  code_action_preview: 'Preview',
  code_action_apply: 'ApplyResult',
  format_preview: 'Preview',
  format_apply: 'ApplyResult',
  execute_command: 'CommandResult',
};

const createOutputSchema = (successDefinition: string): JsonSchema => ({
  $schema: JSON_SCHEMA_DIALECT,
  type: 'object',
  oneOf: [
    {
      type: 'object',
      properties: {
        ok: { const: true },
        data: { $ref: '#/$defs/ToolSuccessData' },
      },
      required: ['ok', 'data'],
      additionalProperties: false,
    },
    {
      type: 'object',
      properties: {
        ok: { const: false },
        error: { $ref: '#/$defs/ToolError' },
      },
      required: ['ok', 'error'],
      additionalProperties: false,
    },
  ],
  $defs: {
    ...cloneSchema(PUBLIC_SCHEMA_DEFS),
    ToolSuccessData: { $ref: `#/$defs/${successDefinition}` },
  },
});

export const OUTPUT_SCHEMAS: Readonly<Record<ToolName, JsonSchema>> = Object.fromEntries(
  Object.entries(OUTPUT_SUCCESS_DEFINITION_NAMES).map(([name, successDefinition]) => [
    name,
    createOutputSchema(successDefinition),
  ]),
) as Record<ToolName, JsonSchema>;

