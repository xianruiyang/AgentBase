# AgentBase 当前接手状态

状态截点：2026-08-23（Asia/Shanghai）。

## 一句话状态

执行控制与 Skill 上下文生命周期第三版及后继 `SessionStart` 推理档位投影均已发布；投影行为实现提交为 `d55984a`，完整部署 Validate、实际 Publish 和发布后 Status 均通过。当前范围没有开放源码实施项，安装后的行为只需在新任务中观察。接手时已有的 Windows SWE sandbox 候选继续留在 dirty worktree，属于另一工作边界。

## 当前源码、安装与未提交边界

- 行为实现提交 `d56f794` 包含局部快速路径、同源 `active_frontiers`、`result_history_state_write_drift`、昂贵动作 preflight、四层规则失效定位、稳定候选验证时点、稀疏子代理交接、可回滚连续遮蔽实验和跨 generation 的零 Token oracle revalidation；本文件所在后继提交只更新接手状态。
- 推理档位投影提交 `d55984a` 由 `reasoning-governor` 持有 conversation-state 权威读回，DirectCompatibility 与 Plugin 的 `SessionStart(startup|resume|clear|compact)` 只投影当前 next-turn 档位；新建、清空、压缩必发，相同线程未变化的普通恢复静默。按线程哈希的 256 项临时缓存只抑制重复，不持有或设置真实档位；实际 `none` 不是缺失标记，读回失败只发送未知状态且不重试。
- 用户针对本次操作明确授权后，正式入口以 `DirectCompatibility + InstallPortableSettings` 发布 `d55984a` 所属源码，5 个受管对象发生变化；回滚备份为 `C:\Users\gzxt\.codex\backups\AgentBase-20260823-160955-347ca016`，同范围只读 Status 返回 `published:true`。
- 必须保留并排除于本版本后继提交：根 `README.md`；`development/agent-evaluation/` 的 Windows SWE sandbox 修改及 `vendor/`；`docs/requirements.md` 中 AC-062—AC-065 等评测合同工作树 hunk。不要清理、回退或把它们误归入本版本。
- Windows SWE elevated sandbox、qualification、候选模型和外部 Verifier 没有在本版本发布中执行；正式 Validate/Publish 只运行 evaluator 禁用的确定性基础设施检查。

## 当前职责与证据

- `global/AGENTS.md` 按当前有界动作决定局部快速路径、稳定候选验证时点与语义子代理默认；主代理继续拥有目标、授权、规划、正式实现、验收、Git 和发布。
- `reasoning-governor` 继续唯一负责线程 next-turn 档位查询与设置；新增 Hook 入口只消费同一读回并向模型注入 `reasoning_effort=<value>; observed, not target/user-lock.`，不替代目标档位裁决或用户固定要求。
- `global/agents/evidence.toml` 与 `experiment.toml` 唯一维护角色模型、档位和角色指令。`evidence` 只读交付稀疏决策证据；`experiment` 可在有恢复依据的隔离或精确可回滚范围修改实验代码并探明连续遮蔽问题，实验补丁不自动转正。
- `task-table-manager` 从既有 task/state/result 与关联 DCR 派生当前前沿；结构漂移只形成 advisory 和恢复入口，不自动推进状态或裁决完成。
- 正式路由 generation 为 `089AC7A5EA9521DE82F919AB6083BF31871B207979FD3010434CA78F209B56B8`：Routing 114/114、Policy 114/114、References 45/45。最终刷新为 evaluator run 0、recovered 2、oracle revalidated 1；没有对未变输入原样重采样。
- `taskctl` 102 项回归通过；路由基础设施 6 suites、22 个 PowerShell 文件、0 模型调用；部署 Validate 和 Publish 内各自的 67 项 Windows SWE 基础设施检查通过，Publish 后 Status 为 `published:true`。
- `d55984a` 的定向证据为 reasoning-governor 13/13、routing contract 114 cases 和 skill quick validation 通过；完整部署 Validate 与 Publish 各自运行 67 项 Windows SWE 基础设施检查并通过，模型 evaluator 保持禁用，没有运行 Windows SWE 九题。
- 发布只证明受管文件已安装。Codex 在任务启动时构建指令链，当前已启动任务不会追溯加载新规则；子代理选择、局部快速路径、状态写回与 preflight 的真实行为仍以新任务消费者证据为准。

## 下个对话的最小恢复步骤

1. 读取根 `README.md` 与本文件，运行 `git status --short`；保留上述 README、Windows SWE、`vendor/` 与 requirements dirty 边界，不清理、不回退、不并入无关提交。
2. 若 `d55984a` 与本文件所在提交已在私有上游，当前 `SessionStart` 投影没有开放源码实施项；不要因缺少新任务行为观察而自动重开实现。
3. 任务依赖真实安装状态时，只读运行部署说明中的 `DirectCompatibility + InstallPortableSettings Status`；当前预期为 `published:true`，不得从安装副本反推项目真源。
4. 在新任务观察：已知 owner 的局部动作是否直接闭环；长期静态取证是否选择稀疏 `evidence`；连续遮蔽试路是否选择可回滚 `experiment` 并由主代理裁决接入；昂贵动作是否先走领域 runner preflight；反例是否及时写回既有状态 owner。
5. Windows SWE sandbox 仍属于独立评测工作边界；普通仓库验证不得初始化 elevated sandbox、克隆题目、安装依赖、运行 qualification 或启动候选模型。
6. 本次 Publish 授权已经消耗；任何后续手动或正式 Codex 发布都必须重新取得当次明确同意。
