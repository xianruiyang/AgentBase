# AgentBase 当前接手状态

状态截点：2026-08-20 增量独立路由评估与统一确定性测试基础设施闭环，未执行新的 Codex Publish（Asia/Shanghai）

## 一句话状态

AgentBase 已形成分阶段、增量、可恢复的独立 Codex 路由评估和统一零模型测试入口；当前 96/96/26 evidence、部署 Validate 与全部受影响本地回归通过，没有开放实施项。真实 srcq 安装仍为 0.3.1，真实 Codex 仍是上一轮发布态。

## 仓库、候选与真实发布状态

- 当前分支为 `main`；增量评估、测试基础设施、验证记录和本交接按持续 Git 授权提交并非强制推送到私有 `origin/main`。正常接手时上游与工作区应一致，若 dirty 必须先确认归属并保留。
- 项目源码版本为 `srcq 0.4.0`。最终源码快照为 `sha256:c7795a6bc25ed6a2ccc477de60a76fad5d9723f9395784f521e5aceabebde300`；本机忽略目录中的可复现 ZIP 为 2725761 bytes，SHA-256 `65734560168a3471c6f907e156ab61ef68fcb88db7a1add93d0014e28648d942`。
- 独立用户级 srcq 安装仍为 0.3.1；0.4.0 只完成隔离升级和 release 沙箱验证，没有写入真实安装根。
- scc 3.7.0 与 hyperfine 1.20.0 已由 winget 安装；官方用户 npm `@openai/codex@0.148.0` 也已安装，持久 User PATH 中 npm prefix 位于 WindowsApps 前。bootstrap 与路由 runner 共用 `development/common/codex_cli_runtime.ps1` 解析 nested/hoisted/vendor 布局下的绝对原生 `codex.exe`，当前桌面宿主要通过命令名继承新 PATH 时仍需完全退出并重启。
- 最新真实 Codex 发布仍是上一轮 `DirectCompatibility + InstallPortableSettings`；回滚备份仍为 `C:\Users\gzxt\.codex\backups\AgentBase-20260819-001202-f1169bf2`。P11 的 `global/AGENTS.md`、`source-query` 和部署候选尚未 Publish。
- 上一次 Publish 授权已经消耗；任何再次 Publish 必须取得用户针对当次操作的明确同意。持续 Git 维护与私有远端非强制同步授权继续有效，但不能替代发布授权。

## 当前评估与工具能力

- 普通源码统计使用 `srcq scc <scc argv...>`；高级控制使用 `srcq query scc <exec|defaults|doctor>`，覆盖 summary/languages/files/hotspots/lossless/raw、machine、artifact、稳定分页与同次捕获协议回退。
- 规范化指标保留文件、行、代码、注释、空行、复杂度和字节；COCOMO/cost/schedule/people 只在 lossless/raw/artifact 中保留，复杂度不作为缺陷或质量结论。
- Windows bootstrap 现在管理 8 个前置工具，并以精确包身份安装/检查 scc、hyperfine 与用户 npm Codex CLI；hyperfine 保持独立 benchmark 职责，不进入 srcq 或发布 payload。
- `global/AGENTS.md` 提供普通 scc/hyperfine 的低固定成本路由；`source-query` 只在 scc 定向视图、machine/raw/artifact、分页或 AST/LSP 证据升级时触发。
- release manifest 已声明非捆绑 `scc.exe` 与验证版本 3.7.0，安装器与部署 preflight 会分别验证 srcq 完整性、AST doctor 和 scc doctor。
- `test_routing_infrastructure.ps1` 一次解析 22 个评估及共享 runtime PowerShell，并行运行指纹、capsule、planner、隔离 runtime、attempt ledger 和恢复套件；进程环境机械禁止 evaluator，实测约 17 秒、零模型调用。
- `get_routing_evaluation_plan.ps1` 与 `refresh_routing_evidence.ps1` 只运行可见语义变化阶段；passed stage 可同代恢复、跨代搬运并在搬运中断后继续，未变化再次刷新为 `already-current`。

## 验证与未跨越边界

- srcq 全 workspace 门禁通过；受影响定向为 lib 45/45、真实 query gateway 32/32、release 6/6。backend 合同 6/6、36 模式、9 oracle 和 AST 0.4.0 baseline 通过。
- bootstrap 回归与真实只读 Check 通过：`ready:true`、8/8 supported；插件、portable config/agent/lifecycle、0.3.1→0.4.0 安装生命周期和最终 release 烟测通过。
- 静态路由合同为 96 cases、55 strict routing、10 strict references，11/11 skills 有正向与非触发覆盖。
- 当前独立 evidence generation 为 `4CE359AE0B4873D9D910ADB7371DF62E909678BE7C80CE6DD50167C5DD41E311`：Routing 96/96、Policy 96/96、References 26/26；当前账本 3/6 收据，两阶段跨代零 Token 搬运、References 一次正式运行，随后同输入 refresh 为零运行。
- 统一评估基础设施、bootstrap、managed lifecycle、portable agents/config、完整部署回归与 `manage_agentbase -Action Validate` 均通过。当前三 capsule 同口径为 35,537 Token；仅 References 工作集为 7,920，非引用 skill 正文变化为零模型调用。
- 本机没有 `cargo-audit`，未新增 advisory scan；未安装该工具。未执行真实 srcq Upgrade，未执行 Codex Publish。

## 下个对话的最小恢复步骤

1. 读取根 `README.md` 和本文件，运行 `git status --short`；正常状态应为 clean，若出现 dirty 内容先确认归属并保留用户改动。
2. 当前没有开放实施项。只有需要选择、替代或重开子计划时读取 `docs/plan.md`；本轮详细证据见 `docs/work/20260820_incremental_routing_evidence/verification.md` 与 `completion-audit.md`。
3. 修改路由基础设施时运行零模型 `test_routing_infrastructure.ps1`；规则、skill 或触发合同变化后先查看 planner，再由正式 refresh 只运行 `evaluate` 阶段。Validate/真实 Publish 会运行确定性套件并拒绝陈旧 evidence，但不会替用户静默启动模型。
4. 若任务依赖真实安装状态，按部署说明只读核对 `DirectCompatibility + InstallPortableSettings Status` 和 srcq `Status`；不要把 0.4.0 本地 release 候选当作已安装版本。
5. 只有用户针对当次操作明确同意后，才可升级真实 srcq 或执行新的 Codex Publish；PATH 发生变化后先重启 Codex 桌面宿主并在新任务中验证。
