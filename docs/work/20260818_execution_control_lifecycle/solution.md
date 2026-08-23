# 执行控制与 Skill 上下文生命周期：方案

## SOL-001 在旧方案继续实施前熔断失效的职责判断

- 状态: confirmed
- 解决: GAP-002
- 满足: AC-024

由 `global/AGENTS.md` 的授权与执行边界规定：职责错位或架构风险一旦会改变本次方案、复发条件、完成结论或形成同责多入口，就必须在继续依赖旧方案前说明，并返回最早失效的职责或方案重新裁决。必要修正仍按当前授权边界处理；与本次结果无关的顺带重构不因此取得授权。

## SOL-002 由跨步骤控制需要决定是否建立计划

- 状态: confirmed
- 解决: GAP-003
- 满足: AC-036

由 `global/AGENTS.md` 判断任务是否需要跨步骤保持关键不确定性、依赖、不可交换顺序、分工、验收或恢复状态；需要时模型自主建立计划，无此需要时不为形式建立。用户要求查看计划时，计划作为交付物提供，但不把用户是否说出“计划”当作内部控制判断的替代品。计划继续不得创建目标、范围或实施授权。

## SOL-003 分离 skill 选择、正文有效性和引用加载生命周期

- 状态: confirmed
- 解决: GAP-001
- 满足: AC-007, AC-041, AC-044

每个 new turn 重新根据当前请求路由 skill，不继承上轮的选择结论。已选 skill 的同一来源完整正文仍在当前有效上下文且没有已知变化时直接复用；首次选择、正文不可用或已知内容变化时才从真源完整读取。上下文压缩后重新路由，只为本轮已选 skill 补回不可用的完整 `SKILL.md`，再按当前动作加载尚不可用的必要引用；名称、摘要或历史使用记录不能替代原文，也不触发未选 skill 的批量重读。

本方案不建立持久 skill 缓存、版本账本、Hook 或每轮文件探测。当前上下文是正文可用性的 owner，宿主提供变化事实；额外缓存会形成可能过期的第二状态源，并把节省一次读取变成新的同步成本。

## SOL-004 用生命周期正反例验证质量后再比较成本

- 状态: confirmed
- 解决: GAP-001, GAP-002, GAP-003
- 满足: AC-007, AC-024, AC-036, AC-044

扩展静态和 detached Policy/ Routing oracle，至少覆盖：实施中发现架构判断失效、复杂任务未显式要求计划、简单任务不建形式计划、未压缩正文复用、压缩后补回已选 skill、压缩后不加载历史未选 skill，以及已知内容变化后的重读。先验证必要 skill 仍被选择、非触发 skill 不被选择和行为标签成立，再把消除的重复正文作为成本收益；规则存在和 token 变短都不单独证明模型行为已经改变。

## SOL-005 建立运行期下一动作的唯一控制 owner

- 状态: confirmed
- 解决: GAP-004, GAP-005
- 满足: AC-036

新增 `execution-governor`，只在多个下游共享未证前提或被新证据共同推翻、昂贵或批量验证、执行链反复失败，或原因与成本质疑会改变推进时触发。它唯一裁决当前证据前沿、首个真实消费者、失败遮蔽和继续、扩量或重裁，不保存第二份计划、任务状态或完成摘要。稳定前提的普通多步实现、单个领域故障和职责裁决仍由既有 owner 处理。

## SOL-006 把纵向闭环从软偏好投影为真实依赖

- 状态: confirmed
- 解决: GAP-004
- 满足: AC-036

`global/AGENTS.md` 只保留跨项目不变量：后续动作共享未证判断时先用实际消费者的最小路径验证，成立前不扩展下游，反例即熔断并返回所属层。`delivery-workflow` 把证明动作与首个消费者写回方案和任务投影；`task-table-manager` 只在后续任务真实消费该证据时保存为 `hard` 依赖，不按深度、序号或完成数量自行推断前沿。

## SOL-007 分离执行控制、治理、交付、任务与线程设置

- 状态: confirmed
- 解决: GAP-005, GAP-006
- 满足: AC-008, AC-009, AC-036, AC-050

