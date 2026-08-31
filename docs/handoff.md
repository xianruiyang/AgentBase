# AgentBase 当前接手状态

状态截点：2026-09-01（Asia/Shanghai）。

## 一句话状态

开发环境与门禁治理 T001—T006 已闭环：Windows SWE 候选与 Verifier 已迁移为受信任本地双工作区，旧 elevated setup、权限画像、ACL/canary、认证 hardlink、preflight 和专用 cleanup 已从生产入口与测试退出；旧 ACL 保护的 workspace、sandbox runtime 与 sandbox check 残留经用户明确授权的一次管理员清理后物理删除。2026-08-31 已正式发布当前全局规则、`subagent-orchestration` 与 6 子代理容量，发布后 formal gap 为 0；T007 只保留有明确重开条件的客户端能力阻塞。2026-09-01 又发布 `srcq-v0.6.0`，覆盖 C# 与 Go/Python/Rust/JavaScript/TypeScript/TSX 的无 LSP typed relation 和本地项目范围增强。

## 当前源码、发布与未提交边界

- 本轮治理改动归属 `development/agent-evaluation/`、根/组件文档及 `docs/work/20260830_development_environment_governance/`；后续若这些路径重新出现未提交修改，先确认归属，不清理、回退或自动提交未知内容。
- `srcq-v0.6.0` 指向 `9bee175a1005485f6591fffa9ea3bdf0862d0c84`，Windows 归档 SHA-256 为 `552ff93b24f7bb01d71bfa895f3aa4c766f9024b75a4986d878934bb0d1ee38f`；8 个 Release 资产、真实认证下载和隔离安装/Status/卸载已验证。用户默认安装未随 Release 自动升级，仍为 ready 0.5.0。
- T001—T006 已完成只读入口、受信任本地 candidate/Verifier/recover、旧 strict-safety 生命周期退出、当前 owner/入口更新、无消费者残留清理和跨契约完成审计。T007 的客户端主动调度行为仍保持 blocked，只有出现正式结构化委派机制时才按任务表重开，不影响本轮环境治理完成。
- `DirectCompatibility + InstallPortableSettings` 已于 2026-08-31 10:15（Asia/Shanghai）正式发布：`AGENTS.md`、`config.toml` 和 `subagent-orchestration` 的两个文件实际变化，Status 为 `managed_payload_formally_published=true`、gap 0。evaluator 开发源码不属于 Codex payload，安装副本仍不得反推项目源码；当前运行也不会追溯加载新规则。
- 本次 Publish 授权已经消耗；任何新的正式 Publish 都必须取得用户针对当次操作的明确同意。Git 维护与私有上游同步授权不等于 Publish 授权。
- `.codex/`、`codexRuntimeLogFile/`、`node_modules/`、`dist/`、`target/`、覆盖率、测试缓存和部署沙箱是本地状态或可重建产物，不是项目真源。

## 最终评测当前合同

- 当前正式入口为 [`development/agent-evaluation/README.md`](../development/agent-evaluation/README.md) 和 `agent_eval.py` 的 `validate/list/next/check/prepare/oracle/run/recover/report`。
- candidate 每次从 `global/AGENTS.md`、`global/config.toml`、`global/agents/` 与 `skills/` 生成工作区投影；安装 Codex 根只用于现有认证和 session 使用量统计，不复制或链接凭据。
- Verifier 在独立工作区运行；保留固定 corpus/依赖、patch 边界、身份/收据、锁/CAS、超时/后代进程终止、报告和无模型恢复合同。
- 已删除 `candidate_preflight.ps1`、`sandbox_runtime_cleanup.ps1`、`collect_native_validation.ps1` 以及 sandbox setup/status/check/assess CLI，不保留兼容入口。
- 正式 `test_agent_evaluation_infrastructure.ps1` 已通过 62/62，明确保持 model evaluator disabled；Python 编译、PowerShell AST、当前 CLI 命令面和退役生产入口引用审计同时通过。本轮没有运行真实模型、九题 qualification 或九题评测。

## 已安装运行时与 MCP

- 当前正式 Release 为 `srcq 0.6.0`；本机用户级安装 Status 仍为 ready/integrity verified 0.5.0，PATH 条目恰好 1 个，doctor 与 scc doctor 均为 `ok`。发布不等于安装，后续升级须按用户任务单独执行。`vscode-lsp-mcp 0.2.0` 本轮未修改。
- 上一轮 MCP `list_workspaces` 返回 `available:0`。若 VS Code 项目已打开而读回仍为 0，先要求用户在对应窗口执行 **Reload Window**；不要自行关闭编辑器、重装扩展或重新 Publish。
- 需要当前安装结论时必须走各组件正式只读 Status/list 入口重新读回，不能把本文件的历史截点当作实时状态。

## 下个对话的最小恢复步骤

1. 读取根 `README.md` 与本文件，运行 `git status --short`；若存在未提交修改，先确认与本轮治理边界是否一致，不清理、不回退、不自动提交未知内容。
2. 确认当前 `HEAD`、上游和 ahead/behind；开发环境治理 T001—T006 已完成，不重跑。T007 是有明确重开条件的客户端能力阻塞，不把它误报为当前实施项。
3. 任务依赖真实安装状态时，只读运行部署说明中的 `DirectCompatibility + InstallPortableSettings Status`、srcq Status 和 MCP status/list_workspaces；正式 srcq Release 是 0.6.0，但本机安装仍可能是 0.5.0，不得把 Release 外推为已安装，也不得从安装副本反推项目真源。
4. 需要 LSP 时先调用一次 `list_workspaces`。若结果为空且 VS Code 项目已打开，要求用户 Reload Window 后再读一次；不重装、不重发、不原样循环 doctor。
5. 最终评测改动只运行模型禁用的组件确定性入口；没有用户显式评测任务时不运行九题 oracle、候选模型或九项评测。
6. 未取得新的当次 Publish 授权时，只能完成源码、验证、Git 提交与已授权私有上游同步，不得 Publish。

## 建议的新任务首条消息

```text
请接手 D:\program\AgentBase。

先读取 D:\program\AgentBase\README.md 和 D:\program\AgentBase\docs\handoff.md，按其中“下个对话的最小恢复步骤”恢复。先运行 git status --short；不要清理、回退或自动提交未知内容，也不要从 Codex 安装副本反推项目源码。

恢复后只读确认当前 HEAD/upstream、AgentBase 的 DirectCompatibility + InstallPortableSettings Status、srcq 当前 Status（正式 Release 为 0.6.0，本机上次读回仍为 0.5.0），以及 vscode-lsp-mcp 0.2.0 status/list_workspaces。若 VS Code 已打开而 workspace 仍为 0，先告诉我需要 Reload Window，不要自行关闭编辑器或重新安装。

开发环境治理 T001—T006 已完成；T007 只在任务表记录的正式重开条件成立时继续。上次 Publish 授权已经消耗，未经我针对当次操作明确同意不得 Publish。没有相关改动时不要重跑完整验证或九项评测。
```
