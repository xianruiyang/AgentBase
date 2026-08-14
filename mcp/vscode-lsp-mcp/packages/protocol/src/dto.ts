export const TOOL_NAMES = [
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
  'rename_preview',
  'rename_apply',
  'code_actions',
  'code_action_preview',
  'code_action_apply',
  'format_preview',
  'format_apply',
  'execute_command',
] as const;

export type ToolName = (typeof TOOL_NAMES)[number];

export const SYMBOL_KINDS = [
  'file',
  'module',
  'namespace',
  'package',
  'class',
  'method',
  'property',
  'field',
  'constructor',
  'enum',
  'interface',
  'function',
  'variable',
  'constant',
  'string',
  'number',
  'boolean',
  'array',
  'object',
  'key',
  'null',
  'enumMember',
  'struct',
  'event',
  'operator',
  'typeParameter',
  'unknown',
] as const;

export type SymbolKind = (typeof SYMBOL_KINDS)[number];

export const CAPABILITY_NAMES = [
  'workspaceSymbols',
  'documentSymbols',
  'hover',
  'declaration',
  'definition',
  'typeDefinition',
  'implementation',
  'signatureHelp',
  'references',
  'callHierarchy',
  'typeHierarchy',
  'rename',
  'codeActions',
  'documentFormatting',
  'rangeFormatting',
  'diagnostics',
  'commands',
  'tasks',
] as const;

export type CapabilityName = (typeof CAPABILITY_NAMES)[number];

export const ERROR_CODES = [
  'INVALID_ARGUMENT',
  'INVALID_RESULT_WINDOW',
  'WORKSPACE_NOT_FOUND',
  'WORKSPACE_DISCONNECTED',
  'ROOT_NOT_FOUND',
  'PATH_OUTSIDE_WORKSPACE',
  'DOCUMENT_NOT_FOUND',
  'POSITION_OUT_OF_RANGE',
  'PROVIDER_UNAVAILABLE',
  'PROVIDER_TIMEOUT',
  'PREVIEW_NOT_FOUND',
  'PREVIEW_EXPIRED',
  'RENAME_SCOPE_VIOLATION',
  'RENAME_IDENTITY_UNVERIFIED',
  'RENAME_NO_EDITS',
  'PREVIEW_TOO_LARGE',
  'DOCUMENT_CHANGED',
  'EDIT_CONFLICT',
  'APPLY_FAILED',
  'ACTION_SET_NOT_FOUND',
  'ACTION_NOT_PREVIEWABLE',
  'COMMAND_NOT_ALLOWED',
  'INTERACTIVE_COMMAND',
  'COMMAND_TIMEOUT',
  'COMMAND_FAILED',
  'INTERNAL_ERROR',
] as const;

export type ErrorCode = (typeof ERROR_CODES)[number];

export type JsonPrimitive = null | boolean | number | string;
export type JsonValue = JsonPrimitive | JsonObject | readonly JsonValue[];

export interface JsonObject {
  readonly [key: string]: JsonValue;
}

export interface ResultWindowInput {
  readonly resultStart?: number;
  readonly resultEnd?: number;
}

export interface Range {
  readonly startLine: number;
  readonly startColumn: number;
  readonly endLine: number;
  readonly endColumn: number;
}

export type ListWorkspacesInput = ResultWindowInput;

export interface HealthCheckInput extends ResultWindowInput {
  readonly workspaceId?: string;
  readonly file?: string;
}

export interface GetCapabilitiesInput extends ResultWindowInput {
  readonly workspaceId: string;
  readonly file?: string;
  readonly capabilities?: readonly CapabilityName[];
}

export interface GlobFilterInput {
  readonly includeGlobs?: readonly string[];
  readonly excludeGlobs?: readonly string[];
}

export interface WorkspaceSymbolsInput extends ResultWindowInput, GlobFilterInput {
  readonly workspaceId: string;
  readonly query: string;
  readonly kinds?: readonly SymbolKind[];
  readonly contextLines?: number;
}

export interface DocumentSymbolsInput extends ResultWindowInput {
  readonly workspaceId: string;
  readonly file: string;
  readonly kinds?: readonly SymbolKind[];
  readonly maxDepth?: number;
  readonly nameEquals?: string;
  readonly pathEquals?: readonly string[];
  readonly includeRange?: boolean;
  readonly contextLines?: number;
}