`execution-governor` 只控制运行期下一动作；`change-governance` 只在根因会改变长期 owner、入口、共享契约、迁移、争议 oracle 或跨契约完成边界时升级；`delivery-workflow` 和 `task-table-manager` 分别持有阶段语义与持久任务关系；`reasoning-governor` 只读写 next-turn 配置。复杂执行的目标档位与切换价值由执行控制裁决，稳定工作仍由模型按全局规则直接判断，避免新的选择循环。

## SOL-008 用一条共享前提消费者切片验证路由与引用

- 状态: confirmed
- 解决: GAP-004, GAP-005, GAP-006
- 满足: AC-036, AC-050

在现有三阶段路由评估中加入九个任务共享测试环境、首题在候选启动前被管理员批准阻断的只读用例。Routing 应选择 `execution-governor + task-table-manager`，Policy 应识别事实优先与纵向消费者闭环，References 应加载证据前沿、失败成本、任务查询和真实依赖合同。该切片证明发现与渐进引用，不把它外推为 skill 内实际执行行为已经验证。

## SOL-009 把支持场景中的可预防模型错误纳入项目质量

- 状态: confirmed
- 解决: GAP-007
- 满足: AC-066

`docs/requirements.md` 以 AC-066 定义验收边界；`global/AGENTS.md` 只保留抽象责任：规则、skill 或工具已经适用而模型仍犯可预防错误，即把可观察行为作为系统失败，定位规则、路由、入口、反馈、状态或验证缺口。具体领域错误仍回到其 owner 修复，不把每个 UE 表象追加为全局规则，也不以规则文件通过冒充行为通过。

## SOL-010 在既有任务真源中保存证据检查点与验证边界

- 状态: confirmed
- 解决: GAP-008
- 满足: AC-036, AC-066

任务合同可选保存 `validation_dimensions`，state 可选保存 `evidence_frontier`、`active_consumer`、`validation_case`、当前 `validated_coverage`、`uncovered_dimensions`、`latest_evidence` 与 `invalidated_source_ids`，结果以 `validation_coverage` 只声明最终直接覆盖的值或已证等价类。`taskctl note` 以既有 state CAS 原子更新或清空检查点；`context` 从同一任务、来源索引和交付文档投影检查点、上游与显式关联 DCR，不建立 resume 文件或第二状态源。反例改变范围、覆盖边界或下一动作时先写回，再继续依赖工作。

## SOL-011 用最小判别维度约束验证结论

- 状态: confirmed
- 解决: GAP-008
- 满足: AC-036, AC-066

`execution-governor` 先识别会改变行为或 oracle 的维度与等价依据，选择能够区分候选机制的最小组合，不机械展开笛卡尔积；fixture、单载体或单模式通过不得外推。Delivery Workflow 分别把维度写入任务合同、当前 case 写入执行检查点、直接覆盖写入结果，保持目标、执行状态和完成证据的生命周期分离。

## SOL-012 把重复脆弱接口和工具现态诊断交给正确入口

- 状态: confirmed
- 解决: GAP-009
- 满足: AC-066

稳定外部接口因人工拼装反复失败且影响当前结果时，`execution-governor` 熔断原样重试，已有领域 runner 则改用，缺失时由 `change-governance` 裁决 runner owner；全局规则不保存领域命令语法。`source-query` 仅在当前 srcq 能力、错误、降级或恢复协议待裁时加载 `diagnostics.md`，固定工作目录、版本、对应帮助和原输入，只运行能区分解释的一次复现并分类，不把已有能力写成新需求。

## SOL-013 对已被新 oracle 接受的原结果做零 Token 再校验

- 状态: confirmed
- 解决: GAP-010
- 满足: AC-066

路由账本新增 `oracle_revalidation` 来源：只接受当前 oracle 已通过、可见输入/capsule/evaluator 与一份 `oracle_violation` 失败收据精确相同、文件哈希未变的 stage；追加的 passed 收据引用同代失败收据，或通过不可变账本哈希链引用上一代失败收据，Token/耗时为零，不计入真实 evaluator 采样次数，但仍占有界总收据并参与历史、merge 和 current evidence 校验。刷新入口优先恢复或再校验 staging，不能用该机制接受身份、结构或执行失败，也不能覆盖已有 passed receipt。

