# VS Code LSP MCP 工具 Schema

## 1. 文档定位

本文是 `vscode-lsp-mcp` 第一版公开工具接口的规范源。接口只为 LLM 的定位、理解、修改和验证流程服务，不复刻传统 LSP 数据结构，也不暴露 Bridge、Provider 或预览缓存的内部实现字段。

- Schema 版本：`1.1.0-draft.1`
- MCP 规范基线：`2025-11-25`
- JSON Schema 方言：Draft 2020-12
- MCP `inputSchema` 和调用参数：严格 JSON
- MCP `content[].text`：由精简 DTO 确定性序列化的 YAML，也是唯一公开结果正文
- 内部输出 Schema：仅用于服务端校验精简 DTO，不通过 `tools/list` 或 `tools/call` 暴露
- 行列：1-based
- 范围结束位置：exclusive

参考：[MCP Tools 规范](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)。

## 2. LLM 接口原则

### 2.1 只返回完成下一步所需的信息

- 不返回实际 Provider 身份，因为 VS Code Provider Command 通常不能可靠提供该信息。
- 不返回请求中已有的 `workspaceId`、工具名、操作类型和参数回显。
- 不返回 `requestId`、连接实例 ID、文档哈希、缓存时间戳等内部诊断字段；符号查询只公开当前 Provider 调用的紧凑耗时/尝试回执，供本任务升降级使用。
- 不输出值为 `null`、`false`、空字符串或空数组的可选字段。
- 不为统一 DTO 强迫无关工具返回空字段。
- 能由同一响应其他字段直接推导的值不重复返回。
- 只有会影响 LLM 判断或下一次调用的标识符才公开。

### 2.2 位置优先

语义查询使用 `workspaceId + file + line + column`。输出位置默认只包含 `file + line + column`；只有编辑和诊断需要完整范围。

`file` 是工作区逻辑路径：

- 单根工作区使用相对路径，例如 `src/app.ts`。
- 多根工作区使用 `rootAlias/path`，例如 `backend/src/app.ts`。
- `rootAlias` 由 `list_workspaces` 返回并保证在一个 `workspaceId` 内唯一。
- 不向 LLM 返回本地绝对路径、URI 或内部 workspace folder ID。

所有公开 `line`/`column` 使用 1-based 坐标；`column` 按 UTF-16 code unit 计数，与 VS Code `Position.character` 一致，不是 UTF-8 byte、Unicode code point 或 grapheme cluster。`Range` 的 end exclusive，且每个编辑范围只对生成它的精确文档快照有效。

### 2.3 结果窗口

所有独立候选集合支持：

```json
{
  "resultStart": { "type": "integer", "minimum": 1, "default": 1 },
  "resultEnd": { "type": "integer", "minimum": 1 }
}
```

规则：

- 均省略：显示 `1..20`。
- 仅提供 `resultStart`：从该项开始显示 20 项。
- 仅提供 `resultEnd`：显示 `1..resultEnd`。
- `resultEnd >= resultStart`，单次最多 100 项。
- 先规范化、去重和稳定排序，再截取窗口。
- 起点超过可用数量时成功返回空 `results`。
- WorkspaceEdit、TextEdit 和 apply 报告属于一个操作，不按候选窗口切片。

第一版精确使用结果窗口的工具为：`list_workspaces`、`health_check`、`get_capabilities`、`workspace_symbols`、`document_symbols`、`symbol_info`、`get_references`、`get_call_hierarchy`、`get_type_hierarchy`、`get_diagnostics` 和 `code_actions`。`verify_symbol_candidates` 的输出与显式候选输入一一对应，不再二次分页。未注册的 MCP completion 能力不在本组件第一版范围内。

集合只额外返回可用候选数量：

```yaml
available: 46
```

- `available` 是 Provider 本次实际返回并完成去重后的数量，不声称是语言服务器未截断的全局绝对总数。
- LLM 已知自己请求的起点，并可由 `results.length` 计算本次终点；下一页起点为 `resultStart + results.length`，因此不重复返回窗口起止字段。

### 2.4 Schema 生成

- 每个公开工具声明独立的 `inputSchema`；不声明 `outputSchema`，避免客户端把完整 YAML 与完整 `structuredContent` 同时注入模型上下文。
- 每个工具仍维护独立的内部输出 Schema，在 YAML 序列化前校验精简 DTO。
- 输入对象默认 `additionalProperties: false`。
- 公共 `$defs` 由 `packages/protocol` 维护，构建时内联到每个工具 Schema。
- Schema 可表达的约束由 JSON Schema 校验；位置顺序、窗口宽度等跨字段约束由服务端再次校验。

计数口径冻结为：

- 19 个公开工具。
- `tools/list` 公开 19 份独立 `inputSchema`。
- 服务端内部维护 19 份输出 Schema；输入与内部输出共 38 份 Schema，均可单独通过 Draft 2020-12 校验。
- 公共 `$defs` 是生成源，不是额外公开工具 Schema，也不计入上述数量。

### 2.5 默认值和跨字段校验

- JSON Schema 的 `default` 只描述接口默认值；服务端必须在 Schema 校验成功后显式完成默认值归一化，不能依赖校验器自动写入。
- `Range` 按 `(line, column)` 字典序比较，结束位置不得早于开始位置；起止相同的零长度范围合法，用于插入编辑。涉及已打开文档时，服务端还要校验位置未超出文档。
- 结果窗口在应用默认值后必须满足 `resultEnd >= resultStart` 且宽度 `resultEnd - resultStart + 1 <= 100`。
- `includeGlobs` 和 `excludeGlobs` 匹配使用 `/` 的工作区逻辑路径。第一版只支持 `*`、`?`、`**` 和字符类 `[...]`；先应用 include，再应用 exclude；不支持或无效的模式返回 `INVALID_ARGUMENT`。
- `contextLines: 0` 不输出 `snippet`；大于 0 时，snippet 包含命中行及其前后最多 N 行，遇文件边界截断。服务端必须在截取前统一换行符，不能返回工作区外内容。
- `document_symbols.maxDepth` 省略表示不限制深度，`0` 只返回顶层符号。调用/类型层级的 `maxDepth: 0` 只返回根节点。
- `document_symbols.nameEquals` 比较 `path` 最后一项，`pathEquals` 比较完整路径；均为 ordinal exact 且在结果窗口前执行。`includeRange` 默认关闭。
- `execute_command.target.taskRoot` 在单根或 taskName 全工作区唯一时可以省略；存在多个同名 task 候选时必须提供，否则返回 `INVALID_ARGUMENT`，不得静默选择。

