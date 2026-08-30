import {
  TOOL_NAMES,
  type ToolAnnotations,
  type ToolExecutionPolicy,
  type ToolName,
} from './dto.js';
import { INPUT_SCHEMAS } from './input-schemas.js';
import { OUTPUT_SCHEMAS } from './output-schemas.js';
import type { JsonSchema } from './schema-definitions.js';

export interface ToolDefinition {
  readonly name: ToolName;
  readonly description: string;
  readonly annotations: ToolAnnotations;
  readonly execution: ToolExecutionPolicy;
  readonly inputSchema: JsonSchema;
  readonly outputSchema: JsonSchema;
}

interface ToolMetadata {
  readonly name: ToolName;
  readonly description: string;
  readonly readOnly: boolean;
  readonly destructive: boolean;
  readonly idempotent: boolean;
  readonly openWorld: boolean;
}

const TOOL_METADATA: readonly ToolMetadata[] = [
  {
    name: 'list_workspaces',
    description: 'Resolve an unknown workspace and root aliases.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'health_check',
    description: 'Diagnose bridge or document activation after uncertainty or failure.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'get_capabilities',
    description: 'Probe only capabilities that change the next action.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'workspace_symbols',
    description: 'After scoped text/AST cannot locate a symbol, return bounded semantic candidates.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'document_symbols',
    description: 'Only when source/AST cannot supply the required outline, return bounded Provider document symbols; do not use it for an ordinary C/C++ function list.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'symbol_info',
    description: 'At a known position, request only semantics unresolved by source/AST.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'get_references',
    description: 'At a known symbol, return complete semantic references when text matches are insufficient.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'verify_symbol_candidates',
    description: 'Verify bounded text/AST candidates against one target identity.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'get_call_hierarchy',
    description: 'Return bounded overload-aware call relations only when source/AST is insufficient; cold C/C++ requires a current compile_commands entry.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'get_type_hierarchy',
    description: 'Return bounded semantic inheritance relations only when the active language Provider supports them; use source AST for cpptools C/C++.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'get_diagnostics',
    description: 'Read diagnostics from the smallest needed scope.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'rename_preview',
    description: 'Preview a complete semantic rename within an explicit path scope.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'rename_apply',
    description: 'Apply one unexpired rename preview after change validation.',
    readOnly: false,
    destructive: true,
    idempotent: false,
    openWorld: false,
  },
  {
    name: 'code_actions',
    description: 'For one known range, list bounded code actions only when provider assistance is needed.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'code_action_preview',
    description: 'Resolve one code action into an edit preview without applying it.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'code_action_apply',
    description: 'Apply one unexpired code-action preview after change validation.',
    readOnly: false,
    destructive: true,
    idempotent: false,
    openWorld: false,
  },
  {
    name: 'format_preview',
    description: 'Preview formatting for one known document or range without applying it.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'format_apply',
    description: 'Apply one unexpired formatting preview after change validation.',
    readOnly: false,
    destructive: true,
    idempotent: false,
    openWorld: false,
  },
  {
    name: 'execute_command',
    description:
      'Execute one selected standard command, trusted task, or authorized custom command; never arbitrary shell.',
    readOnly: false,
    destructive: true,
    idempotent: false,
    openWorld: false,
  },
];

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

const definitions = TOOL_METADATA.map((metadata): ToolDefinition => ({
  name: metadata.name,
  description: metadata.description,
  annotations: {
    readOnlyHint: metadata.readOnly,
    destructiveHint: metadata.destructive,
    idempotentHint: metadata.idempotent,
    openWorldHint: metadata.openWorld,
  },
  execution: { taskSupport: 'forbidden' },
  inputSchema: INPUT_SCHEMAS[metadata.name],
  outputSchema: OUTPUT_SCHEMAS[metadata.name],
}));

if (
  definitions.length !== TOOL_NAMES.length ||
  definitions.some((definition, index) => definition.name !== TOOL_NAMES[index])
) {
  throw new Error('Tool metadata does not match the frozen public tool order.');
}

export const TOOL_DEFINITIONS: readonly ToolDefinition[] = deepFreeze(definitions);

const definitionByName = new Map(
  TOOL_DEFINITIONS.map((definition) => [definition.name, definition] as const),
);

export const getToolDefinition = (name: ToolName): ToolDefinition => {
  const definition = definitionByName.get(name);
  if (!definition) {
    throw new Error(`Unknown tool: ${name}`);
  }
  return definition;
};
