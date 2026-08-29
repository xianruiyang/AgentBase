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
    description: 'List usable VS Code workspaces and logical root aliases.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'health_check',
    description: 'Check the server, VS Code bridge, and optional document activation.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'get_capabilities',
    description: 'Check which semantic operations are usable for a workspace or document.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'workspace_symbols',
    description: 'Search workspace symbols by name and return bounded navigation candidates.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'document_symbols',
    description: 'Return a bounded document outline with exact path/name filters and optional full ranges.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'symbol_info',
    description: 'Query selected semantic information at one source position.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'get_references',
    description: 'Find complete semantic references using fast C/C++ identity search or an explicit full Provider scan.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'verify_symbol_candidates',
    description: 'Verify a bounded set of source positions against one target symbol identity.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'get_call_hierarchy',
    description: 'Return bounded incoming or outgoing call hierarchy entries.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'get_type_hierarchy',
    description: 'Return bounded supertype or subtype hierarchy entries.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'get_diagnostics',
    description: 'Return diagnostics for selected files, modified files, or a workspace.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'rename_preview',
    description: 'Preview a complete semantic rename within an explicit path scope and safety budget.',
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
    description: 'List code actions that can be safely previewed as complete text changes.',
    readOnly: true,
    destructive: false,
    idempotent: true,
    openWorld: false,
  },
  {
    name: 'code_action_preview',
    description: 'Turn one cached code action into a reviewable text change preview.',
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
    description: 'Preview complete document or range formatting changes.',
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
      'Execute one standard user command, trusted-workspace task, or authorized custom command.',
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
