# 增量独立路由验证证据

## 确定性基础设施

- `test_routing_infrastructure.ps1 -View Machine` 通过：22 个 PowerShell 文件语法有效，6 组套件并行通过，`model_evaluator_runs=0`；2026-08-21 共享 shell policy 接入后的读回为 `ready:true`、约 17.8 秒。
- 套件覆盖阶段指纹、最小 capsule、cases-only schema、planner、用户 npm Codex 的 nested/hoisted/vendor 布局与安全解析、单模型目录投影、共享 policy 哈希/严格 CLI 参数、禁用能力、环境清理、Begin/Finish、复用与跨代收据、稳定锁、分类限额、同代恢复、跨代搬运及搬运中断续传。
- invoker 的测试边界行为验证通过：`AGENTBASE_ROUTING_EVALUATOR_DISABLED=1` 时在生成输出或 Begin 前拒绝，确定性回归不能意外启动模型。

## 独立模型 evidence

- 当前 generation 为 `4CE359AE0B4873D9D910ADB7371DF62E909678BE7C80CE6DD50167C5DD41E311`。正式 validator 通过 96 个 Routing、96 个 Policy 和 26 个 References 用例；attempt history 为 schema 3、3/6 收据，无 `started`。
- 共享 shell policy 加强后只读 planner 仍返回 Routing、Policy、References 全部 `reuse/visible_identity_and_oracle_valid`，`evaluation_count:0`，generation/capsule/可见输入均未变化；既有成功 runner 已拒绝所有 tool event，因此没有模型可见环境变化，也没有重采样依据。
- 最终刷新以两份 `staged_carry_forward` 收据复用 Routing 与 Policy，只启动一次 References evaluator；该次 CLI 报告 18,391 input、0 cached input、3,766 output Token。紧接着再次调用正式 refresh 返回 `already-current`、`evaluator_run_count=0`，没有新增收据。
- 真实失败均先改变机制或可见输入再继续：WindowsApps package-identity ACL 改由官方用户 npm 原生 CLI；冷 home 远端目录刷新改为单模型目录投影；PowerShell 环境清理 stdout 污染、结构化 schema 不支持字段、并发锁删除竞态、预执行失败分类和引用过选分别形成实现或触发边界修正。没有对未变输入盲目重跑。

## Token 与时间边界

- 使用同一 `tiktoken 0.13.0 / o200k_base` 口径，旧三阶段 capsule 为 36,785 Token；当前为 Routing 14,191、Policy 13,426、References 7,920，总计 35,537，完整冷启动输入下降 1,248 Token（约 3.4%）。
- 主要收益来自增量触发而非宣称完整 capsule 大幅缩短：未变化为零模型调用；非引用 skill 正文变化为零调用；仅引用正文变化只运行 References，静态 capsule 工作集由当前三阶段 35,537 降为 7,920（约减少 77.7%），实际 API 用量仍以对应 receipt 为准。
- 统一确定性套件并行执行约 16 秒；模型 evaluator 不进入该时间与 Token 预算。

## Windows 主机与原部署门禁快照

- `bootstrap_windows.ps1 -Action Check -View Machine` 读回 `ready=true`、8 个前置均受支持；Codex CLI 为 0.148.0，路径是用户 npm nested optional-package 布局下的原生 `codex.exe`，隔离选项受支持，用户 npm prefix 位于 WindowsApps 前。bootstrap 与 evaluator 对该路径使用同一个共享解析 owner。
- 当前原生 Codex 的无模型 `features list` 已在临时空 home 中接受共享 policy 的全部 33 个 `-c` overrides，证明 PowerShell 生成的通配符 dotted-key 参数可被真实 CLI 解析；临时 home 已清理。
- `test_bootstrap_windows.ps1`、managed asset lifecycle、portable agents、portable config 和当时的完整 `test_manage_agentbase.ps1` 均通过。该快照曾验证真实 CodexRoot Publish 消费路由 evidence；这项职责已于 2026-09-03 由 SOL-006 退出，不代表当前部署合同。
- 当时的 `manage_agentbase.ps1 -Action Validate` 通过；该历史结果不覆盖 schema 9 迁移。

## 2026-09-03 模型 evidence 退出部署验证

- 两次由真实候选变化触发的增量路由研究都出现不同语义 oracle 失败；第二次还让一个候选语义未变的小型闭集 case 选择被其明确边界禁止的标签。没有对相同模型输入重采样；失败收据保留为研究证据。
- 当前 attempt ledger 的独立校验通过：活跃 generation 有 2/6 份有界失败收据，没有未完成尝试或超限重采样。`current.json` 仍是上一份已完成候选；对二者强行执行同代绑定校验会按合同拒绝“不同 visible candidate”，准确表明当前研究尚未合并成功快照，而不是部署或账本结构失败。
- 生产代码审计确认 Routing、Policy 与 References 的具体选择没有 payload、Deploy、Status 或 Rollback 消费者；旧部署只验证 evidence 自身并把机器身份写回 manifest。
- `test_manage_agentbase.ps1` 通过：新 schema 9 manifest 不含 routing evidence，Validate 和 Deploy 结果也不投影该身份；schema 7 published 与 schema 8 deployed 可由 Status 读取，schema 8 deployed 的实际 Rollback 通过。
- `manage_agentbase.ps1 -Action Validate` 返回 `valid:true`，没有读取 current evidence、attempt ledger 或启动模型。
- 用户授予本轮持续 Deploy 权限后，`DirectCompatibility + InstallPortableSettings` Deploy 更新 4 个受管对象；同范围 Status 返回 `managed_payload_formally_deployed:true`、gap 0。该操作没有形成版本、标签或分发资产。
