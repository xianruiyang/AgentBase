# VS Code LSP MCP Companion 方案

## 1. 目标

建立一个独立、开源、可与现有 `vscode-mcp` 并存的 VS Code LSP MCP 组件。组件复用 VS Code 已激活的语言扩展和 Provider，不自行实现 clangd、Roslyn、Pylance、rust-analyzer 等语言服务器。

核心目标：

- 通过标准 MCP 向 Codex 等外部客户端提供稳定的代码语义能力。
- 优先使用 `file + line + column` 定位符号，减少名称搜索和 `codeSnippet` 消歧。
- 补全工作区符号、文档符号、调用层级、类型层级、Code Action 和安全重命名。
- 所有语义写操作采用 `preview -> apply`，并校验文档版本或内容哈希。
- 控制结果数量和上下文体积，适合 LLM 使用。
- MCP 协议和内部机器通道使用严格 JSON，面向 LLM 的返回正文统一使用 YAML。
- 保留无交互 VS Code command/task 执行能力。
- 只维护 Windows 宿主与 Windows 原生发布链。

## 2. 非目标

- 不修改或 fork 当前第三方 `vscode-mcp`。
- 不替代 `simplechat-ast`；AST 仍负责代码形状搜索和结构化改写。
- 不重新实现语言服务器，也不直接绑定某一种语言。
- 不通过鼠标、键盘、Quick Pick 或 Input Box 自动化 VS Code UI。
- 不保证语言扩展未实现的 LSP capability 可以被补造出来。
- 第一阶段不提供调试器、终端、源代码管理和编辑器 UI 自动化。

## 3. 总体架构

```text
Codex / MCP Client
        |
        | MCP stdio
        v
External MCP Server
  - tool schemas
  - workspace routing
  - result windows / limits
  - preview sessions
  - safety validation
  - YAML text response encoding
        |
        | authenticated local IPC
        v
VS Code Companion Extension
  - document activation
  - Provider Command adapters
  - diagnostics access
  - WorkspaceEdit serialization
  - command/task policy
        |
        | VS Code Language APIs
        v
Installed Language Extensions / Language Servers
```

选择双组件架构的原因：

- VS Code Extension Host 才能调用 `vscode.commands` 和 `vscode.languages`。
- Codex 更适合通过独立 stdio MCP Server 建立稳定连接。
- 插件重载与 MCP Server 生命周期解耦，便于自动恢复。
- 可以在 MCP 层统一限制输出、缓存预览并实施安全策略。

## 4. 计划目录

```text
vscode-lsp-mcp/
├── PLAN.md
├── MCP_TOOL_SCHEMAS.md # 工具名、输入/输出 Schema、错误码和默认值的规范源
├── package.json
├── package-lock.json
├── packages/
│   ├── protocol/       # IPC 消息、公共类型、序列化格式
│   ├── extension/      # VS Code Companion 插件
│   ├── server/         # 外部 stdio MCP Server
│   └── win32-security/ # Windows Named Pipe/DACL 最小 Node-API 适配器
├── scripts/            # 安装、卸载、doctor、VSIX 打包
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
└── dist/               # 构建产物，不提交临时输出
```

业务与协议实现使用 TypeScript，采用 npm workspaces。`packages/win32-security` 中基于稳定 Node-API ABI 的可审计 Windows 原生适配器只负责创建带显式 DACL 和 `PIPE_REJECT_REMOTE_CLIENTS` 的 Named Pipe、异步收发原始字节以及创建/校验运行时目录 ACL，不解析业务协议。MCP Server 使用官方 MCP SDK；VS Code 插件仅使用公开 Extension API 和公开内置 Provider Commands；公共 protocol 包集中封装稳定 DTO、严格 JSON 机器传输和 YAML 文本输出。

## 5. 工作区发现与 IPC

### 5.1 工作区标识

