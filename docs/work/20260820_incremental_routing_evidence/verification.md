# 增量独立路由验证证据

## 确定性基础设施

- `test_routing_infrastructure.ps1 -View Machine` 通过：22 个 PowerShell 文件语法有效，6 组套件并行通过，`model_evaluator_runs=0`，共享 runtime 抽取后一次实测约 16.9 秒。
- 套件覆盖阶段指纹、最小 capsule、cases-only schema、planner、用户 npm Codex 的 nested/hoisted/vendor 布局与安全解析、单模型目录投影、禁用能力、环境清理、Begin/Finish、复用与跨代收据、稳定锁、分类限额、同代恢复、跨代搬运及搬运中断续传。
- invoker 的测试边界行为验证通过：`AGENTBASE_ROUTING_EVALUATOR_DISABLED=1` 时在生成输出或 Begin 前拒绝，确定性回归不能意外启动模型。

## 独立模型 evidence

- 当前 generation 为 `4CE359AE0B4873D9D910ADB7371DF62E909678BE7C80CE6DD50167C5DD41E311`。正式 validator 通过 96 个 Routing、96 个 Policy 和 26 个 References 用例；attempt history 为 schema 3、3/6 收据，无 `started`。
- 最终刷新以两份 `staged_carry_forward` 收据复用 Routing 与 Policy，只启动一次 References evaluator；该次 CLI 报告 18,391 input、0 cached input、3,766 output Token。紧接着再次调用正式 refresh 返回 `already-current`、`evaluator_run_count=0`，没有新增收据。
- 真实失败均先改变机制或可见输入再继续：WindowsApps package-identity ACL 改由官方用户 npm 原生 CLI；冷 home 远端目录刷新改为单模型目录投影；PowerShell 环境清理 stdout 污染、结构化 schema 不支持字段、并发锁删除竞态、预执行失败分类和引用过选分别形成实现或触发边界修正。没有对未变输入盲目重跑。

## Token 与时间边界

- 使用同一 `tiktoken 0.13.0 / o200k_base` 口径，旧三阶段 capsule 为 36,785 Token；当前为 Routing 14,191、Policy 13,426、References 7,920，总计 35,537，完整冷启动输入下降 1,248 Token（约 3.4%）。
- 主要收益来自增量触发而非宣称完整 capsule 大幅缩短：未变化为零模型调用；非引用 skill 正文变化为零调用；仅引用正文变化只运行 References，静态 capsule 工作集由当前三阶段 35,537 降为 7,920（约减少 77.7%），实际 API 用量仍以对应 receipt 为准。
- 统一确定性套件并行执行约 16 秒；模型 evaluator 不进入该时间与 Token 预算。

## Windows 主机与部署门禁

- `bootstrap_windows.ps1 -Action Check -View Machine` 读回 `ready=true`、8 个前置均受支持；Codex CLI 为 0.148.0，路径是用户 npm nested optional-package 布局下的原生 `codex.exe`，隔离选项受支持，用户 npm prefix 位于 WindowsApps 前。bootstrap 与 evaluator 对该路径使用同一个共享解析 owner。
- `test_bootstrap_windows.ps1`、managed asset lifecycle、portable agents、portable config 和完整 `test_manage_agentbase.ps1` 均通过。沙箱 Publish 不重复嵌套基础设施套件；真实 CodexRoot Publish 仍执行。
- `manage_agentbase.ps1 -Action Validate` 通过；本轮未执行 Codex Publish，也未升级真实 srcq 安装。
