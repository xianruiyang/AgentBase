# LSP 语义查询合同

仅在结论依赖文本和 AST 不能裁决的真实符号身份、类型、精确引用、调用/类型层级或 Provider 诊断时读取。

## 渐进发现

- 先用现有文件、位置和名称把请求收窄；随后只发现能补齐当前证据的一个读取能力，不展开全量工具定义。
- 定义身份先查询精确位置的符号信息或定义；只有结果出现新的必要关系时，再发现引用、层级、类型或诊断能力。
- 首次进入时调用一次 `list_workspaces` 并复用 `workspaceId`；集合窗口从 1 开始且首尾均包含，默认 1–20、单页最多 100，`contextLines` 默认 0。
- 单根工作区的 `file` 使用根相对路径且不加根别名，多根才使用 `<root-alias>/<relative-path>`；不得传物理绝对路径。行列从 1 开始、列按 UTF-16，位置不确定时先读目标行而不猜测；输入路径错误应按工作区身份修正，不调用 `health_check` 掩盖参数问题。
- `workspace_symbols` 在小项目、热索引或高效 Provider 下可以直接使用；在大型项目或已观测到昂贵/不稳定的 Provider 下先用文本或 AST 缩小范围，再定向查询。
- 精确引用优先调用 `get_references`：C/C++ 默认 `auto` 会在工作区标准源码扩展名内快速发现 token 并核验每个候选身份，成功即为该工作区搜索边界内的完整集合；超出预算时用 `scopePaths` 直接列出相关逻辑文件或目录，例如 `Source/Module`、`Plugins/Name/Source`，无需改写 glob。只有所有候选均验证完成才接受成功，任何 incomplete 都保持未证。
- 已经由 `srcq rg` 或 AST 得到更小候选集时，可改用 `verify_symbol_candidates`；只把 `verified` 计入同符号结果，`mismatched` 排除，`unresolved` 或位置错误保留为未证，完整性不得超过文本/AST 实际覆盖范围。
- 只有结论必须依赖 Provider 自身枚举时才把 `get_references.searchMode` 设为 `provider`，并按需传入最长 300000 ms 的 `timeoutMs`；include/exclude 只过滤 Provider 输出，不能缩小其内部扫描。客户端工具超时必须高于该值并预留桥接收尾时间。
- 记录 Provider、工作区和文档版本边界；超时、不可用、部分结果和陈旧文档不得解释为空集合或完整答案。

## 职责边界

优先使用 Codex 已提供的延迟 MCP 工具目录；未用 LSP 的任务不得为预检而加载其 schema。当前正式运行时没有 `srcq lsp` 入口，不得猜测调用；只有宿主延迟发现经正式验收不达标并完成分支设计与实现后，才可接入复用现有 VS Code companion 与 Provider 的只读入口。Source Query Gateway 只负责源码查找，不能因查询需要而取得 rename、Code Action 应用、格式化应用、命令执行或调试控制授权，也不得另写第二套 LSP 语义实现。
