# AgentBase 当前接手状态

状态截点：2026-08-30（Asia/Shanghai）。

## 一句话状态

源码查询链、`source-query` skill 与 VS Code LSP MCP 已完成本轮收敛并发布：PATH 中为 `srcq 0.5.0`，本机安装为 `vscode-lsp-mcp 0.2.0`，Codex 已加载新版 19 个 MCP 工具。源码、路由 evidence、私有上游和 Codex payload 均已对齐；当前没有开放源码实施项，只有一个运行时条件：尚无已激活的 VS Code workspace 注册。

## 当前源码、发布与未提交边界

- 当前已推送实现链为：`aafefc6`（查询工具、skill 与 MCP 升级路径）、`1a6e76e`（skill 引用路由收敛）、`2845ff8`（并存 VS Code 更新目录的安装发现）。`main` 与 `origin/main` 为 `0/0`。
- AgentBase 已通过 `DirectCompatibility + InstallPortableSettings` 正式发布，发布后 Status 为 `published:true`；本次更新 11 个受管对象，回滚备份为 `C:\Users\gzxt\.codex\backups\AgentBase-20260830-231906-5f1dad37`。
- `global/AGENTS.md` 的源码读取规则已纳入项目历史；它要求已知符号后直接有界读取完整定义、签名依赖和相邻契约，并只在当前职责确需且规模有界时读取完整文件。实际 Codex 安装已包含相同内容，仓库候选与受管安装在该规则上对齐；当前预期无 tracked dirty。
- `dist/`、`target/`、MCP 日志和构建输出仍是忽略的可重建资产，不是项目真源。

## 已安装运行时与真实状态

- `srcq 0.5.0`：安装 Status 为 `ready:true`、`integrity:verified`、PATH entry 恰好 1；`srcq doctor` 与 `srcq query scc doctor` 均为 `ok`。
- `vscode-lsp-mcp 0.2.0`：server、companion extension、manifest 和版本身份均通过；当前 Codex 已暴露 19 个新工具，包含 `verify_symbol_candidates`、带 `scopePaths/searchMode` 的 `get_references`，以及新版调用/类型层级工具描述。
- MCP server 的真实 `list_workspaces` 调用成功，但当前返回 `available:0`。Doctor 无失败、无旧 IPC/版本冲突，因 `NO_REGISTRATIONS` 为 `degraded`。若 VS Code 项目本应已打开，先在对应窗口执行一次 **Reload Window**；不得自行关闭用户编辑器。
- 当前安装正常；workspace 注册是 VS Code 窗口/扩展激活状态，不是重新安装或重新 Publish 的理由。

## 当前查询与升级路径

1. 文件发现和文本定位直接用 PATH 中的 `srcq fd` / `srcq rg`，已知符号后停止搜索并有界读取完整定义、签名依赖和相邻契约。
2. 定义、引用和调用候选使用 `srcq symbol`；范围按真实可见性选择：文件内 helper 限文件，公共符号才扩到模块或正式源码根，调用树默认 depth 1、当前路径确需时再取下一层。
3. 少量源码/AST 候选只需判断同一身份时用 LSP `verify_symbol_candidates`；需要明确文件或目录范围内的完整精确引用时用 scoped `get_references`；只有 Provider 全局枚举才能回答时才使用 provider 模式。
4. Provider 空调用树不能推翻 `srcq calls` 已观察到的源码调用点；LSP 不重复文本、AST 或关系候选已经证明的事实。
5. 大型 UAI 只读实测：文件范围引用约 `0.503s`，两层 incoming 调用树约 `1.443s`。C++ incoming 已复用 AST 找到的确切 caller 定义，不再按短名跨模块重选而被同名 helper 干扰。

## 验证与路由证据

- `srcq` 完整 test/build/lint/fmt、真实 UAI 查询和速度基准通过。
- MCP 0.2.0 的组件测试、两次可复现 release、19 工具成功/失败 envelope、安装生命周期、Extension Host、双 workspace 隔离及与 `vscode-mcp`/`ast-mcp` 三进程共存通过。
- 路由合同为 127 cases、84 strict routing、28 strict references；基础设施 6 suites 通过。当前 generation 为 `22FA6E6A7F03BB851652A2C46E4B08E9B23D4E1974142D218CEFBE892A279AC0`，计划为 `runs=0 reuse=3 blocked=0 pending=0`。
- 本轮未运行九项最终评测；它们不是本次工具/skill/MCP 发布的必要门禁。
- 规则文件、安装和门禁通过不自动证明所有后续模型行为；应在新的干净任务中用一个真实、有界工作观察查询升级、纵向闭环和验证成本，出现可复现反例才重开相应 owner。

## 下个对话的最小恢复步骤

1. 读取根 `README.md` 与本文件，运行 `git status --short`；当前预期无 tracked dirty，若出现改动先确认归属，不清理、不回退、不自动提交未知内容。
2. 确认 `HEAD` 与上游关系；若上述实现链仍在当前历史中且本地与上游为 `0/0`，当前源码没有开放实施项，不因缺少新行为观察自动重开。
3. 任务依赖真实安装状态时，只读运行部署说明中的 `DirectCompatibility + InstallPortableSettings Status`、srcq Status 和 MCP status；不得从安装副本反推项目真源。
4. 需要 LSP 时先调用一次 `list_workspaces`。若结果为空且 VS Code 项目已打开，要求用户在对应窗口 Reload Window，再重新读 workspace；不重装、不重发、不原样循环 doctor。
5. 新任务先用真实、有界工作验证新版行为；没有相关改动时不重跑完整组件门禁、路由 evaluator 或九项最终评测。
6. 本次 Publish 授权已经消耗；任何后续正式 Publish 都必须重新取得用户针对当次操作的明确同意。

## 建议的新任务首条消息

```text
请接手 D:\program\AgentBase。

先读取 D:\program\AgentBase\README.md 和 D:\program\AgentBase\docs\handoff.md，按其中“下个对话的最小恢复步骤”恢复。先运行 git status --short；若存在未提交修改，先确认归属，不清理、回退或自动提交未知内容，也不要从 Codex 安装副本反推项目源码。

恢复后只读确认当前 HEAD/upstream、AgentBase 的 DirectCompatibility + InstallPortableSettings Status、srcq 0.5.0 Status，以及 vscode-lsp-mcp 0.2.0 status/list_workspaces。若 VS Code 已打开而 workspace 仍为 0，先告诉我需要 Reload Window，不要自行关闭编辑器或重新安装。

先向我报告当前源码与发布状态、未提交边界、MCP 活跃状态、是否存在开放实施项和建议的下一步，然后等待我的实际任务。上次 Publish 授权已经消耗；未经我针对当次操作明确同意，不得再次 Publish。没有相关改动时不要重跑完整验证或九项评测。
```