export const SYMBOL_INFO_INCLUDES = [
  'hover',
  'declaration',
  'definition',
  'typeDefinition',
  'implementation',
  'signatureHelp',
] as const;

export type SymbolInfoInclude = (typeof SYMBOL_INFO_INCLUDES)[number];

export interface SymbolInfoInput extends ResultWindowInput, GlobFilterInput {
  readonly workspaceId: string;
  readonly file: string;
  readonly line: number;
  readonly column: number;
  readonly include?: readonly SymbolInfoInclude[];
  readonly contextLines?: number;
}

export interface GetReferencesInput extends ResultWindowInput, GlobFilterInput {
  readonly workspaceId: string;
  readonly file: string;
  readonly line: number;
  readonly column: number;
  readonly contextLines?: number;
  readonly timeoutMs?: number;
}

export interface GetCallHierarchyInput extends ResultWindowInput {
  readonly workspaceId: string;
  readonly file: string;
  readonly line: number;
  readonly column: number;
  readonly direction?: 'incoming' | 'outgoing' | 'both';
  readonly maxDepth?: number;
}

export interface GetTypeHierarchyInput extends ResultWindowInput {
  readonly workspaceId: string;
  readonly file: string;
  readonly line: number;
  readonly column: number;
  readonly direction?: 'supertypes' | 'subtypes' | 'both';
  readonly maxDepth?: number;
}

export type DiagnosticSeverity = 'error' | 'warning' | 'information' | 'hint';

export interface GetDiagnosticsInput extends ResultWindowInput {
  readonly workspaceId: string;
  readonly scope?: 'files' | 'modifiedFiles' | 'workspace';
  readonly files?: readonly string[];
  readonly severities?: readonly DiagnosticSeverity[];
  readonly sources?: readonly string[];
  readonly includeRelatedInformation?: boolean;
}

export interface RenamePreviewInput extends GlobFilterInput {
  readonly workspaceId: string;
  readonly file: string;
  readonly line: number;
  readonly column: number;
  readonly newName: string;
  readonly includeGlobs: readonly string[];
  readonly timeoutMs?: number;
}

export interface PreviewApplyInput {
  readonly previewId: string;
}

export interface CodeActionsInput extends ResultWindowInput {
  readonly workspaceId: string;
  readonly file: string;
  readonly range: Range;
  readonly onlyKinds?: readonly string[];
}

export interface CodeActionPreviewInput {
  readonly actionSetId: string;
  readonly actionId: string;
}

export interface FormattingOptions {
  readonly tabSize?: number;
  readonly insertSpaces?: boolean;
}

export interface FormatPreviewInput {
  readonly workspaceId: string;
  readonly file: string;
  readonly range?: Range;
  readonly options?: FormattingOptions;
}

export interface CommandTarget {
  readonly kind: 'command';
  readonly commandId: string;
  readonly arguments?: readonly JsonValue[];
}

export interface TaskTarget {
  readonly kind: 'task';
  readonly taskName: string;
  readonly taskRoot?: string;
}

export interface ExecuteCommandInput {
  readonly workspaceId: string;
  readonly target: CommandTarget | TaskTarget;
  readonly saveBeforeRun?: 'none' | 'active' | 'all';
  readonly timeoutMs?: number;
  readonly maxOutputChars?: number;
  readonly retainOutputLog?: boolean;
}

export interface ToolInputMap {
  readonly list_workspaces: ListWorkspacesInput;
  readonly health_check: HealthCheckInput;
  readonly get_capabilities: GetCapabilitiesInput;
  readonly workspace_symbols: WorkspaceSymbolsInput;
  readonly document_symbols: DocumentSymbolsInput;
  readonly symbol_info: SymbolInfoInput;
  readonly get_references: GetReferencesInput;
  readonly get_call_hierarchy: GetCallHierarchyInput;
  readonly get_type_hierarchy: GetTypeHierarchyInput;
  readonly get_diagnostics: GetDiagnosticsInput;
  readonly rename_preview: RenamePreviewInput;
  readonly rename_apply: PreviewApplyInput;
  readonly code_actions: CodeActionsInput;
  readonly code_action_preview: CodeActionPreviewInput;
  readonly code_action_apply: PreviewApplyInput;
  readonly format_preview: FormatPreviewInput;
  readonly format_apply: PreviewApplyInput;
  readonly execute_command: ExecuteCommandInput;
}

export interface Collection<T> {
  readonly results: readonly T[];
  readonly available: number;
  readonly warnings?: readonly string[];
  readonly provider?: ProviderObservation;
}