## SOL-014 在 taskctl 既有查询与生成视图中稀疏派生当前执行前沿

- 状态: confirmed
- 解决: GAP-011
- 满足: AC-069

`status` 与 `TASK_TABLE.md` 从活跃 task/state、当前关联 DCR 和结构诊断即时派生 `active_frontiers`，只展开具有非空检查点、关联 DCR 或写回漂移的任务。每项保留任务结果、修改范围、来源 ID、验证维度/case、已证覆盖、未覆盖维度、最近证据、下一动作、task/state 路径与 revision；生成视图记录 UTC 刷新时间。model 预算依次移除 DCR 正文、按完整任务单元缩减；单项仍过大时保留身份、真源、任务结果、前沿、消费者、最近证据和下一动作的有界投影，列出缩短或省略字段并给出 `context`/machine 恢复入口。机器视图保持同源结构；TASK_TABLE、status 与 context 都不是修改入口。

## SOL-015 把 `state+1` 未引用结果诊断为可恢复写回漂移

- 状态: confirmed
- 解决: GAP-012
- 满足: AC-069

结果历史在完成结构与任务身份校验后，只对 `result revision == state revision + 1` 且 state 未引用该路径的记录返回 `result_history_state_write_drift`。诊断包含 task/path/state/result/current task revision 与恢复动作，不设置 current result、不写 state、不裁决完成；结果仍适用且 task 合同未变时，相同内容重试继续使用既有 partial-write recovery；结果已失效或合同已变时，先用 CAS state note 越过旧尝试，再完成当前合同。占用路径的不同内容由 `TASK-OVERWRITE` 阻断，较早历史与已引用当前结果不误报。

## SOL-016 由 execution-governor 定义通用 preflight，领域 runner 持有实现

- 状态: confirmed
- 解决: GAP-013
- 满足: AC-070

`failure-and-cost.md` 把昂贵动作适用的输入/schema、fixture/catalog、路径/权限/依赖、runner/lifecycle、oracle 到达性、重复运行变化依据和 ready/blocked 输出定义为一次最小充分 preflight。字段按当前动作适用性选择；具体命令、检查和生命周期仍由领域正式 runner 唯一维护。缺少 runner 且人工拼装已反复失败时沿既有职责升级，不建立跨领域脚本或授权门禁。

## SOL-017 由 change-governance 按四层 trace 定位规则系统失效

- 状态: confirmed
- 解决: GAP-014
- 满足: AC-071

`causal-analysis.md` 将支持场景失败分为 `definition_missing`、`route_or_reference_missing`、`action_noncompliant` 和 `state_writeback_missing`，分别消费规范对照、Routing/References/入口 trace、实际可见输入与动作反例、state revision 与结果收据。只修正直接证据覆盖的最早 owner；后续未到达层保持未知，结构漂移不外推为语义完成。路由合同以行为标签和正/非触发用例验证发现边界，真实行为仍留给后续独立场景。

## SOL-018 把完整验证集中到稳定候选的发布前阶段

- 状态: confirmed
- 解决: GAP-015
- 满足: AC-072

全局内核要求候选稳定后验证，用户仍在补充时不启动完整、昂贵或独立模型验证；AgentBase 已有组件回归、路由评测和部署 Validate 继续作为正式入口，在用户表示准备发布后的 Publish 前阶段按最终影响范围集中调用。用户明确要求提前验证时可以执行；开发中只有能立即改变当前实现且成本低的局部检查可以提前运行，且不得由单项扩成横向门禁。候选仍在变化时已启动的昂贵验证停止扩展，不使用其不完整输出作结论。

## SOL-019 用一条全局条件替换仅覆盖机械修改的快速路径

- 状态: confirmed
- 解决: GAP-016
- 满足: AC-073

全局内核不再只按“对象和变换完整”识别机械任务，而按当前有界动作判断：owner、契约和验收明确、无共享未知且不改变职责时，直接读改验收并停止，不进入完整治理流程。routing 复用现有 `mechanical-document-edit` 与 `specified-local-implementation`，增加同一个 `local_task_fast_path` 行为标签，不另建 skill、状态或流程；契约、共享前提、职责或入口实际失效时继续由现有 delivery、execution 或 change owner 接管。

