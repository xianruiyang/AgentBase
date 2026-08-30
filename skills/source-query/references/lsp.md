# LSP 语义查询合同

仅在结论依赖文本和 AST 不能裁决的真实符号身份、类型、精确引用、调用/类型层级或 Provider 诊断时读取。

## 渐进发现

- 定义、引用或调用关系先消费 `srcq symbol` 已返回的位置候选、范围状态和 unknown 原因；只有未决身份、类型、重载或动态语义会改变当前动作时才进入 Provider，不为重复候选集合启动 LSP。
- 先用现有文件、位置和名称把请求收窄；随后只发现能补齐当前证据的一个读取能力，不展开全量工具定义。
- 定义身份先查询精确位置的符号信息或定义；只有结果出现新的必要关系时，再发现引用、层级、类型或诊断能力。
- 首次进入时调用一次 `list_workspaces` 并复用 `workspaceId`，只有窗口重启、断开或返回 stale/unknown workspace 时刷新；集合窗口从 1 开始且首尾均包含，默认 1–20、单页最多 100，`contextLines` 默认 0。
- 单根工作区的 `file` 使用根相对路径且不加根别名，多根才使用 `<root-alias>/<relative-path>`；不得传物理绝对路径。行列从 1 开始、列按 UTF-16，位置不确定时先读目标行而不猜测；输入路径错误应按工作区身份修正，不调用 `health_check` 掩盖参数问题。
- `workspace_symbols` 在小项目、热索引或高效 Provider 下可以直接使用；在大型项目或已观测到昂贵/不稳定的 Provider 下先用文本或 AST 缩小范围，再定向查询。
- C/C++ 普通函数列表与语法轮廓由 AST 的 `function_declarator` 查询承担，不调用 `document_symbols`；只有所需结论依赖语义符号种类、Provider 嵌套、精确重载调用关系或类型关系时才使用相应 LSP 工具。
- 记录 Provider、工作区和文档版本边界；超时、不可用、部分结果和陈旧文档不得解释为空集合或完整答案。
- 冷 C/C++ 层级会在一次请求内有界等待瞬时空结果；保持活动 `compile_commands` 含目标文件且不含已删除条目，复用同一 VS Code 窗口，不原样重试。cpptools 没有 C++ Type Hierarchy；继承关系走 AST。

## 选择一个语义动作

| 当前缺口 | 只调用 |
| --- | --- |
| 已知位置，但定义、类型、实现或重载身份仍影响动作 | `symbol_info`，`include` 只列所缺字段 |
| 已有不超过 100 个文本/AST/srcq 候选，只需判定是否同一符号 | `verify_symbol_candidates`；它不枚举，也不扩大候选范围 |
| 需要一个明确文件/目录范围内完整精确引用 | `get_references`，C/C++ 用 `searchMode=scoped` 和对应逻辑 `scopePaths` |
| 工作区合理且确需完整引用，尚无更好范围 | `get_references` 的 `auto`；快速路径不能完成时先收窄，不自动转 Provider |
| 只有语言 Provider 自身的全局枚举才能回答 | `get_references searchMode=provider`，显式预算并接受冷启动成本 |
| 源码调用候选存在真实重载或动态分派歧义 | `get_call_hierarchy`；空结果不作为不存在证明 |
| 非 C++ Provider 确实实现类型层级且 AST 不足 | `get_type_hierarchy` |

`srcq` 的物理范围和 MCP 的逻辑范围应表达同一个 owner/消费者边界；把前者转换为 `list_workspaces` 返回的逻辑文件或目录，不把物理绝对路径传给 MCP。工作区外依赖先由 `srcq` 的编译范围或显式根查询；只有 VS Code 窗口确实暴露该根时，才把它作为 LSP 输入。

C/C++ fast/scoped 引用只有全部候选完成身份核验才成功，任何 incomplete 都保持未证；Provider 模式的 include/exclude 只过滤返回，不能缩小内部枚举。`verified` 只证明提交给 `verify_symbol_candidates` 的位置；`unresolved` 仍未证。Provider 调用边只证明实际返回结果，空树不能覆盖 `srcq calls` 已观察到的调用点。

## 职责边界

优先使用 Codex 已提供的延迟 MCP 工具目录；未用 LSP 的任务不得为预检而加载其 schema。当前正式运行时没有 `srcq lsp` 入口，不得猜测调用；只有宿主延迟发现经正式验收不达标并完成分支设计与实现后，才可接入复用现有 VS Code companion 与 Provider 的只读入口。Source Query Gateway 只负责源码查找，不能因查询需要而取得 rename、Code Action 应用、格式化应用、命令执行或调试控制授权，也不得另写第二套 LSP 语义实现。
