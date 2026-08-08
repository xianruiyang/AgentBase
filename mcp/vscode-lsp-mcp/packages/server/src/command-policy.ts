import {
  classifyCommandArgumentVariable,
  classifyCommandRisk,
  isStandardUserCommand,
  type ExecuteCommandInput,
  type ToolResponseMap,
} from '@simplechat/vscode-lsp-mcp-protocol';

export const serverCommandSafetyPreflight = (
  input: ExecuteCommandInput,
): ToolResponseMap['execute_command'] | undefined => {
  if (input.target.kind !== 'command') return undefined;
  const risk = classifyCommandRisk(input.target.commandId);
  const variable = classifyCommandArgumentVariable(input.target.arguments ?? []);
  if ((risk === undefined || isStandardUserCommand(input.target.commandId)) &&
      variable === undefined) return undefined;
  return Object.freeze({
    ok: false,
    error: Object.freeze({
      code: 'INTERACTIVE_COMMAND',
      message: 'The command was rejected before workspace dispatch because it is not safely non-interactive.',
      retryable: false,
      details: Object.freeze({
        targetKind: 'command',
        reason: variable ?? 'uiInteraction',
      }),
    }),
  });
};