export interface ProviderObservation {
  readonly status: 'completed' | 'unavailable' | 'notReady' | 'cancelled' | 'timedOut' | 'failed';
  readonly elapsedMs: number;
  readonly attempts: number;
}

export interface Workspace {
  readonly workspaceId: string;
  readonly name: string;
  readonly roots: readonly string[];
}

export interface HealthResult {
  readonly target: string;
  readonly status: 'healthy' | 'degraded' | 'unavailable' | 'timedOut';
  readonly issues?: readonly string[];
}

export interface Capability {
  readonly name: CapabilityName;
  readonly status: 'available' | 'unavailable' | 'unknown' | 'timedOut';
  readonly reason?: string;
}

export interface SymbolHit {
  readonly name: string;
  readonly kind: SymbolKind;
  readonly file: string;
  readonly line: number;
  readonly column: number;
  readonly container?: string;
  readonly snippet?: string;
}

export interface DocumentSymbol {
  readonly kind: SymbolKind;
  readonly path: readonly string[];
  readonly line: number;
  readonly column: number;
  readonly range?: Range;
  readonly snippet?: string;
}

export interface HoverInfo {
  readonly type: 'hover';
  readonly text: string;
}

export interface LocationInfo {
  readonly type: 'declaration' | 'definition' | 'typeDefinition' | 'implementation';
  readonly file: string;
  readonly line: number;
  readonly column: number;
  readonly snippet?: string;
}

export interface SignatureParameter {
  readonly label: string;
  readonly documentation?: string;
}

export interface SignatureInfo {
  readonly type: 'signatureHelp';
  readonly label: string;
  readonly activeParameter?: number;
  readonly documentation?: string;
  readonly parameters?: readonly SignatureParameter[];
}

export type SymbolInfoResult = HoverInfo | LocationInfo | SignatureInfo;

export interface ReferenceHit {
  readonly file: string;
  readonly line: number;
  readonly column: number;
  readonly snippet?: string;
}

export interface HierarchySymbol {
  readonly name: string;
  readonly kind: SymbolKind;
  readonly file: string;
  readonly line: number;
  readonly column: number;
}

export interface CallHierarchyEntry {
  readonly relation: 'root' | 'incoming' | 'outgoing';
  readonly depth: number;
  readonly symbol: HierarchySymbol;
  readonly parent?: HierarchySymbol;
  readonly callSites?: readonly Range[];
}

export interface TypeHierarchyEntry {
  readonly relation: 'root' | 'supertype' | 'subtype';
  readonly depth: number;
  readonly symbol: HierarchySymbol;
  readonly parent?: HierarchySymbol;
}

export interface DiagnosticRelatedInformation {
  readonly file: string;
  readonly range: Range;
  readonly message: string;
}

export interface Diagnostic {
  readonly file: string;
  readonly range: Range;
  readonly severity: DiagnosticSeverity;
  readonly message: string;
  readonly code?: string | number;
  readonly source?: string;
  readonly tags?: readonly ('unnecessary' | 'deprecated')[];
  readonly relatedInformation?: readonly DiagnosticRelatedInformation[];
}

export interface TextEdit {
  readonly range: Range;
  readonly oldText: string;
  readonly newText: string;
}

export interface TextChange {
  readonly kind: 'text';
  readonly file: string;
  readonly edits: readonly TextEdit[];
}

export interface Preview {
  readonly previewId?: string;
  readonly changes: readonly TextChange[];
  readonly warnings?: readonly string[];
}

export interface ApplyResult {
  readonly changedFiles: readonly string[];
}

export interface CodeAction {
  readonly actionId: string;
  readonly title: string;
  readonly kind?: string;
}

export interface CodeActionSet {
  readonly actionSetId?: string;
  readonly results: readonly CodeAction[];
  readonly available: number;
  readonly warnings?: readonly string[];
}

export type PublicCommandResultValue = true | number | JsonObject | readonly JsonValue[];

export interface CommandResult {
  readonly result?: PublicCommandResultValue;
  readonly output?: string;
  readonly outputTruncated?: true;
  readonly warnings?: readonly string[];
  readonly outputLog?: TaskOutputLog;
}

export interface TaskOutputLog {
  readonly path: string;
  readonly lineCount: number;
  readonly byteCount: number;
  readonly encoding: 'utf-8';
  readonly truncated: boolean;
}