## 3. 结果 Envelope

成功：

```yaml
ok: true
data: {}
```

失败：

```yaml
ok: false
error:
  code: PROVIDER_UNAVAILABLE
  message: Definition is unavailable for this document.
  retryable: false
  action: Install or activate a language extension that supports definitions.
```

`action` 和 `details` 仅在能帮助 LLM 修正调用时输出。

内部输出 Schema 外壳：

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "ok": { "const": true },
        "data": { "$ref": "#/$defs/ToolSuccessData" }
      },
      "required": ["ok", "data"],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "ok": { "const": false },
        "error": { "$ref": "#/$defs/ToolError" }
      },
      "required": ["ok", "error"],
      "additionalProperties": false
    }
  ]
}
```

每个工具把 `ToolSuccessData` 替换为第 6 节指定的成功数据类型。

服务端先用该 Schema 校验精简 DTO，再把同一 DTO 序列化为 YAML。公开 `tools/list` 不包含 `outputSchema`，公开 `tools/call` 不包含 `structuredContent`，因此模型上下文只接收一份 YAML；严格 JSON 仅保留在参数、IPC 和内部校验流程中。

## 4. 公共 DTO

以下为逻辑类型。标记 `?` 的字段仅在有值且对 LLM 有用时输出。

### 4.1 基础类型

```yaml
ToolError:
  code: ErrorCode
  message: string
  retryable: boolean
  action?: string
  provider?: ProviderObservation
  details?: ErrorDetails object # 仅允许第 5.1 节按 code 冻结的对象分支

Collection<T>:
  results: T[]
  available: integer >= 0
  warnings?: string[]
  provider?: ProviderObservation

ProviderObservation:
  status: completed | unavailable | notReady | cancelled | timedOut | failed
  elapsedMs: integer >= 0
  attempts: integer >= 0

Range:
  startLine: integer >= 1
  startColumn: integer >= 1
  endLine: integer >= 1
  endColumn: integer >= 1

```

`warnings` 只承载部分 Provider 超时、底层已知截断等非致命且可行动的信息，不输出空数组。

`retryable` 是必填字段，因此值为 `false` 时仍必须输出。`details` 只允许对应错误码规范明确列出的、经过清理且可帮助修正调用的 JSON 字段；不得作为任意内部异常、绝对路径、URI、堆栈或 Provider 数据的透传容器。apply/command 相关分支已在第 5.1 节冻结。

所有输出对象都拒绝对应 DTO 未声明的字段。所有必填字符串 `minLength: 1`；所有必填集合根据语义声明 `minItems`，只有 `Collection.results`、无变更 `Preview.changes` 等明确允许的结果可以为空。

### 4.2 工作区和能力

```yaml
Workspace:
  workspaceId: string
  name: string
  roots: string[] # 至少一项

HealthResult:
  target: string # 字面量 server 或实际 workspaceId
  status: healthy | degraded | unavailable | timedOut
  issues?: string[]

Capability:
  name: CapabilityName
  status: available | unavailable | unknown | timedOut
  reason?: string
```

`roots` 是工作区内所有 workspace folder 的唯一别名列表，单根工作区也返回一项；单根文件路径仍省略 alias 前缀，多根文件路径必须使用 `rootAlias/path`。`server` 是 HealthResult.target 的保留字，workspaceId 不得取该值。版本、物理路径、URI、PID、端点、最后心跳和连接实例 ID 留在 doctor/debug 日志中，不进入 `health_check` 公共 DTO。

### 4.3 符号和语义结果

```yaml
SymbolHit:
  name: string
  kind: SymbolKind
  file: string
  line: integer >= 1
  column: integer >= 1
  container?: string
  snippet?: string

DocumentSymbol:
  kind: SymbolKind
  path: string[]
  line: integer >= 1
  column: integer >= 1
  range?: Range
  snippet?: string

HoverInfo:
  type: hover
  text: string

LocationInfo:
  type: declaration | definition | typeDefinition | implementation
  file: string
  line: integer >= 1
  column: integer >= 1
  snippet?: string

SignatureInfo:
  type: signatureHelp
  label: string
  activeParameter?: integer >= 0
  documentation?: string
  parameters?: SignatureParameter[]

SignatureParameter:
  label: string
  documentation?: string

SymbolInfoResult:
  oneOf: HoverInfo | LocationInfo | SignatureInfo

ReferenceHit:
  file: string
  line: integer >= 1
  column: integer >= 1
  snippet?: string

SymbolCandidateVerification:
  file: string
  line: integer >= 1
  column: integer >= 1
  status: verified | mismatched | unresolved | positionOutOfRange

HierarchySymbol:
  name: string
  kind: SymbolKind
  file: string
  line: integer >= 1
  column: integer >= 1

CallHierarchyEntry:
  relation: root | incoming | outgoing
  depth: integer >= 0
  symbol: HierarchySymbol
  parent?: HierarchySymbol
  callSites?: Range[]

TypeHierarchyEntry:
  relation: root | supertype | subtype
  depth: integer >= 0
  symbol: HierarchySymbol
  parent?: HierarchySymbol
```

`SymbolKind` 使用 VS Code 的稳定可读名称：

```yaml
SymbolKind:
  oneOf:
    - file
    - module
    - namespace
    - package
    - class
    - method
    - property
    - field
    - constructor
    - enum
    - interface
    - function
    - variable
    - constant
    - string
    - number
    - boolean
    - array
    - object
    - key
    - 'null'
    - enumMember
    - struct
    - event
    - operator
    - typeParameter
    - unknown
```

设计约束：

- Workspace symbol 不伪造完整限定名。
- Document symbol 的 `path` 由文档符号树确定性生成，例如 `[ClassName, methodName]`；名称是最后一项，深度是数组长度减一，不重复输出。
- 引用结果不返回 `isDeclaration`，因为 Reference Provider 不标记单项语义。候选核验只裁决调用方提交的位置，不声称调用方的文本候选集合完整。
- Symbol info 使用判别联合，不为 Hover 返回空 location，也不为 Definition 返回空 markdown。
- 多个签名候选把当前 active signature 排在第一项；只有参数存在独立文档时才输出 `parameters`。
- Symbol info 忽略请求中 `include` 的排列差异，按 `hover`、`declaration`、`definition`、`typeDefinition`、`implementation`、`signatureHelp` 的固定能力顺序分组。组内先规范化和去重：Hover 按标准化 text，Location 按 file/line/column/snippet，Signature 先 active signature、再按 label/documentation。分组拼接后再应用统一结果窗口。
- 层级结果不公开只在单次 Provider 调用内有意义的 item ID。
- incoming call 的 `callSites` 位于 `symbol.file`，outgoing call 的 `callSites` 位于 `parent.file`。

### 4.4 诊断

```yaml
Diagnostic:
  file: string
  range: Range
  severity: error | warning | information | hint
  message: string
  code?: string | integer
  source?: string
  tags?: (unnecessary | deprecated)[]
  relatedInformation?: DiagnosticRelatedInformation[]

