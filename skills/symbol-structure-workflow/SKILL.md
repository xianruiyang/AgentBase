---
name: symbol-structure-workflow
description: "以成本分层方式定位并安全修改需要结构或符号语义的代码。用于任务需要在受限 rg、$ast-grep-token-safe、vscode-lsp-mcp 与项目编辑工具间选择，或结论依赖定义、引用、类型、层级、诊断、安全重命名、Code Action 或格式化时；普通字符串、注释、日志、配置和文件名搜索不触发，直接使用对应文本或文件发现 skill。"
---

# Symbol Structure Workflow

以最低成本取得足够证据；不要把 LSP 当作默认发现工具或形式化验收步骤。

## 成本路由

| 需求 | 首选 | 何时升级 |
| --- | --- | --- |
| 字符串、注释、配置、日志、文件名 | 受限 `rg` / `fd` | 文本不能表达所需结构时 |
| 调用、声明、控制流、语法形状、同名候选 | `$ast-grep-token-safe` | 必须区分重载、类型或真实符号身份时 |
| 已知文件的源码理解或普通编辑 | 读取源码 + 项目编辑工具 | 结论依赖定义、类型、引用或 Provider 修改时 |
| 定义、类型、继承、精确引用、安全重命名 | `vscode-lsp-mcp` | 已是最高语义层；调用最小必要工具 |
| 正确性验收 | 定向构建、测试、lint/诊断 | LSP 不能替代构建和运行时证据 |

执行规则：

1. 先缩小目录、文件、名称和代码形状；证据充分即停止。
2. 结构问题触发并遵循 `$ast-grep-token-safe`，使用其内置 sgy、Token-Safe YAML、缓存分页和 rewrite 预览；不要在这里复制其命令协议。
3. ast-grep 只证明语法匹配，不证明跨文件符号身份；文本/结构候选不得冒充精确引用或安全 rename。
4. 不因“可能有帮助”同时调用 definition、references、hierarchy 和 rename；只调用当前判断缺失的一项。

## LSP 相对成本与准入

UE/C++ 的 cpptools 成本可能远高于其他语言。下表是调用门禁，不是固定耗时承诺。

| 工具 | 成本 | 仅在以下情况调用 | 控制方式 |
| --- | --- | --- | --- |
| `list_workspaces` | 很低 | 本轮确定需要 LSP | 调一次并复用；重启/断线后重取 |
| `health_check` | 低 | 首次激活或故障诊断 | 可带目标文件；不要每次查询前调用 |
| `get_capabilities` | 中 | 排查兼容性或策略 | 结果仅作弱提示，不能作为门禁 |
| `document_symbols` | 低-中 | 已知文件，需要语义大纲/嵌套路径 | 优先于全工作区搜索 |
| `symbol_info` | 中 | 需要 hover、定义、类型、实现或签名 | 每次只请求当前需要的 kind |
| `get_diagnostics` | 低-中 | 需要已发布诊断 | 指定 files；避免无必要 workspace 范围 |
| `workspace_symbols` | 中-高 | 名称已知但文件未知，rg/AST 不足以消歧 | 限 query、kind、glob 和结果窗口 |
| `get_call_hierarchy` / `get_type_hierarchy` | 高 | 用户问题本身要求调用/继承关系 | 限方向和深度，不作常规预检 |
| `get_references` | 很高 | 必须得到同一符号的精确影响范围 | 先完成低成本定位；遵循下方协议 |
| `rename_preview` | 很高 | 用户确实要求语义重命名 | 必须限定安全范围；不要默认先跑 references |
| `code_actions` / preview | 中 | 诊断驱动或用户要求 Provider 修复 | 只预览选中的 action |
| `format_preview` | 中 | 用户要求格式化或项目验收需要 | 限文件/范围；普通编辑不必调用 |
| `*_apply` / `execute_command` | 副作用 | 完整预览已确认，或用户任务需要运行/调试/重载 | 只调用一次；结果未知时先验状态 |

## LSP 契约

- 进入 LSP 路线后先取当前 `workspaceId`；后续使用同一 ID。
- `file` 使用工作区逻辑路径，不传绝对路径、URI 或 `..`。多根工作区使用 `list_workspaces` 返回的根别名。
- 行列从 1 开始，列按 UTF-16；位置不确定时先读目标行，不猜列号。
- 集合默认取 1–20 项、`contextLines: 0`；仅在判断需要时分页或增加上下文。
- include/exclude glob 用于结果和修改安全边界，不保证 Provider 查询前缩小扫描。大型工作区排除 Saved、Binaries、缓存和源码镜像；不要删除或阻断 UE 编译所需的 Intermediate 生成内容。
- 同一文件首次激活和高成本 Provider 调用串行执行，不并发叠加。

## 高成本查询协议

### 精确引用

调用 `get_references` 前必须满足：

