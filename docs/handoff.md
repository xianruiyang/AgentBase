# AgentBase 当前接手状态

状态截点：2026-08-23（Asia/Shanghai）。

## 一句话状态

执行控制与 Skill 上下文生命周期第四版已发布：实现提交 `ce5de0f` 在既定设计内深度优先闭合正式可用结果，并以可组合证据控制多维实现与测试扩量；独立提交 Validate、实际 Publish 和发布后 Status 均通过。当前范围没有开放源码实施项，安装后的行为只需在新任务中观察。接手时已有的 Windows SWE sandbox 候选继续留在 dirty worktree，属于另一工作边界。

## 当前源码、安装与未提交边界

- 实现提交 `ce5de0f` 新增 AC-075，并让 `execution-governor` 在上游设计、owner、契约与依赖确认后，先完成一个跨层正式可用结果；平级实现、fixture、示例和测试在该结果成立前同属横向扩量。coverage basis 只保存独立失效机制、等价依据、真实交互、代表 case、扩量触发和剩余未知；首个结果不成为新设计来源。
- 既有提交 `d56f794` 的局部快速路径、同源前沿、preflight、四层失效定位和语义子代理，以及 `d55984a` 的 `SessionStart(startup|resume|clear|compact)` 推理档位投影均继续保留；本文件所在提交只更新第四版发布记录。
- 用户针对本次操作明确授权后，正式入口以 `DirectCompatibility + InstallPortableSettings` 发布 `ce5de0f` 所属源码，7 个受管对象发生变化；回滚备份为 `C:\Users\gzxt\.codex\backups\AgentBase-20260823-190448-db62872f`，同范围只读 Status 返回 `published:true`。
- 必须保留并排除于本版本后继提交：根 `README.md`；`development/agent-evaluation/` 的 Windows SWE sandbox 修改及 `vendor/`；`docs/requirements.md` 中 AC-062—AC-065 等评测合同工作树 hunk。不要清理、回退或把它们误归入本版本。
- Windows SWE elevated sandbox、qualification、候选模型和外部 Verifier 没有在本版本发布中执行；正式 Validate/Publish 只运行 evaluator 禁用的确定性基础设施检查。

## 当前职责与证据

- `global/AGENTS.md` 按当前有界动作决定局部快速路径、稳定候选验证时点与语义子代理默认；主代理继续拥有目标、授权、规划、正式实现、验收、Git 和发布。
- `global/AGENTS.md` 的抽象维度与等价依据不再重复扩写；`execution-governor` 负责把它编译为既定设计内的正式可用结果闭环、测试编写前熔断和 coverage basis。小而廉价、owner/契约/oracle 明确且无共享未知的闭集仍直接走局部快速路径。
- `reasoning-governor` 继续唯一负责线程 next-turn 档位查询与设置；新增 Hook 入口只消费同一读回并向模型注入 `reasoning_effort=<value>; observed, not target/user-lock.`，不替代目标档位裁决或用户固定要求。
- `global/agents/evidence.toml` 与 `experiment.toml` 唯一维护角色模型、档位和角色指令。`evidence` 只读交付稀疏决策证据；`experiment` 可在有恢复依据的隔离或精确可回滚范围修改实验代码并探明连续遮蔽问题，实验补丁不自动转正。
- `task-table-manager` 从既有 task/state/result 与关联 DCR 派生当前前沿；多维裁决只复用 `verification`、`validation_dimensions`、state 检查点和 result `validation_coverage`，不新增矩阵文件、状态字段、固定 case 上限或平级虚假依赖。
- 正式路由 generation 为 `E9A8578617B9FDCED63E0B6B4BDD72220B9717F999BE6DFE4C0293B95FAD25D3`：Routing 117/117、Policy 117/117、References 46/46。最终刷新只运行 References 一次，Routing 与 Policy 各 carry-forward 一次；当前计划为 0 evaluate、3 reuse、0 blocked/pending，没有对未变输入原样重采样。
- `taskctl` 既有 102 项回归继续有效；第四版路由基础设施为 6 suites、22 个 PowerShell 文件、0 模型调用。`ce5de0f` 的独立 worktree 通过 46 项基线检查，组合工作树与 Publish 各通过 67 项 Windows SWE 基础设施检查，Publish 后 Status 为 `published:true`。
- `d55984a` 的定向证据为 reasoning-governor 13/13、routing contract 114 cases 和 skill quick validation 通过；完整部署 Validate 与 Publish 各自运行 67 项 Windows SWE 基础设施检查并通过，模型 evaluator 保持禁用，没有运行 Windows SWE 九题。
- 发布只证明受管文件已安装。Codex 在任务启动时构建指令链，当前已启动任务不会追溯加载新规则；子代理选择、局部快速路径、状态写回与 preflight 的真实行为仍以新任务消费者证据为准。

## 下个对话的最小恢复步骤

1. 读取根 `README.md` 与本文件，运行 `git status --short`；保留上述 README、Windows SWE、`vendor/` 与 requirements dirty 边界，不清理、不回退、不并入无关提交。
2. 若 `ce5de0f` 与本文件所在提交已在私有上游，当前第四版与 `SessionStart` 投影均没有开放源码实施项；不要因缺少新任务行为观察而自动重开实现。
3. 任务依赖真实安装状态时，只读运行部署说明中的 `DirectCompatibility + InstallPortableSettings Status`；当前预期为 `published:true`，不得从安装副本反推项目真源。
4. 在新任务观察：上游设计已完成时是否先深度做成一个正式可用结果，而非铺平级实现或测试；coverage basis 是否按失效机制组合证据且不把 pairwise 外推高阶交互；小而廉价闭集是否直接快速闭环。既有局部快速路径、子代理交接、runner preflight 与反例写回边界继续观察。
5. Windows SWE sandbox 仍属于独立评测工作边界；普通仓库验证不得初始化 elevated sandbox、克隆题目、安装依赖、运行 qualification 或启动候选模型。
6. 本次 Publish 授权已经消耗；任何后续手动或正式 Codex 发布都必须重新取得当次明确同意。