DiagnosticRelatedInformation:
  file: string
  range: Range
  message: string
```

诊断 ID 没有后续查询用途，因此不公开。

### 4.5 编辑、预览和应用

```yaml
TextEdit:
  range: Range
  oldText: string
  newText: string

TextChange:
  kind: text
  file: string
  edits: TextEdit[] # 至少一项

Preview:
  previewId?: string
  changes: TextChange[]
  warnings?: string[]

ApplyResult:
  changedFiles: string[]
```

第一版只应用 VS Code 公共 `WorkspaceEdit.entries()` 可枚举并重建的 `TextEdit`。先要求 `WorkspaceEdit.size === WorkspaceEdit.entries().length` 作为保守拒绝门禁，随后仍只重建 entries；该相等关系本身不被当作“不含隐藏资源操作”的证明。资源 create/rename/delete、SnippetTextEdit 和附带 command 的 Action 不得进入 Preview；组件永远重建并应用公开展示的 text-only edit，不应用 Provider 原始对象。版本、内容哈希、Provider 数据、标题和过期时间仅存内部缓存。`changes` 非空时必须返回 `previewId`；格式化等操作没有变更时成功返回空 `changes` 并省略 `previewId`，因此不会产生可 apply 的空预览。成功 apply 的 `ok: true` 已表达“已应用”，不再回显 `previewId`、操作类型或逐文件成功状态；`changedFiles` 至少一项，只包含经 readback 验证的 text target，并按逻辑路径稳定排序。

### 4.6 Code Action 和命令

```yaml
CodeActionSet:
  actionSetId?: string
  results: CodeAction[]
  available: integer >= 0
  warnings?: string[]

CodeAction:
  actionId: string
  title: string
  kind?: string

CommandResult:
  result?: JSON value
  output?: string
  outputTruncated?: true
  warnings?: string[]
  outputLog?: TaskOutputLog

TaskOutputLog:
  path: workspace-logical string
  lineCount: integer >= 0
  byteCount: integer >= 0
  encoding: utf-8
  truncated: boolean
```

Code Action 结果只包含能安全解析为完整 text-only WorkspaceEdit 的 Action，并把 preferred Action 排在前面。不返回带 command、资源操作、SnippetTextEdit 或其它无法完整公开重建的 Action，也不暴露 command ID、内部解析状态、preferred 标记或交互风险枚举。

`actionSetId` 仅在 `results` 非空时输出；空候选集没有后续 preview 行为，不生成无用句柄。

命令成功由外层 `ok: true` 表达。command 返回 string 时使用 `output` 并按 Unicode code point 截断；JSON-compatible 非 string 返回值使用 `result`，序列化后超过 `maxOutputChars` 时省略并给 warning。task 成功不伪造 `output`；默认删除捕获，`retainOutputLog: true` 时在 `data.outputLog` 返回日志元数据。Windows 上无依赖的 `ProcessExecution` 失败时可在错误 details 中返回 `outputLog`。正文只保存在 task root 的 `.vscode-lsp-mcp/task-logs`，不进入 MCP 响应。工具名、任务名、状态、开始时间、结束时间和耗时都不在结果中重复。

## 5. 错误码

| 错误码 | 含义 | 默认可重试 |
|---|---|---|
| `INVALID_ARGUMENT` | 参数或条件组合无效 | 否 |
| `INVALID_RESULT_WINDOW` | 窗口逆序或超过 100 项 | 否 |
| `WORKSPACE_NOT_FOUND` | `workspaceId` 不存在 | 是 |
| `WORKSPACE_DISCONNECTED` | VS Code 实例已断开 | 是 |
| `ROOT_NOT_FOUND` | 多根工作区逻辑路径中的 root alias 不存在 | 否 |
| `PATH_OUTSIDE_WORKSPACE` | 路径越过工作区边界 | 否 |
| `DOCUMENT_NOT_FOUND` | 文档不存在或无法打开 | 否 |
| `POSITION_OUT_OF_RANGE` | 行列超出文档范围 | 否 |
| `PROVIDER_UNAVAILABLE` | 目标语言能力不可用 | 否 |
| `PROVIDER_TIMEOUT` | 语义查询超时 | 是 |
| `PREVIEW_NOT_FOUND` | 预览 ID 不存在或已被消费 | 否 |
| `PREVIEW_EXPIRED` | 预览已过期 | 否 |
| `RENAME_SCOPE_VIOLATION` | 重命名 Provider 返回了声明 glob 范围外的目标，整份预览被拒绝 | 否 |
| `RENAME_IDENTITY_UNVERIFIED` | 重命名编辑无法全部证明属于同一符号，整份预览被拒绝 | 否 |
| `RENAME_NO_EDITS` | 重命名 Provider 未返回有效文本编辑，未创建预览 | 否 |
| `PREVIEW_TOO_LARGE` | 完整预览超过 MCP 安全输出预算，未缓存且不返回截断预览 | 否 |
| `DOCUMENT_CHANGED` | 预览后的文档版本或内容已变化 | 否 |
| `EDIT_CONFLICT` | 编辑重叠、越界、顺序歧义或编辑类型不受支持 | 否 |
| `APPLY_FAILED` | VS Code 未能应用或无法验证完整 text-only 编辑 | 否 |
| `ACTION_SET_NOT_FOUND` | Code Action 候选集不存在或已过期 | 否 |
| `ACTION_NOT_PREVIEWABLE` | Action 不能安全转换为 text-only WorkspaceEdit | 否 |
| `COMMAND_NOT_ALLOWED` | 指令或任务未被有效执行策略授权 | 否 |
| `INTERACTIVE_COMMAND` | 指令或任务可能触发 UI 输入 | 否 |
| `COMMAND_TIMEOUT` | 指令或任务未在期限内完成，结果可能未知 | 否 |
| `COMMAND_FAILED` | 指令或任务实际执行失败或完成不可证明 | 否 |
| `INTERNAL_ERROR` | 未分类内部错误 | 是 |

未知工具和基础 MCP 请求格式错误使用 JSON-RPC 协议错误；已进入工具的参数和执行错误使用 `isError: true` 与上述 error envelope。

### 5.1 状态机错误 `details` 联合

以下对象都拒绝未知字段。`files` 只含公开逻辑路径，稳定排序、去重、最多 100 项；更多项以 `additionalFiles` 计数，不得改放 absolute path 或 URI。

```yaml
WorkspaceDisconnectedDetails:
  phase: preflight | apply | command
  outcome: notStarted | unknown