- 每次 Extension Host 激活生成随机 UUIDv4 `instanceId`；每个可登记工作区另生成独立的 128-bit 随机 `workspaceId`，使用 `ws_` 加无填充 base64url 编码，且不得取保留字 `server`。路径、窗口标题和 PID 都不参与 ID 生成；同一路径被两个窗口打开时必须得到不同 ID。
- 工作区 folder 集合、顺序或 alias 发生变化时递增内部 `workspaceGeneration`，撤销旧登记并生成新的 `workspaceId`；旧路由不得继续落到变化后的根集合。
- root alias 从 `WorkspaceFolder.name` 生成小写 ASCII slug，仅保留 `a-z0-9._-`；其他连续字符折叠为 `-`，空结果使用 `root`。同名根追加 `~` 和规范根比较键的 SHA-256 前 8 位，仍冲突时每次增加 2 位，直到在当前工作区唯一。alias 比较始终区分大小写且不受宿主文件系统规则影响。
- MCP 对外只返回 `workspaceId`、工作区名称和 alias 列表。单根工作区的 `file` 为 `relative/path`，多根工作区为 `rootAlias/relative/path`；单根也返回一个 alias，但输入输出路径不得带该前缀。
- 第一版只把与 MCP Server 同一 OS 用户、同一文件系统命名空间且所有根均为 `file:` URI 的 folder workspace 标记为可用。无 folder、虚拟 URI 或跨主机 Extension Host 不进入 `list_workspaces`；若实例在同一运行时目录可发现，则以 `health_check: unavailable` 和 doctor 原因报告。
- 内部登记规范根、工作区 folder、VS Code 版本和远程类型；绝对路径、URI、实例 ID、PID 和端点不进入日常 MCP DTO。

公开命名空间冻结如下，避免与既有 `vscode-mcp` 4.9.2 冲突：

| 用途 | 冻结值 |
|---|---|
| MCP 配置名与 server bin | `vscode-lsp-mcp` |
| VS Code 扩展 ID | `simplechat.vscode-lsp-mcp-companion` |
| VS Code command/config 前缀 | `vscodeLspMcp` |
| 根 npm package | `simplechat-vscode-lsp-mcp`（private） |
| workspace packages | `@simplechat/vscode-lsp-mcp-protocol`、`@simplechat/vscode-lsp-mcp-extension`、`@simplechat/vscode-lsp-mcp-server`、`@simplechat/vscode-lsp-mcp-win32-security`（均 private） |
| 运行时目录/记录前缀 | `vscode-lsp-mcp` |
| Windows pipe 前缀 | `\\.\pipe\vscode-lsp-mcp-` |

### 5.2 本地传输

- 本地传输使用 `\\.\pipe\vscode-lsp-mcp-<userScopeHash>-<instanceId>` Named Pipe，运行时根使用 `%LOCALAPPDATA%\vscode-lsp-mcp\run`；目录与记录必须通过 Windows ACL 校验，不能因为目录“可写”就接受。
- 每帧为 4-byte unsigned big-endian 长度加 UTF-8 JSON object；长度必须为 `1..16777216`，UTF-8 必须可严格解码，JSON 必须拒绝重复键和未知判别字段。换行不参与分帧。
- 连接首帧必须是 `hello`，包含精确协议版本、`instanceId`、`workspaceId`、256-bit 随机 base64url token 和客户端 nonce；响应 `helloAck` 必须回显身份与 nonce，但不得回显 token。比较 token 使用恒定时间逻辑，失败立即关闭连接且不向公开响应泄露原因。
- 插件以同目录临时文件、flush、原子 rename 发布判别联合注册记录。可用记录包含协议版本、实例/工作区/代次、Extension Host PID 与启动指纹、端点、token、alias/规范根、VS Code 版本和 `updatedAt`；不可用记录只保留身份、心跳和清理后的 reason code。正常 MCP 响应不得透传这些字段。
- 心跳间隔 10 秒，60 秒未更新即成为 stale candidate 并从 `list_workspaces` 排除。握手成功是存活真源；PID/启动指纹只用于避免 PID 复用误判。握手失败且进程指纹失效时立即删除记录；否则隔离，连续 5 分钟无有效心跳与握手后仅删除失效记录，绝不终止进程。
- MCP Server 在每次 workspace 列举/路由前扫描注册目录，并用目录 watcher 加防抖优化；断线后重新发现，采用有限退避。断线中的请求返回 `WORKSPACE_DISCONNECTED`；只读调用可由调用方显式重试，preview/apply 和 command 不得静默重放。

