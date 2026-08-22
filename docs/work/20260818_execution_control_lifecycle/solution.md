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

任务合同可选保存 `validation_dimensions`，state 可选保存 `evidence_frontier`、`active_consumer`、`validation_case`、`latest_evidence` 与 `invalidated_source_ids`，结果以 `validation_coverage` 只声明直接覆盖的值或已证等价类。`taskctl note` 以既有 state CAS 原子更新或清空检查点；`context` 从同一任务、来源索引和交付文档投影检查点、上游与显式关联 DCR，不建立 resume 文件或第二状态源。反例改变范围或下一动作时先写回，再继续依赖工作。

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

路由账本新增 `oracle_revalidation` 来源：只接受当前 oracle 已通过、可见输入/capsule/evaluator 与一份 `oracle_violation` 失败收据精确相同、文件哈希未变的 stage；追加的 passed 收据引用原失败收据和同代 cycle，Token/耗时为零，不计入真实 evaluator 采样次数，但仍占有界总收据并参与历史、merge 和 current evidence 校验。刷新入口优先恢复或再校验 staging，不能用该机制接受身份、结构或执行失败，也不能覆盖已有 passed receipt。