DocumentChangedDetails:
  reason: content | version | existence | workspace
  files?: string[]
  additionalFiles?: integer >= 1

EditConflictDetails:
  reason: overlappingEdits | rangeOutOfBounds | unsupportedEdit | ambiguousOperationOrder
  files?: string[]
  additionalFiles?: integer >= 1

ApplyFailedDetails:
  stage: apply | readback
  outcome: notApplied | unknown | postconditionFailed

RenameScopeViolationDetails:
  files: string[] # 最多 10 个越界逻辑路径
  additionalFiles?: integer >= 1
  totalFiles: integer >= 1

RenameIdentityUnverifiedDetails:
  reason: targetUnresolved | editUnresolved | mismatchedSymbol | textMismatch | budgetExceeded | providerFailed | providerTimedOut
  checkedEdits: integer >= 0
  totalEdits: integer >= 1
  files?: string[] # 最多 10 个逻辑路径
  additionalFiles?: integer >= 1

PreviewTooLargeDetails:
  changedFiles: integer >= 0
  edits: integer >= 0
  textCharacters: integer >= 0
  serializedBytes: integer >= 0
  limits:
    changedFiles: 50
    edits: 100
    textCharacters: 50000
    serializedBytes: 65536

ActionNotPreviewableDetails:
  reason: missingEdit | containsCommand | resourceOperationsUnsupported | unsupportedEdit | cachedActionInvalid

InteractiveCommandDetails:
  targetKind: command | task
  reason: inputVariable | commandVariable | uiInteraction | workspaceTrust | customExecution | backgroundTask | unknownInteractivity

CommandTimeoutDetails:
  targetKind: command | task
  timeoutMs: integer # 1000..600000
  outcome: notStarted | terminated | unknown

CommandFailedDetails:
  targetKind: command | task
  reason: saveFailed | rejected | nonZeroExit | cancelled | completionUnverifiable | alreadyRunning
  outcome: notStarted | failed | terminated | unknown
  exitCode?: integer