### 5.3 安全边界

- Windows 运行时目录和记录使用受保护 DACL，只授权当前用户 SID 与 `SYSTEM`；Named Pipe 使用同一 DACL 并设置 `PIPE_REJECT_REMOTE_CLIENTS`。
- Node/libuv 默认 Named Pipe 创建路径不会传入上述显式安全描述符，也不会设置拒绝远程客户端标志，因此 Windows 服务端必须使用随组件构建的 `win32-security` Node-API 适配器；MCP Server 客户端仍可使用 `node:net` 连接。适配器、ACL 验证或架构匹配失败时关闭该实例并报告 unavailable；不得把服务端降级为普通 `node:net` Named Pipe，也不得把随机名称或握手 token 当作 OS 访问控制的替代品。
- 公共逻辑路径只接受 `/` 分隔的相对路径，拒绝空路径、首尾 `/`、`//`、`.`/`..` 段、反斜杠、NUL/控制字符、URI/绝对路径、drive/UNC、ADS `:`、设备名和尾随点/空格。语法错误映射 `INVALID_ARGUMENT`，多根未知 alias 映射 `ROOT_NOT_FOUND`。
- 双端使用同一 protocol 路径库执行：逻辑路径解析 -> alias 精确查找 -> 根 URI -> lexical absolute -> `realpath.native`（不存在目标则取最近存在父目录）-> Windows 大小写不敏感比较键 -> 组件边界归属。归属判断必须使用路径组件/`relative` 结果，不得用字符串前缀。
- 根本身可为 symlink，但登记时即固定其规范真实路径。目标 symlink/junction 只有在解析后仍位于所选根内时才允许；即使逃逸目标落入另一个 workspace root，也必须以 `PATH_OUTSIDE_WORKSPACE` 拒绝，不能跨 alias 接受。新建目标校验最近存在父目录，并在 apply 前由 Extension 再校验一次。
- MCP Server 的校验是早期拒绝，Extension 的校验是权威边界；两侧任何不一致都按更严格结果失败。Provider 返回的工作区外只读位置从候选集中丢弃并给出清理后的 warning；任何写入候选只要含一个越界位置，整个 preview/apply 以 `PATH_OUTSIDE_WORKSPACE` 拒绝。
- 物理位置反向映射到嵌套 roots 时选择规范路径最长的最具体根，相同长度再按 alias 字典序；找不到归属时不得返回绝对路径或 URI。

## 6. VS Code Provider 映射

插件优先调用下列公开能力：

| MCP 能力 | VS Code Provider/API |
|---|---|
| 工作区符号 | `vscode.executeWorkspaceSymbolProvider` |
| 文档符号 | `vscode.executeDocumentSymbolProvider` |
| 声明 | `vscode.executeDeclarationProvider` |
| 定义 | `vscode.executeDefinitionProvider` |
| 类型定义 | `vscode.executeTypeDefinitionProvider` |
| 实现 | `vscode.executeImplementationProvider` |
| Hover | `vscode.executeHoverProvider` |
| 签名 | `vscode.executeSignatureHelpProvider` |
| 引用 | `vscode.executeReferenceProvider` |
| 调用层级 | `vscode.prepareCallHierarchy`、incoming/outgoing providers |
| 类型层级 | `vscode.prepareTypeHierarchy`、super/subtype providers |
| 重命名 | `vscode.prepareRename`、`vscode.executeDocumentRenameProvider` |
| Code Action | `vscode.executeCodeActionProvider` |
| 格式化 | format document/range providers |
| 诊断 | `vscode.languages.getDiagnostics` |

调用前通过 `openTextDocument` 激活目标语言扩展，但默认不显示编辑器 UI。

## 7. MCP 工具设计

工具数量保持克制，优先让单个工具通过枚举参数覆盖同类只读操作。

公开工具的字段、默认值、错误码、annotations、`inputSchema` 和内部输出校验以 [MCP_TOOL_SCHEMAS.md](./MCP_TOOL_SCHEMAS.md) 为准；本节只保留能力范围概览，避免重复维护 Schema。

