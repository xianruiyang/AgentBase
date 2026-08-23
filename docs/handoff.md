# AgentBase 当前接手状态

状态截点：2026-08-23（Asia/Shanghai）。

## 一句话状态

`srcq 0.4.3` 六位环形续页句柄与可逆操作 `experiment` 触发版本已发布：实现提交 `518de5e`、`f4e3570` 已同步私有上游，私有 Release、真实 srcq Upgrade/doctor、正式路由 evidence、部署 Validate/Publish 和发布后 Status 均通过。当前范围没有开放源码实施项，安装后的行为只需在新任务中观察。接手时已有的 Windows SWE sandbox 候选继续留在 dirty worktree，属于另一工作边界。

## 当前源码、安装与未提交边界

- 实现提交 `ce5de0f` 新增 AC-075，并让 `execution-governor` 在上游设计、owner、契约与依赖确认后，先完成一个跨层正式可用结果；平级实现、fixture、示例和测试在该结果成立前同属横向扩量。coverage basis 只保存独立失效机制、等价依据、真实交互、代表 case、扩量触发和剩余未知；首个结果不成为新设计来源。
- 既有提交 `d56f794` 的局部快速路径、同源前沿、preflight、四层失效定位和语义子代理，以及 `d55984a` 的 `SessionStart(startup|resume|clear|compact)` 推理档位投影均继续保留；当前记录以最新发布证据为准。
- `518de5e` 在 continuation registry owner 中实现 `q1`—`q999999` 环形分配、环形年龄淘汰和旧七位句柄过渡读取，并闭合 YAML emitter 的真实性质反例；`f4e3570` 把 `experiment` 改为按可逆实际操作的信息增益选择，同时收紧 delivery/task-table/change-governance 的正负路由边界。
- 私有 `srcq-v0.4.3` 指向 `f4e35707fcb69e69ed9583bf108a96727f8d5087`；两次 clean archive SHA-256 均为 `9d0b9569a4c19e6e1c20cc5e9625d882a5e9acfeabde93e6ee89533fdcc9e52c`。Release 下载 Upgrade 后 Status 为 `ready:true`、完整性 verified、PATH 条目 1，已安装 `srcq 0.4.3`、doctor、scc doctor 与 `q921 → q922` 续页通过。
- 用户针对本次操作明确授权后，正式入口以 `DirectCompatibility + InstallPortableSettings` 发布当前源码，10 个受管对象发生变化；回滚备份为 `C:\Users\gzxt\.codex\backups\AgentBase-20260823-211434-11afc187`，同范围只读 Status 返回 `published:true`。
- 必须保留并排除于本版本后继提交：根 `README.md`；`development/agent-evaluation/` 的 Windows SWE sandbox 修改及 `vendor/`；`docs/requirements.md` 中 AC-062—AC-065 等评测合同工作树 hunk。不要清理、回退或把它们误归入本版本。
- Windows SWE elevated sandbox、qualification、候选模型和外部 Verifier 没有在本版本发布中执行；正式 Validate/Publish 只运行 evaluator 禁用的确定性基础设施检查。

## 当前职责与证据

- `global/AGENTS.md` 按当前有界动作决定局部快速路径、稳定候选验证时点与语义子代理默认；主代理继续负责目标与交付。
- `global/AGENTS.md` 的抽象维度与等价依据不再重复扩写；`execution-governor` 负责把它编译为既定设计内的正式可用结果闭环、测试编写前熔断和 coverage basis。小而廉价、owner/契约/oracle 明确且无共享未知的闭集仍直接走局部快速路径。
- `reasoning-governor` 继续唯一负责线程 next-turn 档位查询与设置；新增 Hook 入口只消费同一读回并向模型注入 `reasoning_effort=<value>; observed, not target/user-lock.`，不替代目标档位裁决或用户固定要求。
- `global/agents/evidence.toml` 与 `experiment.toml` 唯一维护角色模型、档位和角色指令。`evidence` 只读交付稀疏决策证据；`experiment` 在可逆操作能低成本取得裁决证据时适用，不要求任务陌生、先穷尽静态取证或没有初步路径。实验补丁仍须由主代理按正式 owner 和契约重写、修订接入或拒绝。
- `task-table-manager` 从既有 task/state/result 与关联 DCR 派生当前前沿；多维裁决只复用 `verification`、`validation_dimensions`、state 检查点和 result `validation_coverage`，不新增矩阵文件、状态字段、固定 case 上限或平级虚假依赖。
- 正式路由 generation 为 `94F0F1833032D2C480AB2E126544842C2907ACBFCC8296F53E350DD877BF4D17`：119 cases、78 strict routing、24 strict references，13/13 skills 有正向与非触发覆盖；当前计划为 0 evaluate、3 reuse、0 blocked/pending。最后一次刷新只运行 Routing 与 References，上一代同身份 Policy 由 `staged_carry_forward` 迁移，没有重复模型调用。
- `taskctl` 既有 102 项回归继续有效；当前路由基础设施为 6 suites、22 个 PowerShell 文件、0 模型调用。srcq 全 workspace test/build/lint/fmt、安装视图与 Release 安装合同通过；部署 Validate 与 Publish 各通过 67 项 Windows SWE 基础设施检查，模型 evaluator 保持禁用。
- `d55984a` 的定向证据为 reasoning-governor 13/13、routing contract 114 cases 和 skill quick validation 通过；完整部署 Validate 与 Publish 各自运行 67 项 Windows SWE 基础设施检查并通过，模型 evaluator 保持禁用，没有运行 Windows SWE 九题。
- 发布只证明受管文件已安装。Codex 在任务启动时构建指令链，当前已启动任务不会追溯加载新规则；子代理选择、局部快速路径、状态写回与 preflight 的真实行为仍以新任务消费者证据为准。

## 下个对话的最小恢复步骤

1. 读取根 `README.md` 与本文件，运行 `git status --short`；保留上述 README、Windows SWE、`vendor/` 与 requirements dirty 边界，不清理、不回退、不并入无关提交。
2. 若 `518de5e`、`f4e3570` 与本文件所在提交已在私有上游，当前 `srcq 0.4.3`、可逆操作 Experiment、第四版执行控制与 `SessionStart` 投影均没有开放源码实施项；不要因缺少新任务行为观察而自动重开实现。
3. 任务依赖真实安装状态时，只读运行部署说明中的 `DirectCompatibility + InstallPortableSettings Status`；当前预期为 `published:true`，不得从安装副本反推项目真源。
4. 在新任务观察：已有初步实现方向但可逆操作能显著降低串行试错时是否选择 `experiment`；一次便宜定向循环是否仍由主代理闭环；上游设计已完成时是否先深度做成正式可用结果；`srcq more` 是否只把当前 spool 句柄视为临时游标。真实反例再按对应子计划重开。
5. Windows SWE sandbox 仍属于独立评测工作边界；普通仓库验证不得初始化 elevated sandbox、克隆题目、安装依赖、运行 qualification 或启动候选模型。
6. 本次 Publish 授权已经消耗；任何后续手动或正式 Codex 发布都必须重新取得当次明确同意。