```

条件：

- `WORKSPACE_DISCONNECTED` 只有在 command/apply 的副作用阶段需要澄清时才带 `WorkspaceDisconnectedDetails`。`outcome=unknown` 必须 `retryable=false`；`preflight + notStarted` 才允许 `retryable=true`。
- `DOCUMENT_CHANGED`、`EDIT_CONFLICT`、`APPLY_FAILED`、`RENAME_SCOPE_VIOLATION`、`RENAME_IDENTITY_UNVERIFIED`、`PREVIEW_TOO_LARGE`、`ACTION_NOT_PREVIEWABLE`、`INTERACTIVE_COMMAND`、`COMMAND_TIMEOUT` 和 `COMMAND_FAILED` 带各自同名 details；其它 details 分支不允许复用。
- `exitCode` 仅在 `reason=nonZeroExit` 时出现且必须非零。
- `PREVIEW_NOT_FOUND`、`PREVIEW_EXPIRED`、`ACTION_SET_NOT_FOUND` 和 `COMMAND_NOT_ALLOWED` 必须省略 details，避免暴露跨会话句柄、缓存时间或策略内部信息。
- `APPLY_FAILED`、`COMMAND_TIMEOUT` 和 `COMMAND_FAILED` 均 `retryable=false`；调用方需要检查状态并重新 preview/显式发起新命令。

## 6. 工具 Schema

### 6.1 注册信息

| 工具 | 精确 description | 成功数据类型 | annotations |
|---|---|---|---|
| `list_workspaces` | List usable VS Code workspaces and logical root aliases. | `Collection<Workspace>` | `R=true,D=false,I=true,O=false` |
| `health_check` | Check the server, VS Code bridge, and optional document activation. | `Collection<HealthResult>` | `R=true,D=false,I=true,O=false` |
| `get_capabilities` | Check which semantic operations are usable for a workspace or document. | `Collection<Capability>` | `R=true,D=false,I=true,O=false` |
| `workspace_symbols` | Search workspace symbols by name and return bounded navigation candidates. | `Collection<SymbolHit>` | `R=true,D=false,I=true,O=false` |
| `document_symbols` | Return a bounded document outline with exact path/name filters and optional full ranges. | `Collection<DocumentSymbol>` | `R=true,D=false,I=true,O=false` |
| `symbol_info` | Query selected semantic information at one source position. | `Collection<SymbolInfoResult>` | `R=true,D=false,I=true,O=false` |
| `get_references` | Find semantic references at one source position. | `Collection<ReferenceHit>` | `R=true,D=false,I=true,O=false` |
| `get_call_hierarchy` | Return bounded incoming or outgoing call hierarchy entries. | `Collection<CallHierarchyEntry>` | `R=true,D=false,I=true,O=false` |
| `get_type_hierarchy` | Return bounded supertype or subtype hierarchy entries. | `Collection<TypeHierarchyEntry>` | `R=true,D=false,I=true,O=false` |
| `get_diagnostics` | Return diagnostics for selected files, modified files, or a workspace. | `Collection<Diagnostic>` | `R=true,D=false,I=true,O=false` |
| `rename_preview` | Preview a complete semantic rename within an explicit path scope and safety budget. | `Preview` | `R=true,D=false,I=true,O=false` |
| `rename_apply` | Apply one unexpired rename preview after change validation. | `ApplyResult` | `R=false,D=true,I=false,O=false` |
| `code_actions` | List code actions that can be safely previewed as complete text changes. | `CodeActionSet` | `R=true,D=false,I=true,O=false` |
| `code_action_preview` | Turn one cached code action into a reviewable text change preview. | `Preview` | `R=true,D=false,I=true,O=false` |
| `code_action_apply` | Apply one unexpired code-action preview after change validation. | `ApplyResult` | `R=false,D=true,I=false,O=false` |
| `format_preview` | Preview complete document or range formatting changes. | `Preview` | `R=true,D=false,I=true,O=false` |
| `format_apply` | Apply one unexpired formatting preview after change validation. | `ApplyResult` | `R=false,D=true,I=false,O=false` |
| `execute_command` | Execute one standard user command, trusted-workspace task, or authorized custom command. | `CommandResult` | `R=false,D=true,I=false,O=false` |

缩写依次表示 `readOnlyHint`、`destructiveHint`、`idempotentHint`、`openWorldHint`。安全策略由服务端强制执行，不依赖 annotation。

所有 19 个工具都显式注册 `execution.taskSupport: "forbidden"`：本组件不使用 MCP task-augmented execution。`execute_command` 内部等待 VS Code command/task 完成，不等同于 MCP `tasks/*` 协议。Preview 和候选工具产生的临时服务端缓存不视为对用户工作区环境的修改，因此保持 `readOnlyHint: true`。

### 6.2 `list_workspaces`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "resultStart": { "type": "integer", "minimum": 1, "default": 1 },
    "resultEnd": { "type": "integer", "minimum": 1 }
  },
  "additionalProperties": false
}
```

输出：`Collection<Workspace>`。只列出当前可调用的工作区；失效实例由 `health_check` 和 doctor 处理，不进入正常选择结果。

### 6.3 `health_check`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "workspaceId": { "type": "string", "minLength": 1 },
    "file": { "type": "string", "minLength": 1 },
    "resultStart": { "type": "integer", "minimum": 1, "default": 1 },
    "resultEnd": { "type": "integer", "minimum": 1 }
  },
  "dependentRequired": { "file": ["workspaceId"] },
  "additionalProperties": false
}
```

输出：`Collection<HealthResult>`。省略 `workspaceId` 时检查服务端和全部登记实例；提供 `file` 时自动打开目标文档并检查语言扩展激活，不把激活和超时策略交给 LLM。正常结果只返回 target/status/可行动 issues；版本、PID、端点、IPC 和最后心跳只由 doctor/debug 提供。

### 6.4 `get_capabilities`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "workspaceId": { "type": "string", "minLength": 1 },
    "file": { "type": "string", "minLength": 1 },
    "capabilities": {
      "type": "array",
      "minItems": 1,
      "uniqueItems": true,
      "items": {
        "enum": [
          "workspaceSymbols", "documentSymbols", "hover", "declaration", "definition",
          "typeDefinition", "implementation", "signatureHelp", "references", "callHierarchy",
          "typeHierarchy", "rename", "codeActions", "documentFormatting", "rangeFormatting",
          "diagnostics", "commands", "tasks"
        ]
      }
    },
    "resultStart": { "type": "integer", "minimum": 1, "default": 1 },
    "resultEnd": { "type": "integer", "minimum": 1 }
  },
  "required": ["workspaceId"],
  "additionalProperties": false
}
```

输出：`Collection<Capability>`。提供 `file` 时自动激活文档；无法可靠判断时返回 `unknown`，不猜测 Provider 名称。

### 6.5 `workspace_symbols`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "workspaceId": { "type": "string", "minLength": 1 },
    "query": { "type": "string", "minLength": 1, "maxLength": 500 },
    "kinds": { "type": "array", "minItems": 1, "uniqueItems": true, "items": { "$ref": "#/$defs/SymbolKind" } },
    "includeGlobs": { "type": "array", "minItems": 1, "maxItems": 20, "items": { "type": "string", "minLength": 1 } },
    "excludeGlobs": { "type": "array", "minItems": 1, "maxItems": 20, "items": { "type": "string", "minLength": 1 } },
    "contextLines": { "type": "integer", "minimum": 0, "maximum": 5, "default": 0 },
    "resultStart": { "type": "integer", "minimum": 1, "default": 1 },
    "resultEnd": { "type": "integer", "minimum": 1 }
  },
  "required": ["workspaceId", "query"],
  "additionalProperties": false
}
```

输出：`Collection<SymbolHit>`。按匹配质量、名称、文件和位置稳定排序；成功集合和预期 Provider 失败可携带本次调用的 `ProviderObservation`，不能据此推断长期性能。

### 6.6 `document_symbols`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "workspaceId": { "type": "string", "minLength": 1 },
    "file": { "type": "string", "minLength": 1 },
    "kinds": { "type": "array", "minItems": 1, "uniqueItems": true, "items": { "$ref": "#/$defs/SymbolKind" } },
    "maxDepth": { "type": "integer", "minimum": 0, "maximum": 100 },
    "nameEquals": { "type": "string", "minLength": 1 },
    "pathEquals": { "type": "array", "minItems": 1, "maxItems": 101, "items": { "type": "string", "minLength": 1 } },
    "includeRange": { "type": "boolean", "default": false },
    "contextLines": { "type": "integer", "minimum": 0, "maximum": 5, "default": 0 },
    "resultStart": { "type": "integer", "minimum": 1, "default": 1 },
    "resultEnd": { "type": "integer", "minimum": 1 }
  },
  "required": ["workspaceId", "file"],
  "additionalProperties": false
}
```

输出：`Collection<DocumentSymbol>`。精确名称/路径过滤先于窗口，重复名称全部保留；结果按文档符号树前序排列。`path` 在窗口切片后仍完整表达结构，不返回可推导的名称、深度或父节点 ID。`includeRange: true` 时范围使用 1-based、end-exclusive 坐标；缺失项给出 `provider_range_unavailable`，范围仍须由源码读回验收。集合携带当前 Provider 调用观察。

### 6.7 `symbol_info`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "workspaceId": { "type": "string", "minLength": 1 },
    "file": { "type": "string", "minLength": 1 },
    "line": { "type": "integer", "minimum": 1 },
    "column": { "type": "integer", "minimum": 1 },
    "include": {
      "type": "array",
      "minItems": 1,
      "uniqueItems": true,
      "default": ["definition"],
      "items": { "enum": ["hover", "declaration", "definition", "typeDefinition", "implementation", "signatureHelp"] }
    },
    "includeGlobs": { "type": "array", "minItems": 1, "maxItems": 20, "items": { "type": "string", "minLength": 1 } },
    "excludeGlobs": { "type": "array", "minItems": 1, "maxItems": 20, "items": { "type": "string", "minLength": 1 } },
    "contextLines": { "type": "integer", "minimum": 0, "maximum": 5, "default": 0 },
    "resultStart": { "type": "integer", "minimum": 1, "default": 1 },
    "resultEnd": { "type": "integer", "minimum": 1 }
  },
  "required": ["workspaceId", "file", "line", "column"],
  "additionalProperties": false
}
```

输出：`Collection<SymbolInfoResult>`。只调用 `include` 明确选择的能力；默认只查定义。`includeGlobs` 和 `excludeGlobs` 只过滤带逻辑路径的位置结果，不会隐藏 hover 或 signature help。不同结果使用判别联合，不输出无关空字段。结果按第 4.3 节固定能力顺序分组、组内稳定排序，再对拼接后的单一集合应用窗口。

### 6.8 `get_references`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "workspaceId": { "type": "string", "minLength": 1 },
    "file": { "type": "string", "minLength": 1 },
    "line": { "type": "integer", "minimum": 1 },
    "column": { "type": "integer", "minimum": 1 },
    "includeGlobs": { "type": "array", "minItems": 1, "maxItems": 20, "items": { "type": "string", "minLength": 1 } },
    "excludeGlobs": { "type": "array", "minItems": 1, "maxItems": 20, "items": { "type": "string", "minLength": 1 } },
    "contextLines": { "type": "integer", "minimum": 0, "maximum": 5, "default": 0 },
    "timeoutMs": { "type": "integer", "minimum": 1000, "maximum": 300000 },
    "resultStart": { "type": "integer", "minimum": 1, "default": 1 },
    "resultEnd": { "type": "integer", "minimum": 1 }
  },
  "required": ["workspaceId", "file", "line", "column"],
  "additionalProperties": false
}
```

输出：`Collection<ReferenceHit>`。通常调用 VS Code 公开 Reference Provider 命令，采用其固定包含声明的语义；不对单个结果伪造声明标记。`timeoutMs` 只覆盖本次引用查询，省略时使用扩展的 60,000 毫秒默认值；允许 1,000 至 300,000 毫秒。显式提供 `timeoutMs` 时会把完整预算留给公开 Reference Provider，不先消耗 scoped fallback 预算。C/C++ 在未显式提供 `timeoutMs`、且 `includeGlobs` 带固定目录前缀时，优先执行有界的 scoped identity fallback：只发现范围内的精确标识符 token，并逐个通过 definition/declaration 锚点验证符号身份。只有文件数、文本量、候选数、时间和每个候选的语义验证全部完成时才返回，并附带 `references_scoped_identity_fallback` warning；任一预算或候选身份无法证明时快速返回可恢复错误，不再隐式启动一次昂贵的全工作区 Provider。调用方随后应改用 `verify_symbol_candidates`，或显式提供 `timeoutMs` 请求完整 Provider 枚举。公开 C/C++ references 在超时或取消后会触发一次有界的中断脉冲，并最多等待三秒确认原 Provider promise 已结束；只有真实结束才释放单飞槽，其他 Provider 不支持中断时仍保持保护。

### 6.9 `verify_symbol_candidates`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "workspaceId": { "type": "string", "minLength": 1 },
    "file": { "type": "string", "minLength": 1 },
    "line": { "type": "integer", "minimum": 1 },
    "column": { "type": "integer", "minimum": 1 },
    "candidates": {
      "type": "array",
      "minItems": 1,
      "maxItems": 100,
      "uniqueItems": true,
      "items": {
        "type": "object",
        "properties": {
          "file": { "type": "string", "minLength": 1 },
          "line": { "type": "integer", "minimum": 1 },
          "column": { "type": "integer", "minimum": 1 }
        },
        "required": ["file", "line", "column"],
        "additionalProperties": false
      }
    },
    "timeoutMs": { "type": "integer", "minimum": 1000, "maximum": 300000 }
  },
  "required": ["workspaceId", "file", "line", "column", "candidates"],
  "additionalProperties": false
}
```

输出：`Collection<SymbolCandidateVerification>`，顺序和数量与显式候选输入一致。工具只解析一次目标身份，再逐项核验调用方已通过文本或 AST 收窄的位置；它不会枚举文件，也不证明未提交的位置不存在。`verified` 表示候选解析到同一目标，`mismatched` 表示解析到其他目标，`unresolved` 表示 Provider 未给出可比较身份，`positionOutOfRange` 表示候选位置无效。Provider 整体不可用、失败或超时仍作为工具错误返回，不把未检查项伪装成结果。

### 6.10 `get_call_hierarchy`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "workspaceId": { "type": "string", "minLength": 1 },
    "file": { "type": "string", "minLength": 1 },
    "line": { "type": "integer", "minimum": 1 },
    "column": { "type": "integer", "minimum": 1 },
    "direction": { "enum": ["incoming", "outgoing", "both"], "default": "both" },
    "maxDepth": { "type": "integer", "minimum": 0, "maximum": 5, "default": 1 },
    "resultStart": { "type": "integer", "minimum": 1, "default": 1 },
    "resultEnd": { "type": "integer", "minimum": 1 }
  },
  "required": ["workspaceId", "file", "line", "column"],
  "additionalProperties": false
}
```

输出：`Collection<CallHierarchyEntry>`。按根节点、breadth-first、direction 和位置稳定排列。`parent` 仅在 `depth > 0` 时输出。

### 6.11 `get_type_hierarchy`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "workspaceId": { "type": "string", "minLength": 1 },
    "file": { "type": "string", "minLength": 1 },
    "line": { "type": "integer", "minimum": 1 },
    "column": { "type": "integer", "minimum": 1 },
    "direction": { "enum": ["supertypes", "subtypes", "both"], "default": "both" },
    "maxDepth": { "type": "integer", "minimum": 0, "maximum": 5, "default": 1 },
    "resultStart": { "type": "integer", "minimum": 1, "default": 1 },
    "resultEnd": { "type": "integer", "minimum": 1 }
  },
  "required": ["workspaceId", "file", "line", "column"],
  "additionalProperties": false
}
```

输出：`Collection<TypeHierarchyEntry>`。排序和 parent 规则与调用层级相同。

### 6.12 `get_diagnostics`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "workspaceId": { "type": "string", "minLength": 1 },
    "scope": { "enum": ["files", "modifiedFiles", "workspace"], "default": "modifiedFiles" },
    "files": { "type": "array", "minItems": 1, "maxItems": 200, "uniqueItems": true, "items": { "type": "string", "minLength": 1 } },
    "severities": {
      "type": "array",
      "minItems": 1,
      "uniqueItems": true,
      "default": ["error", "warning", "information", "hint"],
      "items": { "enum": ["error", "warning", "information", "hint"] }
    },
    "sources": { "type": "array", "minItems": 1, "maxItems": 50, "uniqueItems": true, "items": { "type": "string", "minLength": 1 } },
    "includeRelatedInformation": { "type": "boolean", "default": false },
    "resultStart": { "type": "integer", "minimum": 1, "default": 1 },
    "resultEnd": { "type": "integer", "minimum": 1 }
  },
  "required": ["workspaceId"],
  "additionalProperties": false
}
```

输出：`Collection<Diagnostic>`。只返回 VS Code 已发布的诊断；不遍历文件模拟全量语言分析。提供 `files` 且省略 `scope` 时自动使用 `files`；显式使用 `scope: "files"` 时必须提供 `files`，其他 scope 不得同时提供 `files`。跨字段错误由运行时校验返回具体原因，避免依赖客户端对条件 JSON Schema 的支持。

### 6.13 `rename_preview`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "workspaceId": { "type": "string", "minLength": 1 },
    "file": { "type": "string", "minLength": 1 },
    "line": { "type": "integer", "minimum": 1 },
    "column": { "type": "integer", "minimum": 1 },
    "newName": { "type": "string", "minLength": 1, "maxLength": 1000 },
    "timeoutMs": { "type": "integer", "minimum": 1000, "maximum": 300000 },
    "includeGlobs": {
      "type": "array",
      "minItems": 1,
      "maxItems": 20,
      "items": { "type": "string", "minLength": 1 }
    },
    "excludeGlobs": {
      "type": "array",
      "minItems": 1,
      "maxItems": 20,
      "items": { "type": "string", "minLength": 1 }
    }
  },
  "required": ["workspaceId", "file", "line", "column", "newName", "includeGlobs"],
  "additionalProperties": false
}
```

输出：`Preview`。`includeGlobs` 必填，`excludeGlobs` 可选；源文件必须落在声明范围内。`timeoutMs` 可选，范围为 1,000–300,000 ms；省略时使用窗口配置的 Provider 超时（默认 60 秒）。该范围是完整编辑的安全边界，不是结果裁剪器：Provider 只要返回一个范围外目标，整份结果返回 `RENAME_SCOPE_VIOLATION`，不生成 `previewId`、不缓存任何子集，也不得通过放宽范围绕过对每个目标的审查。

Provider edit 规范化后先检查完整路径范围；发现越界文件时直接返回有界的 `RENAME_SCOPE_VIOLATION`，不进入较慢的身份查询，也不缓存预览。范围校验通过后，扩展仍要验证每个 edit：被替换文本必须等于 prepare rename 的目标文本，且该 edit 位置的 definition/declaration 锚点必须非歧义地属于目标锚点集合。对于 definition/declaration 无法解析、但语言 Provider 有意参与重命名的语义字符串位置（例如 Python `__all__`），还必须由目标的一次有界 Reference Provider 结果按文件、行、列精确证明；这不是对普通 unresolved edit 的放行。任一同名异符号、混合锚点、无法解析或无法被引用集合证明、Provider 失败或 30 秒/100 edits 校验预算不足都返回 `RENAME_IDENTITY_UNVERIFIED`，只给出有界原因和计数，不缓存预览。身份 Provider 超时使用 `providerTimedOut` 原因，不再误报为普通 rename Provider 超时。引用证明最多接收 200 个位置。零有效编辑返回 `RENAME_NO_EDITS`，不得以 `ok: true, changes: []` 表示成功。

完整预览最多包含 50 个变更文件、100 个编辑、50,000 个 `oldText + newText` UTF-16 code unit，最终 YAML 工具响应最多 65,536 个 UTF-8 字节。任一预算超限返回仅含计数的 `PREVIEW_TOO_LARGE`；`serializedBytes` 是按真实 YAML 编码器和等长占位 `previewId` 计算的最终响应字节数，不是内部 JSON 大小。不得把截断结果标为可 apply。完整版本和哈希快照保存在内部缓存，不传给 LLM。Provider edit 不能由公共 API 完整枚举为 text-only 时返回 `EDIT_CONFLICT/unsupportedEdit`，不得应用原始 WorkspaceEdit。

### 6.14 `rename_apply`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "previewId": { "type": "string", "minLength": 1 }
  },
  "required": ["previewId"],
  "additionalProperties": false
}
```

输出：`ApplyResult`。调用 apply 本身就是确认，不额外要求 `confirm: true`。`previewId` 已绑定工作区，工具只能应用缓存中的完整预览，不能重复提交 workspace 或 rename 参数。

### 6.15 `code_actions`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "workspaceId": { "type": "string", "minLength": 1 },
    "file": { "type": "string", "minLength": 1 },
    "range": { "$ref": "#/$defs/Range" },
    "onlyKinds": { "type": "array", "minItems": 1, "maxItems": 50, "uniqueItems": true, "items": { "type": "string", "minLength": 1 } },
    "resultStart": { "type": "integer", "minimum": 1, "default": 1 },
    "resultEnd": { "type": "integer", "minimum": 1 }
  },
  "required": ["workspaceId", "file", "range"],
  "additionalProperties": false
}
```

输出：`CodeActionSet`。服务端只返回已经解析并缓存为完整 text-only edit 的 Action，不向 LLM 暴露 `itemResolveCount` 等 Provider 调优参数。

### 6.16 `code_action_preview`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "actionSetId": { "type": "string", "minLength": 1 },
    "actionId": { "type": "string", "minLength": 1 }
  },
  "required": ["actionSetId", "actionId"],
  "additionalProperties": false
}
```

输出：`Preview`。只使用 actionSet 中缓存的已解析 text edit，不重新调用 Provider 取得另一批编辑。若候选缓存完整性或最终安全归一化失败，返回 `ACTION_NOT_PREVIEWABLE` 并要求重新获取候选；文档快照变化返回 `DOCUMENT_CHANGED`。

### 6.17 `code_action_apply`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "previewId": { "type": "string", "minLength": 1 }
  },
  "required": ["previewId"],
  "additionalProperties": false
}
```

输出：`ApplyResult`。预览校验和一次性消费规则与 `rename_apply` 相同。

### 6.18 `format_preview`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "workspaceId": { "type": "string", "minLength": 1 },
    "file": { "type": "string", "minLength": 1 },
    "range": { "$ref": "#/$defs/Range" },
    "options": {
      "type": "object",
      "minProperties": 1,
      "properties": {
        "tabSize": { "type": "integer", "minimum": 1, "maximum": 32 },
        "insertSpaces": { "type": "boolean" }
      },
      "additionalProperties": false
    }
  },
  "required": ["workspaceId", "file"],
  "additionalProperties": false
}
```

输出：`Preview`。省略 `range` 时格式化文档；提供 `range` 时格式化范围。省略 options 时使用目标文档的有效配置。

### 6.19 `format_apply`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "previewId": { "type": "string", "minLength": 1 }
  },
  "required": ["previewId"],
  "additionalProperties": false
}
```

输出：`ApplyResult`。预览校验和一次性消费规则与 `rename_apply` 相同。

### 6.20 `execute_command`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "workspaceId": { "type": "string", "minLength": 1 },
    "target": {
      "oneOf": [
        {
          "type": "object",
          "properties": {
            "kind": { "const": "command" },
            "commandId": { "type": "string", "minLength": 1 },
            "arguments": { "type": "array", "default": [], "items": true }
          },
          "required": ["kind", "commandId"],
          "additionalProperties": false
        },
        {
          "type": "object",
          "properties": {
            "kind": { "const": "task" },
            "taskName": { "type": "string", "minLength": 1 },
            "taskRoot": { "type": "string", "minLength": 1 }
          },
          "required": ["kind", "taskName"],
          "additionalProperties": false
        }
      ]
    },
    "saveBeforeRun": { "enum": ["none", "active", "all"], "default": "none" },
    "timeoutMs": { "type": "integer", "minimum": 1000, "maximum": 600000, "default": 120000 },
    "maxOutputChars": { "type": "integer", "minimum": 1000, "maximum": 200000, "default": 20000 },
    "retainOutputLog": { "type": "boolean", "default": false }
  },
  "required": ["workspaceId", "target"],
  "additionalProperties": false
}
```

输出：`CommandResult`。无交互是工具自身不可关闭的安全约束，不要求 LLM 重复传 `nonInteractive: true`。

- 可信工作区默认允许参数为空的保存、调试控制、窗口/Extension Host 重载，以及已发现的前台 ProcessExecution/ShellExecution task；不要求逐项白名单。
- 自定义 command 仍须精确授权。可用 `allowStandardCommands=false` 或 `allowWorkspaceTasks=false` 收紧默认权限，再用精确条目选择性授权。
- workspace 未受信任时拒绝，避免 VS Code 在 task/command 路径弹出 trust prompt。
- task、依赖 task 或参数中出现 `${input:...}` 时执行前拒绝；`${command:...}` 变量因完成和交互性不可证明也拒绝。
- 已知会打开 InputBox、QuickPick、文件选择器、认证窗口或确认框的命令执行前拒绝。
- 窗口和 Extension Host 重载会先返回“已接受并调度”，再延迟触发，以免 Bridge 先断开导致调用端误判；随后须重新 `list_workspaces`。退出 VS Code、禁用/卸载 companion 和主动断开 Bridge 仍硬拒绝。
- command 必须等待内建策略或自定义授权声明的完成 promise；task 只允许可解析的非 background `ProcessExecution`/`ShellExecution`，并同时等待对应 TaskExecution 的 process-end 与 task-end。
- 除上述重载调度外，只有确认实际完成且成功时返回 `ok: true`；超时、取消、非零退出或只能确认“已发起”时返回错误。
- `saveBeforeRun=active/all` 只保存所选 workspace 内的 `file:` dirty TextDocument；不触碰 untitled、非 file 或其它 workspace 文档。任一 save 返回 false 时不启动 target，但此前已完成的 save 不回滚。
- `maxOutputChars` 只约束 command 返回值。task 成功省略 output，并仅在 `retainOutputLog=true` 时返回 `data.outputLog`；失败时可返回 `error.details.outputLog`。正文不进入 MCP 响应。Windows 上无依赖的 `ProcessExecution` 使用受控 tee wrapper；日志为 UTF-8、单文件最多 64 MiB、每 root 最多保留 10 份。ShellExecution、依赖图、非 Windows 或启动前失败不伪造日志。

## 7. 输出和缓存边界

- `content[].text` 是精简 DTO 唯一公开的 YAML 表示，不添加 Markdown 表格或解释段落。
- 服务端内部保留规范化 JSON 对象和输出 Schema 校验，但不把 `structuredContent` 送入 MCP 调用结果。
- 公共 DTO 不包含内部路径、URI、文档哈希、版本快照、Provider 对象或 IPC 数据。
- Preview 缓存保存重建后的完整 text-only edit、文档 epoch/version、内存内容 hash、磁盘 byte hash 和工作区边界信息；删除公开字段不降低 apply 校验强度。
- rename 的 glob 门禁与输出预算都在 cache commit 前执行；失败结果没有 `previewId`，也不存在可被后续 apply 取得的部分缓存。
- `previewId` 和 `actionSetId` 使用全局不可预测随机值并绑定工作区与客户端会话；后续工具不重复接收 `workspaceId`。
- preview active TTL 为 300 秒；每会话最多 64 个、每 workspace 最多 16 个。actionSet TTL 为 120 秒；每会话最多 32 个、每 workspace 最多 8 个。两类 payload 合计 64 MiB，先清理过期再按创建时间淘汰最旧 active entry；淘汰后按 not-found 处理。
- preview apply 采用原子 claim 和一次性消费；成功、验证失败或已发出 apply 后结果未知都消费。仅在 workspace 连接失败且尚未 claim 时保留 active preview。
- actionSet 中每个 actionId 最多 claim 一次；同一 set 的其它 action 在源快照不变时仍可 preview。任一快照变化使整个 set 失效。
- 空可选字段不序列化；必填字段不得通过 `null` 占位。
- 多行源码、Markdown、oldText/newText 和命令输出使用 YAML block scalar。
- 禁止 YAML tag、anchor、alias、merge key 和重复键。

## 8. 实现验收

- `tools/list` 返回 19 个工具，名称、description、annotations 和 inputSchema 与本文一致，并且不包含 outputSchema。
- 所有输入拒绝未知字段；所有输出拒绝未在对应判别联合中的字段。
- 19 份 inputSchema 和 19 份内部输出 Schema分别通过 Draft 2020-12 校验；公共 `$defs` 生成源也必须通过自身校验并成功内联。
- 每份内部输出 Schema 根显式为 `type: object`，成功和失败 DTO 在 YAML 序列化前通过对应联合 envelope 校验。
- 每个 `tools/call` 响应只包含一份 YAML TextContent，不包含 structuredContent。
- 默认窗口为 20，最大窗口为 100；覆盖单边窗口、空窗口、逆序和越界测试。
- 正常响应不包含无意义的 `null`、`false`、空数组、空字符串或内部元数据。
- Provider 身份、引用声明标记、诊断 ID 和内部层级 item ID 不出现在公开结果中。
- 三组 preview/apply 覆盖过期、重复 apply、文档变化、越界文件和编辑冲突。
- 删除公开版本与哈希字段后，apply 仍使用服务端缓存执行相同强度的版本和内容校验。
- `execute_command` 覆盖默认/收紧策略、`${input:...}`、已知交互命令、task 非零退出、重载调度、超时和真实完成状态。