### 7.1 基础工具

| 工具 | 用途 |
|---|---|
| `list_workspaces` | 列出已连接 VS Code 实例和工作区 |
| `health_check` | 检查 Bridge、版本、IPC 和语言文档激活状态 |
| `get_capabilities` | 返回插件能力和目标文档可探测的 Provider 状态 |

`get_capabilities` 对无法可靠判断的能力返回 `unknown`，不把空结果误判为不支持。

### 7.2 只读语义工具

| 工具 | 用途 |
|---|---|
| `workspace_symbols` | 按名称搜索工作区符号，支持 kind、路径和结果区间 |
| `document_symbols` | 获取文件结构和符号层级 |
| `symbol_info` | 按位置获取 hover、声明、定义、类型、实现和签名 |
| `get_references` | 获取真实引用，支持结果区间和可选上下文 |
| `get_call_hierarchy` | 获取 incoming、outgoing 或两者 |
| `get_type_hierarchy` | 获取 supertypes、subtypes 或两者 |
| `get_diagnostics` | 查询指定文件、修改文件或工作区诊断 |

位置参数对 MCP 使用 1-based `line`、`column`，其中 `column` 以 UTF-16 code unit 计数、Range end exclusive；插件内部统一转换为同一文档快照上的 VS Code 0-based `Position`，禁止跨快照或与 byte/code-point/grapheme offset 直接比较。

### 7.3 安全写工具

| 工具 | 用途 |
|---|---|
| `rename_preview` | 执行 prepare rename 并返回规范化 text changes 和预览 ID |
| `rename_apply` | 使用预览 ID 应用已确认且未过期的重命名 |
| `code_actions` | 只列出能安全解析为完整 text-only WorkspaceEdit 的 Code Action |
| `code_action_preview` | 从已缓存候选生成可安全预览的 text changes |
| `code_action_apply` | 应用已确认且版本一致的 Code Action |
| `format_preview` | 返回格式化 TextEdit，不立即写文件 |
| `format_apply` | 应用已确认的格式化预览 |

所有 apply 工具只接受 preview ID，不重新计算并静默应用另一批编辑。

第一版的可安全应用子集固定为 VS Code 公共 `WorkspaceEdit.entries()` 可枚举的 text edit。先要求 `WorkspaceEdit.size === WorkspaceEdit.entries().length` 作为保守筛选，随后仍只把公开展示的 edits 重建为新的 text-only WorkspaceEdit；Provider 原始 WorkspaceEdit 绝不直接 apply。资源 create/rename/delete、SnippetTextEdit 和 Code Action command 因公共 API 无法完整枚举并复现为同一可审查操作而拒绝或从 Action 候选中过滤。

### 7.4 VS Code 指令

保留 `execute_command`，但与 LSP 工具分开：

- 默认 allowlist 为空；command entry 必须声明 exact command ID、闭合 argument Schema、无交互和 promise 完成语义，task entry 以 root alias + task name 唯一标识。
- workspace 未受信任、task/依赖中的 `${input:...}`、`${command:...}`、已知 InputBox/QuickPick/文件选择/认证/确认交互都在执行前拒绝。
- 重载/关闭窗口、重启 Extension Host、禁用或卸载 companion、退出 VS Code 和主动断开 Bridge 第一版硬拒绝，allowlist 不可覆盖。
- command 参数作为结构化 JSON 传递；没有 argument Schema 时只允许空 arguments。标记为逻辑路径的字段先走 P0-003 路径转换，不拼接命令字符串。
- command 只有 allowlist 已证明其返回 promise 代表真实完成时才允许；promise 只代表“已发起”的命令返回 `COMMAND_FAILED/completionUnverifiable`。
- task 只允许非 background 的 `ProcessExecution`/`ShellExecution`；整个依赖 DAG 必须唯一、无环、全部 allowlisted 且无输入变量。成功要求每个 TaskExecution 同时观察到 process-end exit code 0 和 task-end；CustomExecution、未知 exit code 或仅有 start event 均不算完成。
- 受控 task 可以由 VS Code 在 integrated terminal 承载，但组件不创建通用 terminal 会话、不发送输入、不读取 terminal buffer，也不改用 shell integration 执行任意命令。
- `saveBeforeRun` 只处理所选 workspace 内的 dirty `file:` TextDocument；不触碰 untitled、其它 scheme 或其它 workspace。部分 save 后失败不回滚，但 target 不启动。
- command string 结果按 `maxOutputChars` 截断；task 成功返回空 CommandResult。Windows 无依赖 ProcessExecution 失败时由受控 tee wrapper 留存有界日志并返回逻辑路径元数据，不把正文注入 MCP 响应。
- 超时或取消后只有 task 可以请求 terminate；command promise 无通用取消能力。结果未知时保持 workspace mutation gate，直到实际 promise settle 或 Extension Host 重启，并禁止调用方把失败响应当成可安全重试。