1. 已读取源码并确认精确符号位置；名称常见时先用 rg/ast-grep 了解候选和合理源码根。
2. 结论确实要求“同一符号的完整/精确引用”，而不是同名候选、调用形状或有限影响估计。
3. C++ 优先给出有固定目录前缀的 `includeGlobs`，并排除生成物/副本；保持小结果窗口和零上下文。

C++ 首次调用不显式设置 `timeoutMs`，让 MCP 优先尝试 scoped identity fallback；出现 `references_scoped_identity_fallback` 才表示候选已逐项验证。显式 `timeoutMs: 90000` 会把预算留给全局 Provider，只在用户确实需要全局完整结果、索引已稳定且 60 秒不足时使用。

### 语义重命名

1. 用源码、rg/ast-grep 和必要的 `symbol_info` 确认目标与安全目录；不要例行先调用昂贵的 `get_references`。
2. `rename_preview` 必须提供 `includeGlobs`，按需排除镜像、Saved、Pak、缓存和无关插件。
3. 只有预览完整、未截断、每个文件和 edit 都属于同一目标时，调用一次 `rename_apply`。
4. `RENAME_SCOPE_VIOLATION`、`RENAME_IDENTITY_UNVERIFIED`、`RENAME_NO_EDITS` 或 `PREVIEW_TOO_LARGE` 都表示没有可安全应用的预览；不得放宽范围绕过。

普通局部编辑不需要先做 LSP 重命名或引用查询；读取源码、最小编辑并做定向验证即可。

## 超时与恢复

Provider 默认预算为 60 秒，可显式设置的慢查询上限为 90 秒。超时不是空结果，也不提供可依赖的部分语义结果。

| 状态 | 处理 |
| --- | --- |
| `get_capabilities` timedOut/unknown | 忽略门禁含义；若确有需要，直接做一次精确定向调用 |
| symbols / hierarchy 超时 | 降级到 rg、ast-grep、源码和定点 definition；不原样重试 |
| references / rename 超时 | 立即停止该高成本链；不得并发或连续重试 |
| 超时后 `PROVIDER_UNAVAILABLE` | 底层 Provider 可能仍占用单飞槽；等待明确的索引/Provider 恢复证据，最多再试一次 |
| `WORKSPACE_DISCONNECTED` / NOT_FOUND | 重新 `list_workspaces` 一次；仍失败则降级 |
| `DOCUMENT_CHANGED` / preview 失效 | 重读源码并重新预览 |
| apply/command 超时或连接中断 | 先检查实际状态；确认未执行前不得重放 |

不要轮询高成本调用、无限增加超时或用同名文本伪造成功。若低成本证据足以完成安全范围内工作，继续完成；若任务必须依赖缺失语义，明确报告限制。

## 命令、任务与重载

- 可信工作区默认允许无参数的保存、调试控制、窗口/Extension Host 重载，以及已声明的前台 task；自定义 command 才需要精确策略条目。
- 构建、测试、lint 等使用 `target.kind: task` + `taskName`，重名时加 `taskRoot`；不要调用会弹 QuickPick 的 `workbench.action.tasks.*`。
- 仅在用户任务需要运行或调试时调用 `workbench.action.debug.start` / `run` 及 continue、step、pause、restart、stop；不要调用 `debug.selectandstart`。
- task 仍会拒绝 input/command 变量、background、CustomExecution 和不可验证完成；失败后按退出码/状态处理，不改用终端注入绕过。
- task 默认仅在失败时保留 `outputLog`；只有确需检查成功输出时才传 `retainOutputLog: true`。正文不进入 MCP 响应；先按路径、行数和字节数判断范围，再用受限搜索定位并只读必要行。缺少日志不等于没有终端输出。
- `reloadWindow` / `restartExtensionHost` 成功表示已接受并延迟调度；预期 Bridge 会断开。等待恢复后重新 `list_workspaces`，不要复用旧 `workspaceId` 或重复重载。
- 退出 VS Code、安装/卸载扩展、认证、输入/确认 UI、禁用 companion 或主动断开 Bridge 仍不得自动执行。

## 修改与验收

- 修改前读取目标源码并保留用户无关改动。
- Code Action、格式化和 rename 均遵循 preview → 审查 → 单次 apply。
- 应用后检查目标文件和必要诊断，并按风险运行 formatter、lint/typecheck、构建或定向测试。
- LSP、ast-grep 和诊断都不能代替编译或运行时验证。
- 只报告支撑结论的结果、截断、超时和未验证边界，避免把大结果倾倒进上下文。

## 禁止事项

- 不为文本/结构问题启动高成本 LSP。
- 不把 capability、空结果、超时或同名候选改写成确定语义。
- 不在位置、范围、预览或身份不明确时应用修改。
- 不自动执行需要输入/确认、退出 VS Code、扩展管理、认证或主动断开 MCP 的命令。
