---
name: symbol-structure-workflow
description: "以成本分层方式定位并安全修改需要工具裁决或真实符号语义的代码。用于任务需要在受限 rg、$ast-grep-token-safe、vscode-lsp-mcp 与项目编辑工具间选择，或结论依赖定义、引用、类型、层级、诊断、安全重命名、Code Action 或格式化时；已经明确只需 AST pattern、rule 或 rewrite 时仅使用 ast-grep-token-safe，普通字符串、注释、日志、配置和文件名搜索也不触发。"
---

# Symbol Structure Workflow

以最低成本取得足够证据；文本、AST 和 LSP 分别证明不同层级的事实，不能互相冒充。

## 按需读取

- 需要定义、类型、实现、精确引用、调用/类型层级、语义重命名、Provider 诊断或 LSP 超时恢复时，完整读取 [lsp-query-protocol.md](references/lsp-query-protocol.md)。
- 需要 Code Action、格式化、VS Code task、调试控制、命令执行、窗口/Extension Host 重载或 apply 生命周期时，完整读取 [editor-operations.md](references/editor-operations.md)。
- 只需语法结构搜索或改写时使用 `$ast-grep-token-safe`，并按该 skill 选择其引用；不要为此加载 LSP 协议。

## 成本路由

| 需求 | 首选 | 升级条件 |
| --- | --- | --- |
| 字符串、注释、配置、日志、文件名 | 受限 `rg` / `fd` | 文本不能表达所需结构 |
| 调用、声明、控制流、语法形状、同名候选 | `$ast-grep-token-safe` | 必须区分重载、类型或真实符号身份 |
| 已知文件的源码理解或普通编辑 | 读取源码 + 项目编辑工具 | 结论依赖定义、类型、引用或 Provider 修改 |
| 定义、类型、继承、精确引用、安全重命名 | `vscode-lsp-mcp` | 已是最高语义层，只调用当前缺失能力 |
| 正确性验收 | 定向构建、测试、lint/诊断 | LSP 不能替代构建和运行时证据 |

执行时：

1. 先用准确目录、文件、名称和代码形状缩小范围；证据充分即停止。
2. 结构问题遵循 `$ast-grep-token-safe` 的 Token-Safe 输出、缓存分页和 rewrite 预览。
3. 文本和 AST 只产生候选或语法匹配，不证明跨文件符号身份。
4. 不因“可能有帮助”并行调用 definition、references、hierarchy 和 rename；只请求当前判断缺失的一项。

## 进入 LSP 前

- 先读取目标源码，确认问题确实依赖符号身份、类型、Provider 诊断或语义修改。
- 首次进入时取得并复用当前 `workspaceId`；重载、断线或工作区改变后重新获取。
- `file` 使用工作区逻辑路径；行列从 1 开始，列按 UTF-16。位置不确定时先读目标行，不猜列号。
- 默认使用小结果窗口和零上下文；include/exclude glob 是结果与修改安全边界，不保证 Provider 在查询前减少扫描。
- UE/C++ 高成本 Provider 查询前先完成低成本定位；同一文件首次激活和慢查询串行执行。

## 修改安全门

1. 修改前读取目标源码，保留用户无关改动并明确安全目录。
2. ast-grep rewrite、Code Action、格式化和 rename 均执行 `preview → 审查 → 单次 apply`。
3. 只有预览完整、未截断、身份和文件范围一致时才应用；范围、身份或执行状态未知时停止。
4. apply、命令或连接超时后先检查实际状态；确认未执行前不得重放。
5. 应用后检查目标文件、相关诊断与差异，再按风险运行 formatter、lint/typecheck、构建或定向测试。

## 结果边界

- capability 只表示声明能力；空结果、超时、同名候选和诊断都不得改写成确定符号事实。
- LSP、AST、mock 和静态诊断不能替代编译或运行时验证。
- 只报告支撑结论的结果、范围、截断、超时和未验证边界，避免倾倒大结果。

## 禁止事项

- 不为普通文本、配置、日志或文件名问题启动 LSP。
- 不在位置、范围、预览、身份或 apply 状态不明确时修改。
- 不轮询慢查询、无限增加超时或用同名文本伪造语义成功。
- 不自动执行需要输入/确认、退出 VS Code、安装/卸载扩展、认证或主动断开 MCP 的命令。