export interface WorkspaceDisconnectedDetails {
  readonly phase: 'preflight' | 'apply' | 'command';
  readonly outcome: 'notStarted' | 'unknown';
}

export interface DocumentChangedDetails {
  readonly reason: 'content' | 'version' | 'existence' | 'workspace';
  readonly files?: readonly string[];
  readonly additionalFiles?: number;
}

export interface EditConflictDetails {
  readonly reason:
    | 'overlappingEdits'
    | 'rangeOutOfBounds'
    | 'unsupportedEdit'
    | 'ambiguousOperationOrder';
  readonly files?: readonly string[];
  readonly additionalFiles?: number;
}

export interface ApplyFailedDetails {
  readonly stage: 'apply' | 'readback';
  readonly outcome: 'notApplied' | 'unknown' | 'postconditionFailed';
}

export interface RenameScopeViolationDetails {
  readonly files: readonly string[];
  readonly additionalFiles?: number;
  readonly totalFiles: number;
}

export interface RenameIdentityUnverifiedDetails {
  readonly reason:
    | 'targetUnresolved'
    | 'editUnresolved'
    | 'mismatchedSymbol'
    | 'textMismatch'
    | 'budgetExceeded'
    | 'providerFailed'
    | 'providerTimedOut';
  readonly checkedEdits: number;
  readonly totalEdits: number;
  readonly files?: readonly string[];
  readonly additionalFiles?: number;
}

export interface PreviewTooLargeDetails {
  readonly changedFiles: number;
  readonly edits: number;
  readonly textCharacters: number;
  readonly serializedBytes: number;
  readonly limits: {
    readonly changedFiles: number;
    readonly edits: number;
    readonly textCharacters: number;
    readonly serializedBytes: number;
  };
}

export interface ActionNotPreviewableDetails {
  readonly reason:
    | 'missingEdit'
    | 'containsCommand'
    | 'resourceOperationsUnsupported'
    | 'unsupportedEdit'
    | 'cachedActionInvalid';
}

export interface InteractiveCommandDetails {
  readonly targetKind: 'command' | 'task';
  readonly reason:
    | 'inputVariable'
    | 'commandVariable'
    | 'uiInteraction'
    | 'workspaceTrust'
    | 'customExecution'
    | 'backgroundTask'
    | 'unknownInteractivity';
}

export type CommandTimeoutDetails =
  | {
      readonly targetKind: 'command';
      readonly timeoutMs: number;
      readonly outcome: 'notStarted' | 'unknown';
    }
  | {
      readonly targetKind: 'task';
      readonly timeoutMs: number;
      readonly outcome: 'notStarted' | 'terminated' | 'unknown';
      readonly outputLog?: TaskOutputLog;
    };

export type CommandFailedDetails =
  | {
      readonly targetKind: 'task';
      readonly reason: 'nonZeroExit';
      readonly outcome: 'failed';
      readonly exitCode: number;
      readonly outputLog?: TaskOutputLog;
    }
  | {
      readonly targetKind: 'command';
      readonly reason:
        | 'saveFailed'
        | 'rejected'
        | 'cancelled'
        | 'completionUnverifiable'
        | 'alreadyRunning';
      readonly outcome: 'notStarted' | 'failed' | 'terminated' | 'unknown';
      readonly exitCode?: never;
      readonly outputLog?: never;
    }
  | {
      readonly targetKind: 'task';
      readonly reason:
        | 'saveFailed'
        | 'rejected'
        | 'cancelled'
        | 'completionUnverifiable'
        | 'alreadyRunning';
      readonly outcome: 'notStarted' | 'failed' | 'terminated' | 'unknown';
      readonly exitCode?: never;
      readonly outputLog?: TaskOutputLog;
    };

export type ErrorDetails =
  | WorkspaceDisconnectedDetails
  | DocumentChangedDetails
  | EditConflictDetails
  | ApplyFailedDetails
  | RenameScopeViolationDetails
  | RenameIdentityUnverifiedDetails
  | PreviewTooLargeDetails
  | ActionNotPreviewableDetails
  | InteractiveCommandDetails
  | CommandTimeoutDetails
  | CommandFailedDetails;

interface ToolErrorBase<C extends ErrorCode, R extends boolean> {
  readonly code: C;
  readonly message: string;
  readonly retryable: R;
  readonly action?: string;
  readonly provider?: ProviderObservation;
}