### 7.5 多结果窗口

所有返回独立候选集合的工具统一支持：

| 参数 | 含义 |
|---|---|
| `resultStart` | 第一个显示结果的 1-based 序号，默认 `1` |
| `resultEnd` | 最后一个显示结果的 1-based 序号，包含该项 |

默认与校验规则：

- 两个参数都不填时显示第 `1..20` 项。
- 只填 `resultStart` 时，默认从该项开始显示 20 项。
- 只填 `resultEnd` 时，从第 1 项开始显示到 `resultEnd`。
- `resultStart` 和 `resultEnd` 必须为正整数，且 `resultEnd >= resultStart`。
- 单次结果窗口最大 100 项；超过时返回参数错误，不静默截断。
- `resultStart` 超过可用数量时返回空 `results` 和 `available` 数量，不把它当成工具失败。
- 去重和稳定排序必须在截取区间前完成，保证“第 a 到第 b 项”含义稳定。

此规则适用于 workspace/document symbols、定义、类型定义、实现、Hover Provider 结果、签名候选、引用、调用/类型层级、诊断、Code Action、health/capability 以及 workspace 列表等第一版已注册工具返回的独立候选集合。MCP completion 不属于本组件第一版公开工具。

WorkspaceEdit 和 TextEdit 中共同组成一次操作的编辑列表不是候选结果，不得按 `resultStart/resultEnd` 切片。Preview 返回可审查的完整变更；Apply 始终应用服务端缓存的完整编辑集。

## 8. YAML 文本输出契约

- MCP JSON-RPC、输入 Schema、参数和内部 IPC 使用严格 JSON。
- `content[].text` 使用 UTF-8 YAML，不混入 Markdown 表格或解释段落，并且是唯一进入模型上下文的完整结果。
- 服务端内部 JSON DTO 与 YAML 由同一精简 DTO 生成，字段定义只在 [MCP_TOOL_SCHEMAS.md](./MCP_TOOL_SCHEMAS.md) 维护。
- `tools/list` 不公开 `outputSchema`，`tools/call` 不返回 `structuredContent`，避免同一结果以 YAML 和 JSON 重复占用上下文。
- 日常结果不暴露绝对路径、URI、Provider 身份、文档哈希、版本快照和 IPC 信息。
- 空可选字段不序列化；源码位置只返回完成下一步所需的逻辑路径、行和列。
- 多行源码、Markdown 和命令输出使用 YAML block scalar；禁止 tags、anchors、aliases 和重复键。
- 工具失败同时返回精简 error DTO 并设置 MCP `isError`，不能只在正文描述失败。

## 9. Preview/Apply 一致性

### 9.1 文本坐标与规范化

- 公共位置是 1-based line/UTF-16 column；VS Code Range 是 0-based UTF-16；end exclusive。所有 Range 必须绑定生成它的 document epoch/version/content hash，不能跨快照直接比较。
- 验证统一转换到该快照的 0-based UTF-16 half-open offsets。`oldText` 必须是同一快照 `[start,end)` 的精确内容；VS Code 会调整越界 Position/Range，本组件在调用前比较 validate 结果并拒绝任何被调整的范围。
- 非空区间重叠、插入点位于非空区间内部、未知 edit 类型都返回 `EDIT_CONFLICT`。相邻区间合法；同一点多个插入合法并保持 Provider 原始插入顺序。
- TextChange 按逻辑文件稳定排序；文件内按 range 排序，同位置插入以原始序号打破平局。Apply 重建的新 WorkspaceEdit 与公开 Preview 使用同一规范序列。