## SOL-020 用稀疏决策包和可回滚实验补丁闭合子代理交接

- 状态: confirmed
- 解决: GAP-017
- 满足: AC-068

`evidence` 和 `experiment` 的代理配置直接要求结论先行、只返回能改变主代理裁决或限定范围的非空原子项、精确定位与恢复入口；`subagent-orchestration` 统一禁止复述 capsule、过程和原始日志。`experiment` 新增连续遮蔽问题触发：在临时 worktree、临时副本或主代理明确指定且有恢复依据的精确范围，可以迭代修改代码、配置或测试并运行最小探针，直到路径、关键反例、后继约束或停止边界已足以裁决。该场景同时由 `execution-governor` 裁决遮蔽与验证成本，由 `subagent-orchestration` 承担委派交接；补丁仅为待审实验资产，主代理必须复核职责、契约和 dirty 边界，选择重写、修订接入或拒绝并承担正式验证。路由合同以普通候选路径、连续遮蔽实现链和相近非触发场景覆盖该边界，不复制当前模型名或档位。

## SOL-021 在既定设计内深度优先完成首个正式可用结果

- 状态: confirmed
- 解决: GAP-018
- 满足: AC-036, AC-066

`execution-governor` 把纵向路径定义为已确认设计、owner、契约和依赖内的执行顺序：先选择一个用户可观察的正式可用结果，深度优先完成其跨层所需的生产实现、真实消费者与有效 oracle。首个结果不重新设计系统，也不形成平级任务必须继承的新架构；设计仍由原 owner 持有，真实反例才触发上游重裁。收缩的是同时展开的结果数量和证据成本，不是正式实现；一次性 mock、绕行或硬编码不能冒充闭环，也不要求为未知未来预建抽象。

首个切片成立前，只有该结果直接需要的实现、fixture、示例和测试属于纵向工作，其余平级组件与组合均是横向扩量。Delivery 与 Task 合同继续只保存原设计中的真实依赖；共享未证前提确实产生消费关系时才形成 hard dependency，单纯深度优先选择只进入既有当前消费者与下一动作检查点。

## SOL-022 用 coverage basis 形成可组合覆盖证明

- 状态: confirmed
- 解决: GAP-019
- 满足: AC-075, AC-066

`decision-frontier.md` 在组合扩量前要求一份当前动作内的紧凑 coverage basis：claim、真正改变机制/oracle/生命周期/边界的 dimensions、可复核 equivalence、真实 interactions、每个代表 case 的新增判别信息，以及 promotion 与剩余未知。覆盖由组件契约、接口接缝、真实消费者、交互代表和缺陷回归按各自证据边界组合；同名接口或代码路径不能单独证明等价，pairwise 不外推高阶交互，参数化不改变证据或成本，只有明确逐组合认证、小而廉价的闭集或无充分等价证据的高后果交互才穷举。

## SOL-023 用现有验证字段持久化组合裁决

- 状态: confirmed
- 解决: GAP-019
- 满足: AC-075

组合选择需要跨轮或多人消费时，Delivery Workflow 与 Task Table Manager 只在现有 `verification` 中紧凑保存 coverage basis，在 `validation_dimensions` 中列真正可能改变机制或 oracle 的维度，在 result `validation_coverage` 中列直接覆盖或具有可复核依据的等价类。现有 state 的 `active_consumer`、`validation_case`、`validated_coverage`、`uncovered_dimensions` 与 `next_action` 继续承担执行前沿；不新增 schema 字段、矩阵文件、CLI 语义裁判或固定 case 上限。

## SOL-024 用组合爆炸、反向高阶与小闭集场景验证触发边界

- 状态: confirmed
- 解决: GAP-018, GAP-019
- 满足: AC-036, AC-066, AC-075

`execution-governor` description 在测试代码开始生成前即可发现多类型组合扩量；路由合同新增真实组合停滞场景，要求同时选择纵向闭环、维度边界和必要引用。另以共享高阶状态证明不能机械降为 pairwise，并以低成本 2×2 明确闭集证明普通穷举仍走局部快速路径。行为标签只检查策略边界，不以关键词、固定测试数或模型输出格式代替真实执行行为。