type ToolErrorWithoutDetails<C extends ErrorCode, R extends boolean> = ToolErrorBase<C, R> & {
  readonly details?: never;
};

type NonRetryableSimpleError = ToolErrorWithoutDetails<
  | 'INVALID_ARGUMENT'
  | 'INVALID_RESULT_WINDOW'
  | 'ROOT_NOT_FOUND'
  | 'PATH_OUTSIDE_WORKSPACE'
  | 'DOCUMENT_NOT_FOUND'
  | 'POSITION_OUT_OF_RANGE'
  | 'PROVIDER_UNAVAILABLE'
  | 'PREVIEW_NOT_FOUND'
  | 'PREVIEW_EXPIRED'
  | 'RENAME_NO_EDITS'
  | 'ACTION_SET_NOT_FOUND'
  | 'COMMAND_NOT_ALLOWED',
  false
>;

type RetryableSimpleError = ToolErrorWithoutDetails<
  'WORKSPACE_NOT_FOUND' | 'PROVIDER_TIMEOUT' | 'INTERNAL_ERROR',
  true
>;

export type WorkspaceDisconnectedError =
  | ToolErrorWithoutDetails<'WORKSPACE_DISCONNECTED', true>
  | (ToolErrorBase<'WORKSPACE_DISCONNECTED', true> & {
      readonly details: { readonly phase: 'preflight'; readonly outcome: 'notStarted' };
    })
  | (ToolErrorBase<'WORKSPACE_DISCONNECTED', false> & {
      readonly details: {
        readonly phase: 'apply' | 'command';
        readonly outcome: 'unknown';
      };
    });

type DetailedToolError<C extends ErrorCode, D extends ErrorDetails> = ToolErrorBase<C, false> & {
  readonly details: D;
};

export type ToolError =
  | NonRetryableSimpleError
  | RetryableSimpleError
  | WorkspaceDisconnectedError
  | DetailedToolError<'DOCUMENT_CHANGED', DocumentChangedDetails>
  | DetailedToolError<'EDIT_CONFLICT', EditConflictDetails>
  | DetailedToolError<'APPLY_FAILED', ApplyFailedDetails>
  | DetailedToolError<'RENAME_SCOPE_VIOLATION', RenameScopeViolationDetails>
  | DetailedToolError<'RENAME_IDENTITY_UNVERIFIED', RenameIdentityUnverifiedDetails>
  | DetailedToolError<'PREVIEW_TOO_LARGE', PreviewTooLargeDetails>
  | DetailedToolError<'ACTION_NOT_PREVIEWABLE', ActionNotPreviewableDetails>
  | DetailedToolError<'INTERACTIVE_COMMAND', InteractiveCommandDetails>
  | DetailedToolError<'COMMAND_TIMEOUT', CommandTimeoutDetails>
  | DetailedToolError<'COMMAND_FAILED', CommandFailedDetails>;

export type ToolEnvelope<T> =
  | { readonly ok: true; readonly data: T }
  | { readonly ok: false; readonly error: ToolError };

export interface ToolOutputDataMap {
  readonly list_workspaces: Collection<Workspace>;
  readonly health_check: Collection<HealthResult>;
  readonly get_capabilities: Collection<Capability>;
  readonly workspace_symbols: Collection<SymbolHit>;
  readonly document_symbols: Collection<DocumentSymbol>;
  readonly symbol_info: Collection<SymbolInfoResult>;
  readonly get_references: Collection<ReferenceHit>;
  readonly get_call_hierarchy: Collection<CallHierarchyEntry>;
  readonly get_type_hierarchy: Collection<TypeHierarchyEntry>;
  readonly get_diagnostics: Collection<Diagnostic>;
  readonly rename_preview: Preview;
  readonly rename_apply: ApplyResult;
  readonly code_actions: CodeActionSet;
  readonly code_action_preview: Preview;
  readonly code_action_apply: ApplyResult;
  readonly format_preview: Preview;
  readonly format_apply: ApplyResult;
  readonly execute_command: CommandResult;
}

export type ToolResponseMap = {
  readonly [K in ToolName]: ToolEnvelope<ToolOutputDataMap[K]>;
};

export interface ToolAnnotations {
  readonly readOnlyHint: boolean;
  readonly destructiveHint: boolean;
  readonly idempotentHint: boolean;
  readonly openWorldHint: boolean;
}

export interface ToolExecutionPolicy {
  readonly taskSupport: 'forbidden';
}