### 9.2 快照

每次非空预览保存：

- 随机 `previewId`、monotonic 创建/过期时间、MCP client session。
- `workspaceId + workspaceGeneration`、操作类型、请求摘要和目标逻辑路径。
- 每个目标的 internal URI、document epoch、VS Code version、`getText()` UTF-8 SHA-256、EOL/encoding，以及 `file:` 资源的磁盘 byte SHA-256。
- P0-003 canonical root/realpath boundary fingerprint。
- 规范化 text edits、每个文件 expected post-content hash 和 Extension apply-attempt 去重 ID。

同一 document epoch 内 version 与内存 hash 都必须匹配；document reopen 使 version 不再可比时，内存 hash 和磁盘 hash 必须都匹配。任何内容、version、存在性或工作区 identity 变化都返回 `DOCUMENT_CHANGED`，越界变化优先返回 `PATH_OUTSIDE_WORKSPACE`。

### 9.3 Preview 与 actionSet 生命周期

- preview TTL 300 秒；每 client 最多 64 个、每 workspace 16 个。actionSet TTL 120 秒；每 client 最多 32 个、每 workspace 8 个。合计缓存 charge 64 MiB，先清过期再按 createdAt 淘汰最旧 active entry。
- ID 为至少 128-bit CSPRNG base64url，绑定 server-side client session；跨 client 查询与不存在相同处理。
- apply 先做 route preflight，再原子 claim `active -> applying`。claim 后无论成功、校验失败、API false 或结果未知都进入 consumed tombstone；并发/重复 apply 返回 `PREVIEW_NOT_FOUND`。只有 claim 前连接失败才保留 active preview。
- preview 过期在 tombstone 保留期返回 `PREVIEW_EXPIRED`；消费/淘汰/跨 client 返回 `PREVIEW_NOT_FOUND`。空 changes 不创建 preview。
- code_actions 在返回前解析并缓存每个公开 action 的完整 text-only edit。每个 actionId 只可 claim 一次，同 set 其它候选在源快照不变时仍可 preview；任一快照变化使整个 set 失效。preview 不重新调用 Provider 获取另一批 edits。

### 9.4 Apply、原子性与 readback

1. MCP Server preflight route 后 claim preview；Extension 获取 workspace-wide mutation gate，再执行身份、路径、快照和 Range 的最终复核。
2. Extension 只用缓存的规范 edits 构造一个新的 text-only WorkspaceEdit，并用唯一 applyAttemptId 防止 IPC 重复投递。
3. 只调用一次 `workspace.applyEdit`。VS Code 公共契约对纯 text edits 使用 all-or-nothing；本组件第一版不提交资源操作，因此不承诺或伪造逐文件部分状态。
4. API 返回 true 后读回所有目标，必须全部匹配 expected post-content hash 才返回成功。`changedFiles` 是这些目标逻辑路径的稳定去重列表；apply 不自动 save，成功只表示 VS Code document model 已变更。
5. API false 返回 `APPLY_FAILED/apply/notApplied`；true 但 readback 不符返回 `APPLY_FAILED/readback/postconditionFailed`。两者都不返回 changedFiles。
6. apply request 发出后连接中断返回 `WORKSPACE_DISCONNECTED/apply/unknown` 且 `retryable=false`；不得用同一 previewId 重放。claim 前断开为 `preflight/notStarted`，preview 保留且允许显式重试。

因此 ISSUE-004 的结论是：删除旧稿“失败时报告已应用/未应用文件”的要求。只有完整 text-only apply 且 readback 全部通过才输出 `changedFiles`；任何失败只输出可证明的整体 outcome。

## 10. 激活与能力判定

- 查询文件前先打开 TextDocument，以触发语言扩展激活。
- 等待 Provider 就绪采用有上限的轮询和取消信号，不无限重试。
- 空结果不等于 Provider 不存在；能力状态区分 `available`、`unavailable`、`unknown` 和 `timed_out`。
- 每次结果记录实际调用的 Provider command 和耗时，调试日志写入文件而非 MCP 正常输出。
- 语言扩展崩溃或重启后，已有 MCP Server 自动重新发现插件实例。

