# AgentBase 总计划

## 1. 文档职责

本文件是 AgentBase 唯一的项目级计划入口，维护当前总体方向、跨计划决策、子计划索引、可复用实践结论和重开条件。项目长期目标与约束只由 [requirements.md](requirements.md) 定义；子计划继续拥有各自的需求、设计、任务、结果和详细证据；当前安装状态由正式部署入口读回。本文件不复制这些内容，也不产生执行授权、发布授权或完成判定。

维护项目或启动新一轮工作时，先从本文件确定所属子计划和正式 owner；已有子计划能够承接时回到该入口，只有目标、职责或生命周期确实独立时才新增子计划。子计划形成、关闭、替代或重开后同步更新本文件的入口和结论，不在 README、历史方案或进度说明中维护第二份总计划。

## 2. 总体方向

AgentBase 持续把根需求落实为可跨项目复用的 Codex 协作维护能力：有效洞察并与用户共同校准需求，以证据形成和维护权威职责，让方案、任务、消费者与验证沿目标闭环，并可靠维护规则、skill、工具、配置、部署和发布链。

所有改进依次保证需求对齐、正确性、授权、安全、可维护性和完成证据；质量同等充分时降低端到端 Token，前两者不变差时再提升速度。多个后续动作共享未证判断时，先证明共同前提并完成一个真实消费者，成立前不横向扩展；线程推理深度只按用户明确请求操作，具体边界由 [REQ-003](requirements.md#req-003-按用户明确要求管理线程推理深度) 定义，任务负担、Goal 和状态投影不产生自主查询、升降或恢复授权。

## 3. 跨计划决策合同

1. 从用户需求和项目事实识别真实差距，不从现有实现、旧测试、任务状态或工具输出反推目标。
2. 在决定行为的正式 owner 修正问题，闭合当前消费者、派生产物和旧同责决定路径；允许多个访问入口共享同一权威，不得用上下层补偿特例制造竞争性语义来源。
3. 优化模型取得充分证据并形成可靠结论的完整决策链，不以单个文件、skill、stdout、调用次数或局部预算代替总体结果。
4. 候选先使正式正常路径以最低充分机制满足质量与证据要求；新增规则、门禁、校验、状态、包装层或兜底须有当前必要性证据，既有机制按 [AC-006](requirements.md#ac-006-同一规范事实只在最低充分作用域定义一次) 与全局生命周期边界核实后裁决保留、替换或退出，不能把未找到必要性证据当作删除许可。成本确实影响当前方案选择时，才按对应子计划的适用协议比较完整决策链；总计划不维护固定数值基线或要求每轮量化，速度只在质量和上下文成本不退化时参与选择。
5. 一次只改变一个有直接证据支持的机制；机制与适用输入未变时不为期待不同结果重跑，低成本但质量、oracle 或实验边界无效的结果不得成为目标。
6. 常驻规则只吸收跨任务重复、能稳定改变动作且属于其职责的不变量；专项协议由对应 owner 维护。评测框架与本机私有题库按 [CON-008](requirements.md#con-008-真实评测数据仅保留在本机) 分离，真实题目、实际作答与逐题审计不进入 Git；源码查询与 SWE 框架的基础检查均消费合成数据，历史私有记录不作为新克隆的必需入口。
7. 项目验证只通过 Windows 主机上的正式本地入口按影响范围执行；远端仓库只承担源码与历史同步，不维护 GitHub Actions 或其他远程 CI，也不把缺少远程 CI 识别为质量缺口。

## 4. 子计划索引

已闭环条目的验证、发布和安装数据只描述其链接的交付阶段，不表示后继版本或当前宿主状态；现行合同回到对应 owner，安装状态只由正式 Status 读取。

| 子计划 | 正式入口 | 交付结论与适用边界 | 主要 owner | 跨计划依赖与消费者 | 重开或替代条件 |
| --- | --- | --- | --- | --- | --- |
| AgentBase Evo | [子计划入口](work/20260909_agentbase_content_optimization/README.md)、[需求](work/20260909_agentbase_content_optimization/requirements.md)、[设计](work/20260909_agentbase_content_optimization/design.md)、[方案](work/20260909_agentbase_content_optimization/solution.md)、[完成成本估算](work/20260909_agentbase_content_optimization/estimates.md) | 基本设计与方案已覆盖十三项需求，仍为 proposed，未实施或运行模型评测；当前授权边界见子计划 CON-001 | 拟扩展 `development/agent-evaluation`；来源管理归 `development/references` | 总计划下的独立子计划；复用 Windows SWE、路由、事件/用量及组件 runner，公共投影在原 owner 扩展 | 取得实施授权后按 SOL-011 从离线评分到真实接入、七类组件、自动循环和交付收敛组织任务；以首阶段实绩校准完成成本 |
| 首次部署原配置恢复 | [合同](requirements.md#ac-034-部署可回滚且生效入口唯一)、[正式入口](../development/codex-deployment/README.md#original-configuration-recovery) | 已实现并通过合成配置、首次/连续部署、冲突、失败回退、旧安装和独立恢复包验证；原有部署回归通过，版本与资产由[发行入口](../development/release/README.md)维护。长期原始恢复点与单次回滚分别维护，旧安装不补造历史；受管键恢复和独立入口由同一 owner 承担，Plugin 停用检查只验证合成协议，未操作真实插件 | `development/codex-deployment` | 消费既有受管资产生命周期与可移植配置；DirectCompatibility/Plugin 部署、恢复包和发行说明使用同一实现；插件停用仍归插件正式入口 | 原内容被后继升级覆盖、恢复丢失个人变更、损坏备份或恢复失败不可安全回退、受管范围扩大或发行集成变更 |
| 根需求收益边缘持续优化 | [方案](work/20260814_agentbase_requirement_edge_optimization/solution.md)、[现状与证据](work/20260814_agentbase_requirement_edge_optimization/current-state.md) | 已闭环；SOL-001—SOL-006 的长期结论已进入当前总计划 | `global/AGENTS.md`、核心 skill、路由与部署验证 | 其余当前子计划继承根需求；全局规则或 skill 变化由路由与部署合同消费 | 新的根需求差距、适用失败或跨计划共享机制 |
| Delivery Workflow 自审 | [方案](work/20260812_agentbase_delivery_workflow_self_review/solution.md) | 已闭环；作为后续十二轮审查的基线 | `delivery-workflow`、`task-table-manager` | 十二轮审查承接该基线，当前工作流与任务合同继续消费其稳定结论 | 已修机制复发或任务存储/工作流合同改变 |
| Delivery Workflow 十二轮审查 | [方案](work/20260812_agentbase_delivery_workflow_twelve_round_audit/solution.md) | 已闭环；详细轮次结论保留在该交付链 | `delivery-workflow`、`task-table-manager`、`change-governance` | 依赖自审基线；阶段、任务与治理合同变化需沿三项 skill 的消费者复核 | 阶段语义、快照、分页、影响闭合或任务合同改变 |
| Delivery Workflow 渐进上下文下一版 | [方案](work/20260816_agentbase_delivery_workflow_context_economy/solution.md)、[完成审计](work/20260816_agentbase_delivery_workflow_context_economy/completion-audit.md) | 已闭环；阶段合同按动作加载，执行使用最小语义闭包，条件引用评估支持多个 skill | `delivery-workflow`、`development/skill-routing` | 承接既有交付合同并保持 `task-table-manager` 压缩消费者职责；路由与插件分发消费新增引用 | 阶段引用误选、必要语义缺失、全量预读复发、完成审计漏项或真实任务质量/端到端成本退化 |
| Task completion-context 证据去重 | [方案](work/20260816_task_completion_context_dedup/solution.md)、[完成审计](work/20260816_task_completion_context_dedup/completion-audit.md) | 已闭环；页级目录只返回一次完整任务证据，目标以 ID 保持关系，预算与分页闭包不变 | `task-table-manager` | 承接交付链最终复核与任务结果；路由证据和部署 payload 消费变更后的 skill | 目标关联、证据字段、预算闭包或分页退化，出现真实旧格式消费者，或进一步重复已对完整决策链造成可证实成本 |
| Task 结果诊断与证据时效语义 | [方案](work/20260816_task_result_diagnostic_semantics/solution.md)、[完成审计](work/20260816_task_result_diagnostic_semantics/completion-audit.md) | 已闭环；查询诊断、结果诊断、任务 revision 陈旧和来源快照问题分层表达，后继当前证据不改写历史结果 | `task-table-manager` | 承接完成复核输出、状态与生成视图；`delivery-workflow` 状态视图、路由证据和部署 payload 消费新合同 | 分层计数与唯一候选目录不一致，旧歧义字段复现，后继结果自动抑制旧诊断，或新证据没有明确覆盖目标与当前来源 |
| Task 来源快照收据 | [方案](work/20260817_task_source_snapshot_receipt/solution.md)、[完成审计](work/20260817_task_source_snapshot_receipt/completion-audit.md) | 已闭环；最终模型预算投影决定捕获成员，模型只携带收据，新结果引用内容寻址机器快照 | `task-table-manager` | `delivery-workflow` 初始化和状态摘要消费任务存储及结果诊断；历史内联结果由只读兼容路径消费 | 收据与最终模型可见来源不一致，机器映射或逐来源诊断退化，新写入重新产生内联映射，或发现未迁移的真实写入消费者 |
| Task completion 写入合同 | [方案](work/20260817_task_completion_write_contract/solution.md)、[完成审计](work/20260817_task_completion_write_contract/completion-audit.md) | 已闭环；模型只写结果语义，CLI 以命令身份、task/state 双 CAS 和写前收据校验形成单一永久结果 | `task-table-manager` | 承接来源快照收据和模型交互面合同；历史结果、上一版完成输入与 Delivery Workflow 摘要已复核 | 语义输入重新维护机器身份，新写入能形成不可解引用收据，task/state CAS、历史读取或单向兼容退化，或发现未闭合的真实完成写入消费者 |
| Task 合同 authoring 交互面 | [方案](work/20260817_task_contract_authoring_surface/solution.md)、[完成审计](work/20260817_task_contract_authoring_surface/completion-audit.md) | 已闭环；模型 authoring 保留稳定任务 ID 与交付语义，schema/revision 由 add/update 注入，draft model/machine 同源分层 | `task-table-manager` | 永久任务、上一版完整输入、状态/结果/查询与 Delivery Workflow 消费者已复核 | 新 authoring 重新维护 schema/revision，draft model/machine 同源性、CAS、部分写、历史任务读取或单向兼容退化 |
| Task 写入回执投影 | [方案](work/20260817_task_write_receipt_projection/solution.md)、[完成审计](work/20260817_task_write_receipt_projection/completion-audit.md) | 已闭环；写入 model 回执只保留身份、revision、有效异常和截断恢复，machine/永久记录不变 | `task-table-manager` model projection | 承接模型可见输出双视图与 Task authoring/completion 写入合同；machine/永久记录消费者不变 | 写入回执新增真实程序消费者、诊断截断合同变化或完整回归失败 |
| Task 查询模型投影 | [方案](work/20260817_task_query_model_projection/solution.md)、[完成审计](work/20260817_task_query_model_projection/completion-audit.md) | 已闭环；查询按完整页、截断页和语义空结果投影，真实工作区 impact 崩溃已修复 | `task-table-manager` query model projection 与 impact parser | 承接模型可见输出双视图；machine、永久记录、图算法与 source snapshot 消费者不变 | 查询语义零丢失、分页恢复不完整、impact parser/handler 再失配或完整回归失败 |
| workctl 模型回执投影 | [方案](work/20260817_workctl_model_receipt_projection/solution.md)、[完成审计](work/20260817_workctl_model_receipt_projection/completion-audit.md) | 已闭环；protect/status/impact/render 按动作投影，baseline 语义和诊断分层一致 | `delivery-workflow` model projection | 承接模型可见输出双视图；阶段真源、machine 输出、保护快照、索引和生成视图消费者不变 | baseline machine 合同变化、诊断分层退化、impact 恢复信息丢失或完整回归失败 |
| 生成式模型导航摘要 | [方案](work/20260817_generated_model_navigation/solution.md)、[完成审计](work/20260817_generated_model_navigation/completion-audit.md) | 已闭环；语义空结果显式、零机器统计省略，任务明细与异常仍完整 | taskctl/workctl Markdown render owner | 承接模型交互面与两项 CLI model projection；machine 摘要、阶段/任务真源和历史生成物不变 | 语义空结果消失、必要任务列缺失、partial/unavailable 不可见或完整回归失败 |
| 模型可见工具输出双视图 | [方案](work/20260817_model_visible_tool_output_contract/solution.md)、[输出审计](work/20260817_model_visible_tool_output_contract/output-audit.md)、[消费者复核](work/20260817_model_visible_tool_output_contract/consumer-impact.md)、[完成审计](work/20260817_model_visible_tool_output_contract/completion-audit.md) | 已闭环；taskctl/workctl 默认模型视图只投影当前动作所需证据，显式 machine 视图保留稳定完整合同，两者由同一 canonical 计算与 owner 维护 | `global/AGENTS.md`、`task-table-manager`、`delivery-workflow` | `srcq` 提供既有模型输出成本估算实践；任务与交付消费者、路由验证和部署 payload 消费新合同；其余模型可见入口保持各自 owner，未被误标为已迁移 | 模型视图遗漏完成当前动作的必要证据、重新暴露机器信封或完整快照、machine 合同退化、预算恢复不可定位，真实 tokenizer/阅读质量比较不再成立，或其他 owner 出现可证实的同类高成本输出 |
| Workflow CLI 运行时与模型输入输出 | [需求](work/20260902_workflow_cli_runtime_and_model_io/requirements.md)、[方案](work/20260902_workflow_cli_runtime_and_model_io/solution.md)、[验证](work/20260902_workflow_cli_runtime_and_model_io/verification.md)、[完成审计](work/20260902_workflow_cli_runtime_and_model_io/completion-audit.md) | 已闭环；workctl/taskctl 由独立 Windows 运行时维护并安装为 0.1.0，model 使用短回执和按动作投影，machine 保留完整身份 | `tools/workflow-cli`、`delivery-workflow`、`task-table-manager` | 承接模型可见工具输出双视图与 Task 来源/完成合同；skill、Windows 主机准备和 Codex 部署 preflight 消费新入口 | PATH 命令身份或安装回滚失效，model 重新暴露长机器身份，短回执不能闭合完成/分页，machine 合同退化，或宿主运行时与项目版本漂移 |
| 模型交互面与资产职责 | [方案](work/20260817_model_interaction_surface_contract/solution.md)、[交互审计](work/20260817_model_interaction_surface_contract/interaction-audit.md)、[完成审计](work/20260817_model_interaction_surface_contract/completion-audit.md) | 已闭环；模型读取、模型修改、机器表示和派生物先按事实 owner、消费者、当前责任与生命周期裁决，Event Logger 已接入同源 model/machine 恢复视图 | `global/AGENTS.md`、`delivery-workflow`、`task-table-manager`、`codex-event-logger` | 承接工具双视图并把上位合同扩展到模型阅读或修改的文件；路由、独立评估和部署候选验证消费新合同 | 模型读取面遗漏必要证据、模型修改需同步多个同责位置、生成物反向成为真源、Event Logger 恢复或 machine 兼容退化，或新 owner 出现有直接证据的同类缺口 |
| 常驻模型上下文与恢复面收敛 | [方案](work/20260817_persistent_context_surface/solution.md)、[读取面审计](work/20260817_persistent_context_surface/context-surface-audit.md)、[验证](work/20260817_persistent_context_surface/verification.md)、[完成审计](work/20260817_persistent_context_surface/completion-audit.md) | 已闭环；全局同责规则合并，12 个 description 保持预加载边界，handoff 仍为当前恢复索引；5.0% Token 收益只属于原 11-skill 候选历史样本 | `global/AGENTS.md`、12 个项目 skill、`docs/handoff.md`、`development/skill-routing` | 承接模型交互面合同；Routing、Policy、References 与部署 Validate 消费候选，该阶段安装证据只覆盖当时基线，现态另由 Status 读取 | 严格路由、条件引用、全局行为或恢复充分性退化，description 重新承载正文执行细节，handoff 复制历史展开，或同 tokenizer 成本收益不再成立 |
| Agent 与 Skill 指令面收敛 | [现状与证据](work/20260818_agent_instruction_surface/current-state.md)、[方案](work/20260818_agent_instruction_surface/solution.md)、[验证](work/20260818_agent_instruction_surface/verification.md)、[完成审计](work/20260818_agent_instruction_surface/completion-audit.md) | 已闭环并于 2026-08-18 发布；角色语义唯一 owner、taskctl 动作族引用与中文帮助完成，Routing 93/93、Policy 93/93、References 26/26、部署 Validate 与发布后 Status 通过；默认 Luna/max 保持证据边界 | `global/agents/`、`task-table-manager`、部署与路由验证 | 承接中文单语、常驻上下文、模型交互面与 Delivery Workflow 渐进上下文；部署 payload、References 评估和 CLI 消费新合同 | 角色正文再次形成第二 owner、动作引用过选或漏选、CLI 合同退化、独立评估失败，或取得足以裁决默认子代理组合的真实质量与成本证据 |
| 验证溯源、CLI 帮助与 Git 基线 | [需求](work/20260818_validation_provenance_cli_git/requirements.md)、[现状](work/20260818_validation_provenance_cli_git/current-state.md)、[方案](work/20260818_validation_provenance_cli_git/solution.md)、[验证](work/20260818_validation_provenance_cli_git/verification.md)、[完成审计](work/20260818_validation_provenance_cli_git/completion-audit.md) | 已闭环；失败尝试有界收据、相同输入一次带理由重试、taskctl 二级帮助和私有远端源码身份均完成；核心实现提交 `5814dca` 已同步并于 2026-08-18 发布 | `development/skill-routing`、`task-table-manager` parser、Git 历史 | 承接 Agent 与 Skill 指令面候选及其显式路由研究；CLI 使用者与研究恢复流程消费 evidence，部署只消费确定性 payload 合同；该交付阶段使用 `DirectCompatibility + InstallPortableSettings`，不据此断言当前安装状态 | 研究成功 evidence 找不到通过收据、同输入可无理由重复、参数帮助再次缺失、提交/远端不一致或未来更换正式 evidence owner |
| Agent 档位与验证尝试生命周期 | [历史交付链](work/20260819_agent_attempt_lifecycle/solution.md)、[历史验证](work/20260819_agent_attempt_lifecycle/verification.md)、[历史审计](work/20260819_agent_attempt_lifecycle/completion-audit.md) | 当前角色与嵌套合同由 [AC-068](requirements.md#ac-068-主代理定稿与四个自定义角色分工) 和 [编排 skill](../skills/subagent-orchestration/SKILL.md) 定义；具体模型与档位由角色配置维护。历史三角色验证不证明四角色及新委派边界；运行时可见也不等于真实行为已验证 | `global/AGENTS.md`、`global/agents/`、`subagent-orchestration`、`development/skill-routing` | 需求、角色配置、编排、触发用例和部署 payload 沿同一合同消费；安装状态只由正式 Status 读取，不从历史部署结论外推 | 固定角色继承主代理 profile、experiment 的按需取证被额外授权门槛阻断、evidence/operator 创建子代理、experiment 创建其他角色或超出实验范围，或困难/视觉实验角色不满足其契约时重开对应行为验证 |
| 第三语义执行子代理 | [方案](work/20260826_operator_subagent/solution.md)、[验证](work/20260826_operator_subagent/verification.md)、[完成审计](work/20260826_operator_subagent/completion-audit.md) | 已闭环并于 2026-08-26 发布；`operator` 处理合同已确认但难脚本化的有界执行，既有状态观察归 `evidence`，操作探路归 `experiment`；正式 generation `C0241F…2F76` 为 0 evaluate/3 reuse，Validate/Publish 与 Status 通过 | `global/agents/operator.toml`、`global/AGENTS.md`、`subagent-orchestration`、部署生命周期与路由 evidence | 承接 AC-068 与既有双角色合同；主代理继续拥有目标、设计、正式验收、Git、发布和完成；评测能力投影已消费三角色 | 三角色边界重叠、operator 吸收未知或例外、可脚本化工作被无收益委派、构建失败后自行修复/重跑，或真实任务证明 Luna max 的质量成本不成立时重开 |
| 增量独立路由验证 | [需求](work/20260820_incremental_routing_evidence/requirements.md)、[设计](work/20260820_incremental_routing_evidence/design.md)、[现状](work/20260820_incremental_routing_evidence/current-state.md)、[方案](work/20260820_incremental_routing_evidence/solution.md)、[验证](work/20260820_incremental_routing_evidence/verification.md)、[完成审计](work/20260820_incremental_routing_evidence/completion-audit.md) | 2026-09-03 完成职责收敛：隔离 evaluator、增量 planner、收据与恢复继续用于显式路由研究；两次真实候选刷新暴露模型语义门禁漂移后，Validate/Deploy/Status 已退出 evidence 消费，schema 9 只记录 payload 与受管资产生命周期 | `development/skill-routing` 研究基础设施、`development/codex-deployment` schema 9 | 明确研究路由行为或诊断已发生失败时才刷新模型 evidence；部署只消费 `validate_contract.ps1`、payload 指纹、lifecycle 与回滚事实，schema 8 及更早历史保持可读回滚 | 阶段身份漏绑、研究测试意外调用模型、复用来源链断裂、runner 加载真实 Codex home，或部署再次要求无运行消费者的模型选择时重开 |
| AgentBase Windows SWE 最终评测集 | [当前框架入口](../development/agent-evaluation/README.md)、[隐私边界](requirements.md#con-008-真实评测数据仅保留在本机) | 受信任本地候选与独立 Verifier 工作区保持现行运行模型；Git 只分发框架、schema 与合成基础测试，真实 corpus、题目适配与逐题证据留本机。缺少私有题库不阻断框架验证，也不产生自动下载或模型运行授权 | `development/agent-evaluation`、共享 shell 环境策略、治理任务 T002/T003 | 日常部署不消费该组件回归或真实题目；本地题库由显式 corpus 入口消费，路由、MCP 和 QQ 由各自 owner 取证 | corpus/framework/patch/恢复合同改变，确定性回归失败，或用户显式授权逐题 oracle/model 评测时重开相应工作 |
| Windows sandbox 宿主所有权修复 | [需求](work/20260822_windows_sandbox_ownership_repair/requirements.md)、[设计](work/20260822_windows_sandbox_ownership_repair/design.md)、[现状](work/20260822_windows_sandbox_ownership_repair/current-state.md)、[方案](work/20260822_windows_sandbox_ownership_repair/solution.md)、[验证](work/20260822_windows_sandbox_ownership_repair/verification.md)、[完成审计](work/20260822_windows_sandbox_ownership_repair/completion-audit.md) | 已闭环并发布；`windows.sandbox` 从 portable source 移除并迁移为 `transferred`，Publish 为 changed 0，宿主保持 `unelevated`，发布后 formal Status gap 0；最终评测现已退出独立 sandbox owner | `global/config.toml`、部署 managed-asset lifecycle、目标宿主/Codex UI | 根发布需求 AC-032/AC-047 继续消费；普通 Codex 与最终评测均不从 portable source 选择或初始化 Windows 后端 | portable source 再次拥有 Windows 后端、发布覆盖宿主值、迁移收据丢失，或发布后 Status 再有 lifecycle gap |
| 推理深度生命周期 | [历史方案](work/20260818_reasoning_effort_lifecycle/solution.md)、[历史验证](work/20260818_reasoning_effort_lifecycle/verification.md)、[历史审计](work/20260818_reasoning_effort_lifecycle/completion-audit.md) | 旧自主档位合同已由 [REQ-003](requirements.md#req-003-按用户明确要求管理线程推理深度) 替代；[reasoning-governor](../skills/reasoning-governor/SKILL.md) 只处理用户明确请求，SessionStart 只投影观测值。历史行为结果保留原适用范围，不证明新合同行为 | `global/AGENTS.md`、`reasoning-governor` | `delivery-workflow`、`task-table-manager`、上下文投影、静态路由合同及部署 payload 消费明确请求边界；模型研究仅在显式授权范围进行 | 无用户请求仍查询、选择、升降或恢复，状态投影被当作授权，用户固定要求被覆盖，或 next-turn 读回及 IPC 退化 |
| 执行控制与 Skill 上下文生命周期 | [历史现状](work/20260818_execution_control_lifecycle/current-state.md)、[历史方案](work/20260818_execution_control_lifecycle/solution.md)、[历史验证](work/20260818_execution_control_lifecycle/verification.md)、[历史审计](work/20260818_execution_control_lifecycle/completion-audit.md) | 保留既有正常路径、替换闭环和证据前沿机制；现行全局规则及治理引用区分需求与事实、新增必要性与删除证据、访问入口与语义权威、关键未知与已证失效。第六版历史行为结果不外推为本次措辞修订的行为验证 | `global/AGENTS.md`、`execution-governor`、`change-governance`、`delivery-workflow`、`task-table-manager`、`development/skill-routing` | 继续消费既定设计、活动消费者和适用验证时点；不新增 skill、状态字段、CLI、影响账本或硬门禁，候选安装关系由正式 Status 单独确认 | 真实任务出现未查清即删除、合并合法访问入口、让风险或建议触发无界重裁，或替换与证据边界退化时重开 |
| 开发环境与门禁治理 | [需求](work/20260830_development_environment_governance/requirements.md)、[现状与证据](work/20260830_development_environment_governance/current-state.md)、[方案](work/20260830_development_environment_governance/solution.md)、[任务表](work/20260830_development_environment_governance/TASK_TABLE.md) | T001—T006 已闭环：受信任本地候选/Verifier、旧安全生命周期退出、跨组件现状、无消费者残留清理和最终验证均完成；旧 ACL 保护的 4 个宿主目标经用户明确授权的一次管理员清理后退出。该阶段 AGENTS/skill 与子代理容量曾部署并读回一致，当前合同和安装关系另查正式 owner；部署入口于 2026-09-04 改为只让选定交付模式与 `InstallPortableSettings` 实际消费的来源阻断 Status/Deploy，正式 Validate 仍检查所选模式的完整候选；T007 仍保留 medium/xhigh“声称派发、0 spawn、空 wait”的 blocked 证据 | `development/agent-evaluation`、`global/config.toml`、`global/AGENTS.md`、`subagent-orchestration`、`development/codex-deployment`、本子计划任务表 | 承接 Windows SWE 重开、Agent/Skill 指令面与执行控制；部署只消费当前确定性入口，不重新引入旧 sandbox 状态、permission probe 或未选择来源门禁 | AGENTS/skill、容量或部署来源范围再次改变时重验对应合同；客户端出现正式结构化机制且用户重新授权高级方案时才重开 T007；评测环境只在当前受信任本地合同或保留机械边界退化时重开 |
| Source Query Gateway | [工具入口](../tools/srcq/README.md)、[研究框架](../development/source-query-gateway/README.md) | 工具源码、CLI 合同与安装状态由组件真源和正式 Status 持有；真实题库、逐题报告、历史研究计划与任务状态只留本机，Git 不携带标准答案或实际作答。框架验证使用独立合成数据，历史模型收益不外推为当前能力 | `tools/srcq`、`development/source-query-gateway`、`source-query` | 复用外部 rg/ast-grep；共享查询、缓存、图和输出 owner，各语言只适配 AST/静态类型/callable；C++/C# 解析编译范围，Node/Cargo/Go/Python 只读解析本地项目引用；快速候选不足时才渐进消费 LSP Companion | 关系大结果同快照短句柄、Java 等其余语言项目元数据和真实隔离模型收益仍开放；动态/重载/trait/interface/宏或生成代码保持 unknown；外部根漏扫、候选误报精确全集、适配机械扩量，或既有分页/AST/release/install 合同退化时重开 |
| VS Code LSP MCP Companion | [组件方案](../mcp/vscode-lsp-mcp/PLAN.md)、[当前组件入口](../mcp/vscode-lsp-mcp/README.md) | 0.2.0 候选已重开：C/C++ 默认执行有界工作区 token 扫描与逐候选身份核验，支持无需 glob 的 `scopePaths` 和显式 `auto/scoped/provider` 分流；全局 Provider 最长 300 秒且不会被默认路径隐式启动。组件开发门禁通过；真实 VS Code Stage B 仍被宿主 `vscode-updating` 互斥锁阻断在启动前，尚未发布、安装或完成 release 验证 | `mcp/vscode-lsp-mcp` | Source Query Gateway 消费快速完整引用、显式范围和 Provider 分流；当前安装仍是既有 release，不得把源码候选能力视为已生效 | Stage B/正式 release 门禁取得有效环境证据并经用户另行授权发布；安全边界、Provider 协议、公开工具或发布生命周期再次改变 |
| 代码搜索早期改进 | `../development/code-search-workflow-improvement-plan.md`（本机历史） | 已由 Source Query Gateway 替代，只保留迁移前证据 | 无当前运行 owner | 迁移证据由 Source Query Gateway 保留；没有当前执行消费者 | 仅作证据追溯，不重新启用旧 skill/sgy 入口 |

## 5. 2026-08-16 实践结论

本节至第 10 节只保留历史发现、适用边界和证据入口，供需要追溯决策的维护者按需读取。当前执行仍消费第 2—3 节、根需求及各组件/skill 的正式合同；历史模型、验证顺序、版本和安装结论不作为当前规范或运行状态，也不产生重跑授权。

Source Query Gateway 历史受测比较仅供原宿主追溯，不作为当前候选认证。逐题审计与原始运行按 CON-008 保留在本机；共享源码仅提供[研究框架](../development/source-query-gateway/README.md)和[本地历史校验入口](../development/source-query-gateway/history/README.md)，当前成本优先级由根需求定义，不从单次结果生成通用阈值。

同日交付链实践分别确认了按动作加载阶段合同、同一证据多目标引用去重、任务结果与来源时效分层的价值。证据分别见[渐进上下文审计](work/20260816_agentbase_delivery_workflow_context_economy/completion-audit.md)、[完成上下文去重审计](work/20260816_task_completion_context_dedup/completion-audit.md)和[诊断语义审计](work/20260816_task_result_diagnostic_semantics/completion-audit.md)；当前行为与字段由 `delivery-workflow`、`task-table-manager` 及其工具 owner 维护。

## 6. 2026-08-17 模型可见输出实践结论

该轮把工具输出从统一序列化转向按消费者动作投影，并保留同源的完整机器表示。受测样本、Token 对照和恢复边界见[输出审计](work/20260817_model_visible_tool_output_contract/output-audit.md)；它支持按决策充分性比较表示，不证明任意短格式或固定压缩比例更优。当前协议由各工具 owner 维护，全局只持有模型交互面的通用边界。

## 7. 2026-08-17 模型交互面实践结论

该轮将模型读取、模型修改、机器事实与派生产物的职责分别接入交付文档、任务资产和 Event Logger。实际效果及环境边界见[交互审计](work/20260817_model_interaction_surface_contract/interaction-audit.md)，不外推为尚未接入消费者的结果。

后继来源快照实践揭示了“收据声称读过实际未展示内容”的风险；生成导航实践区分了必要语义零与可省略的机器默认值。证据分别见[来源快照审计](work/20260817_task_source_snapshot_receipt/completion-audit.md)和[生成导航审计](work/20260817_generated_model_navigation/completion-audit.md)。当前收据、字段、分页及恢复协议回到对应 CLI 与 skill 查询，本节不复制维护。

## 8. 2026-08-17 常驻读取面实践结论

该轮比较了全局规则、skill description 与恢复入口的不同读取时点，受测合并项、成本与诊断边界见[读取面审计](work/20260817_persistent_context_surface/context-surface-audit.md)和[验证记录](work/20260817_persistent_context_surface/verification.md)。

当时串联 Routing/Policy/References 与部署校验的验证顺序已不作为日常要求；当前静态验证与显式模型研究由[路由说明](../development/skill-routing/README.md)分开管理，[部署入口](../development/codex-deployment/README.md)不消费模型 evidence。接手所需的 Git、安装与运行时角色状态按 [handoff](handoff.md) 即时取证，不在本节保存当前版本或安装快照。

## 9. 2026-08-18 推理深度生命周期实践结论

历史实验区分了线程配置、next-turn 生效与自动续轮，并暴露固定尾部窗口遗漏配置的读取问题；原实验条件与证据保留在[验证记录](work/20260818_reasoning_effort_lifecycle/verification.md)。

当时“未固定即可自主选择、查询、切换”的策略已由 [REQ-003](requirements.md#req-003-按用户明确要求管理线程推理深度) 替代，不再承担当前执行指导。当前操作与状态投影只消费 [reasoning-governor](../skills/reasoning-governor/SKILL.md)；`SessionStart` 的观测值不构成进一步操作授权，历史切换收益也不恢复旧权限。

## 10. 2026-08-18 执行控制与 Skill 上下文生命周期实践结论

该交付链先后发现了有效 skill 正文重复读取、软纵向优先未阻止扩量、局部失败被后继动作遮蔽，以及同责替换保留旧路径与旧检查等问题。原始反例、历次候选及验证范围保留在[现状](work/20260818_execution_control_lifecycle/current-state.md)、[方案](work/20260818_execution_control_lifecycle/solution.md)、[验证](work/20260818_execution_control_lifecycle/verification.md)和[完成审计](work/20260818_execution_control_lifecycle/completion-audit.md)。

2026-09-03—04 的替换、评审收敛、合法无动作和同线程连续替换结果只覆盖当时受测候选与场景；“第六版最终 payload”是该阶段结论，不锁定后继规则，也不证明当前四角色或其嵌套行为。当前正常路径、未知核实、替换退出和评审边界由[全局规则](../global/AGENTS.md)、[执行控制](../skills/execution-governor/SKILL.md)及[治理 skill](../skills/change-governance/SKILL.md)维护。

## 11. 重开与维护

- 新需求或新证据先定位到现有子计划和 owner；能由现有入口承接时不新增计划。
- 跨计划共享职责、根需求或正式入口变化时，更新本文件的方向、索引和影响结论；专项细节只写回对应子计划。
- 已关闭子计划出现适用失败时重开其交付链或建立明确后继，不静默改写历史完成证据。
- 发布、远端外部写入和其他高风险动作始终按当前用户授权与项目规则裁决；历史子计划中的授权不向当前动作继承。
- 没有新失败、协议变化、新消费者或可重复共享机制时保持收益边缘，不为计划持续存在而制造任务。