## 11. 测试方案

### 11.1 单元测试

- 单根/多根逻辑路径、alias 碰撞、nested roots、Windows 大小写/分隔符和 root identity 轮换。
- realpath、root/target symlink、Windows junction、create parent 和 Provider 返回越界位置。
- VS Code 类型到面向 LLM 的精简 DTO、严格 JSON 和 YAML 正文的序列化。
- YAML 正文可安全解析，并与序列化前通过内部输出 Schema 校验的 JSON DTO 语义一致。
- YAML 多行 block scalar、歧义标量引号、禁用 tags/anchors/aliases 和重复键。
- IPC 严格 JSON 长度分帧能处理多行文本、Unicode 和大消息。
- `resultStart/resultEnd` 默认 20 项、最大 100 项、边界和空区间校验。
- 多结果去重、稳定排序、截取顺序和 `available` 数量。
- text-only WorkspaceEdit 作为一个整体，不受结果窗口切片影响。
- WorkspaceEdit 规范化、重叠编辑检测和 preview 过期。
- UTF-16 line/column 与 snapshot offset 转换、同位置插入顺序、越界不静默 clamp。
- preview/actionSet 的 client binding、TTL、容量淘汰、原子 claim、重复 apply 和 apply outcome unknown。
- 命令白名单、workspace trust、`${input:...}` / `${command:...}`、hard deny 和闭合 argument Schema。
- Process/Shell task DAG、非零 exit、background/custom 拒绝、timeout terminate 与 command 不可取消状态。
- IPC 注册清理、随机令牌、严格 hello、stale lease 和 comparison-and-delete。
- Windows Named Pipe DACL、普通第二用户拒绝、远程客户端拒绝，以及 Node-API adapter 失败时无不安全降级。

### 11.2 Extension Host 集成测试

- 使用 VS Code Extension Test Runner 启动隔离实例。
- 以 VS Code 内置 TypeScript 支持验证 definition、references、symbols、rename preview 和 diagnostics。
- 验证插件激活前后、文件未显示、文件有未保存修改时的结果一致性。
- 验证调用层级、类型层级和 Code Action 对不支持 Provider 的降级结果。

### 11.3 MCP 集成测试

- 启动真实 stdio MCP Server 并完成 initialize/listTools/callTool。
- 同时启动多个 VS Code workspace，验证 workspace ID 路由。
- 重启 VS Code、重载插件和清理失效管道后验证自动恢复。
- 大量引用结果必须按请求区间返回，不能一次输出完整仓库内容。
- preview 后修改文件，apply 必须拒绝。
- apply false、readback mismatch 和 dispatch 后断线均不得返回 changedFiles 或自动重放。
- Code Action 的 command、resource operation、SnippetTextEdit 不进入安全候选。
- 交互 task 必须在出现 UI 前被拒绝。
- task 成功由 process-end exit 0 + task-end 共同证明；失败输出仅来自已包装的当前 ProcessExecution，无法安全捕获时不得抓取其它终端或伪造 stdout。

### 11.4 语言验收

- TypeScript/JavaScript 作为自动化基线。
- C/C++ 使用 clangd 或 C/C++ 扩展做 Windows 手工验收。
- C# 使用已安装的 C# 语言扩展做 Windows 手工验收。
- 语言能力缺失时返回明确降级信息，不伪造成功。

## 12. 实施阶段

### 阶段 A：骨架与连接

- 建立 npm workspace、公共协议、插件和 MCP Server。
- 实现实例注册、Named Pipe、workspace discovery 和 health check。
- 完成多工作区与 Windows 路径测试。

验收：Codex 能稳定列出工作区并完成健康检查，VS Code 重启后不会永久保留失效实例。

### 阶段 B：只读核心语义

- 实现 workspace/document symbols、symbol info、references 和 diagnostics。
- 增加结果窗口、上下文限制和统一位置格式。

验收：已知文件位置无需 `codeSnippet` 即可获得定义和真实引用；大型结果不会失控进入上下文。

### 阶段 C：层级与能力探测

- 实现调用层级、类型层级和 Provider 状态。
- 完善超时、取消和语言扩展延迟激活。

验收：支持时返回结构化层级，不支持时返回明确状态且不阻塞 MCP。

### 阶段 D：安全语义修改

- 实现 rename、Code Action、format 的 preview/apply。
- 增加版本、哈希、路径边界和过期校验。

验收：任何陈旧预览都无法应用；多文件变更可审查并报告精确结果。

### 阶段 E：无交互命令兼容

- 实现命令白名单、task 检查、结果追踪和危险命令策略。
- 验证构建、测试和格式化等非交互命令。

验收：非交互任务可自动完成；包含 `${input:...}` 的任务不会弹出输入框或使 MCP 卡住。

### 阶段 F：打包与交付

- 生成 VSIX、MCP Server 可执行入口、安装/卸载/doctor 脚本。
- 编写组件级安装、配置、排障和开发文档。
- 验证与现有 `vscode-mcp`、`simplechat-ast` 同时启用。

验收：新机器可按组件文档独立安装和卸载，不依赖仓库绝对路径。

## 13. 主要风险

| 风险 | 处理方式 |
|---|---|
| 语言扩展未激活 | 打开 TextDocument 后有限等待，并返回明确状态 |
| Provider 空结果难以区分不支持 | capability 使用四态结果，不武断判断 |
| VS Code 类型无法直接序列化 | protocol 包先生成稳定 DTO，再分别编码为严格 JSON 和 YAML |
| Code Action 只返回不透明 command 或资源操作 | 不进入 LLM 候选结果，并通过 warning 说明没有可安全预览的 text-only Action |
| WorkspaceEdit 公共 API 不能枚举资源操作 | 第一版仅重建并 apply `entries()` 的 text edits；size/entries 不一致时拒绝，永不 apply Provider 原始对象 |
| 多工作区路径冲突 | 使用随机 instance/workspace ID，不依赖路径哈希 |
| Windows 管道或路径大小写问题 | 双端规范化并通过 health 发现真实工作区 |
| 大型引用结果消耗大量 token | 强制结果窗口和默认无源码上下文 |
| Preview 后文件变化 | 文档版本与内容哈希双重校验 |
| 指令触发 UI 交互 | 白名单、task 静态检查和默认拒绝策略 |
| VS Code/扩展 API 变化 | 只依赖公开 API，增加版本兼容测试 |

## 14. 参考实现与资料

- [VS Code Programmatic Language Features](https://code.visualstudio.com/api/language-extensions/programmatic-language-features)
- [VS Code Built-in Commands](https://code.visualstudio.com/api/references/commands)
- [VS Code Extension API：WorkspaceEdit、TaskExecution、Position](https://code.visualstudio.com/api/references/vscode-api)
- [Language Server Protocol 3.18](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.18/specification/)
- [Language-Server-MCP-Bridge](https://github.com/sehejjain/Language-Server-MCP-Bridge)：参考 VS Code Provider 映射，不直接照搬其早期实现。
- [Serena](https://github.com/oraios/serena)：参考面向 Agent 的符号工具和上下文控制。
- [mcpls](https://github.com/bug-ops/mcpls)：参考多语言服务器管理、结果结构和进程监控。

## 15. 第一版完成标准

第一版必须同时满足：

- 无需修改现有 `vscode-mcp`。
- 能复用 VS Code 中已工作的 TypeScript、C/C++ 或 C# 语言 Provider。
- 能按文件位置查询定义、类型、实现和引用。
- 能搜索工作区符号并查询调用层级。
- 能获取指定文件和修改文件诊断。
- 重命名必须先预览，Apply 必须验证版本和哈希。
- MCP 和内部机器通道使用严格 JSON；所有面向 LLM 的 `content[].text` 均为可解析 YAML。
- 大结果必须支持第 `a..b` 项选择，并限制上下文。
- 多 VS Code 工作区可稳定发现和选择。
- 所有自动化 command/task 均无 UI 交互。
- Windows 安装、重启、卸载和静态 doctor 验证可重复执行。
