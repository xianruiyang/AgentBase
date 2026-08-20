# AgentBase 总计划

## 1. 文档职责

本文件是 AgentBase 唯一的项目级计划入口，维护当前总体方向、跨计划决策、子计划索引、可复用实践结论和重开条件。项目长期目标与约束只由 [requirements.md](requirements.md) 定义；子计划继续拥有各自的需求、设计、任务、结果和详细证据；当前安装状态由正式部署入口读回。本文件不复制这些内容，也不产生执行授权、发布授权或完成判定。

维护项目或启动新一轮工作时，先从本文件确定所属子计划和正式 owner；已有子计划能够承接时回到该入口，只有目标、职责或生命周期确实独立时才新增子计划。子计划形成、关闭、替代或重开后同步更新本文件的入口和结论，不在 README、历史方案或进度说明中维护第二份总计划。

## 2. 总体方向

AgentBase 持续把根需求落实为可跨项目复用的 Codex 协作维护能力：有效洞察并与用户共同校准需求，以证据形成和维护权威职责，让方案、任务、消费者与验证沿目标闭环，并可靠维护规则、skill、工具、配置、部署和发布链。

所有改进依次保证需求对齐、正确性、授权、安全、可维护性和完成证据；质量同等充分时降低端到端 Token，前两者不变差时再提升速度。有效规划后优先沿当前目标链形成最近的可验证闭环；用户固定的思考深度在其范围内优先，未固定时随真实不确定性、后果、可逆性和验证负担调整，不按任务形式或 Goal 状态固定。

## 3. 跨计划决策合同

1. 从用户需求和项目事实识别真实差距，不从现有实现、旧测试、任务状态或工具输出反推目标。
2. 在决定行为的正式 owner 修正问题，闭合当前消费者、派生产物和旧同责路径；不得用上下层补偿特例制造平行入口。
3. 优化模型取得充分证据并形成可靠结论的完整决策链，不以单个文件、skill、stdout、调用次数或局部预算代替总体结果。
4. 候选先通过质量与证据门禁；成本确实影响当前方案选择时，才按对应子计划的适用协议比较完整决策链，总计划不维护固定数值基线或要求每轮量化。速度只在质量和上下文成本不退化时参与选择。
5. 一次只改变一个有直接证据支持的机制；机制与适用输入未变时不为期待不同结果重跑，低成本但质量、oracle 或实验边界无效的结果不得成为目标。
6. 常驻规则只吸收跨任务重复、能稳定改变动作且属于其职责的不变量；专项协议、样本、原始运行和审计保留在对应子计划或 `development/`。
7. 项目验证只通过 Windows 主机上的正式本地入口按影响范围执行；远端仓库只承担源码与历史同步，不维护 GitHub Actions 或其他远程 CI，也不把缺少远程 CI 识别为质量缺口。

## 4. 子计划索引

| 子计划 | 正式入口 | 当前结论 | 主要 owner | 跨计划依赖与消费者 | 重开或替代条件 |
| --- | --- | --- | --- | --- | --- |
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
| 模型交互面与资产职责 | [方案](work/20260817_model_interaction_surface_contract/solution.md)、[交互审计](work/20260817_model_interaction_surface_contract/interaction-audit.md)、[完成审计](work/20260817_model_interaction_surface_contract/completion-audit.md) | 已闭环；模型读取、模型修改、机器表示和派生物先按事实 owner、消费者、当前责任与生命周期裁决，Event Logger 已接入同源 model/machine 恢复视图 | `global/AGENTS.md`、`delivery-workflow`、`task-table-manager`、`codex-event-logger` | 承接工具双视图并把上位合同扩展到模型阅读或修改的文件；路由、独立评估和部署候选验证消费新合同 | 模型读取面遗漏必要证据、模型修改需同步多个同责位置、生成物反向成为真源、Event Logger 恢复或 machine 兼容退化，或新 owner 出现有直接证据的同类缺口 |
| 常驻模型上下文与恢复面收敛 | [方案](work/20260817_persistent_context_surface/solution.md)、[读取面审计](work/20260817_persistent_context_surface/context-surface-audit.md)、[验证](work/20260817_persistent_context_surface/verification.md)、[完成审计](work/20260817_persistent_context_surface/completion-audit.md) | 已闭环；全局同责重复规则合并，11 个 description 保持预加载边界，handoff 收敛为当前恢复索引；常驻面在同质量门禁后减少 5.0% tokens | `global/AGENTS.md`、11 个项目 skill、`docs/handoff.md`、`development/skill-routing` | 承接模型交互面合同；Routing、Policy、References 与部署 Validate 消费候选，真实 Codex 仍停留在已发布基线 | 严格路由、条件引用、全局行为或恢复充分性退化，description 重新承载正文执行细节，handoff 复制历史展开，或同 tokenizer 成本收益不再成立 |
| Agent 与 Skill 指令面收敛 | [现状与证据](work/20260818_agent_instruction_surface/current-state.md)、[方案](work/20260818_agent_instruction_surface/solution.md)、[验证](work/20260818_agent_instruction_surface/verification.md)、[完成审计](work/20260818_agent_instruction_surface/completion-audit.md) | 已闭环并于 2026-08-18 发布；角色语义唯一 owner、taskctl 动作族引用与中文帮助完成，Routing 93/93、Policy 93/93、References 26/26、部署 Validate 与发布后 Status 通过；默认 Luna/max 保持证据边界 | `global/agents/`、`task-table-manager`、部署与路由验证 | 承接中文单语、常驻上下文、模型交互面与 Delivery Workflow 渐进上下文；部署 payload、References 评估和 CLI 消费新合同 | 角色正文再次形成第二 owner、动作引用过选或漏选、CLI 合同退化、独立评估失败，或取得足以裁决默认子代理组合的真实质量与成本证据 |
| 验证溯源、CLI 帮助与 Git 基线 | [需求](work/20260818_validation_provenance_cli_git/requirements.md)、[现状](work/20260818_validation_provenance_cli_git/current-state.md)、[方案](work/20260818_validation_provenance_cli_git/solution.md)、[验证](work/20260818_validation_provenance_cli_git/verification.md)、[完成审计](work/20260818_validation_provenance_cli_git/completion-audit.md) | 已闭环；失败尝试有界收据、相同输入一次带理由重试、taskctl 二级帮助和私有远端源码身份均完成；核心实现提交 `5814dca` 已同步并于 2026-08-18 发布 | `development/skill-routing`、`task-table-manager` parser、Git 历史 | 承接 Agent 与 Skill 指令面候选及其当前三阶段 evidence；部署 Validate、CLI 使用者与恢复流程消费结果；当前 Codex 以 `DirectCompatibility + InstallPortableSettings` 消费源码 | 当前成功 evidence 找不到通过收据、同输入可无理由重复、参数帮助再次缺失、提交/远端不一致或未来更换正式 evidence owner |
| Agent 档位与验证尝试生命周期 | [需求](work/20260819_agent_attempt_lifecycle/requirements.md)、[设计](work/20260819_agent_attempt_lifecycle/design.md)、[现状](work/20260819_agent_attempt_lifecycle/current-state.md)、[方案](work/20260819_agent_attempt_lifecycle/solution.md)、[验证](work/20260819_agent_attempt_lifecycle/verification.md)、[完成审计](work/20260819_agent_attempt_lifecycle/completion-audit.md) | 已闭环、发布并同步私有远端；候选收敛为 Luna/max 与 Sol/medium，Terra 完成受管退役；正式评估改为 Begin/Finish，活跃账本有界并链接上一周期 | `global/config.toml`、`global/agents/`、部署资产生命周期、`development/skill-routing` | 继承前两项已闭环子计划；portable settings、部署 Validate/Publish 和路由 evidence 已消费新合同；真实 Codex 以 `DirectCompatibility + InstallPortableSettings` 消费当前候选 | 角色清单或档位漂移、退役资产残留、评估可绕过 Begin、started 不再阻断、同输入或活跃周期上限失效、周期链不可恢复 |
| 增量独立路由验证 | [需求](work/20260820_incremental_routing_evidence/requirements.md)、[设计](work/20260820_incremental_routing_evidence/design.md)、[现状](work/20260820_incremental_routing_evidence/current-state.md)、[方案](work/20260820_incremental_routing_evidence/solution.md)、[验证](work/20260820_incremental_routing_evidence/verification.md)、[完成审计](work/20260820_incremental_routing_evidence/completion-audit.md) | 已闭环；分阶段 planner、用户 npm 隔离 runner、cases-only 协议、可恢复账本与统一零模型测试入口完成，当前 evidence 为 96/96/26，通过后同输入刷新为零运行 | `development/skill-routing` 阶段指纹、planner、runner、确定性测试、evidence 与 attempt ledger | 重开验证溯源和尝试生命周期的成本/复用边界；Windows bootstrap、部署 Validate/真实 Publish、P11 路由候选与后续规则/skill 维护消费结果 | 阶段身份漏绑、测试可意外调用模型、复用来源链断裂、跨代中断重复模型工作、runner 加载真实 Codex home、相同输入绕过重试或质量/Token 退化 |
| 推理深度生命周期 | [方案](work/20260818_reasoning_effort_lifecycle/solution.md)、[验证](work/20260818_reasoning_effort_lifecycle/verification.md)、[完成审计](work/20260818_reasoning_effort_lifecycle/completion-audit.md) | 已闭环；用户固定档位优先；自主控制先独立判断目标，再按决策价值查询状态、按剩余工作净收益设置；Goal 只承载续轮，长 snapshot 与双视图合同保持 | `global/AGENTS.md`、`reasoning-governor` | `delivery-workflow`、`task-table-manager`、路由三阶段 evidence 与部署 Validate 已消费新合同；真实安装状态由部署 `Status` 读取 | 用户覆盖被自主升降，内容型 skill 再次掩盖负担判断，短任务固定查询、有效读回重复查询或转换成本不能摊销，Goal 再成设置门槛，临时配置泄漏，长帧读回、双视图或宿主 IPC 退化 |
| 执行控制与 Skill 上下文生命周期 | [现状与证据](work/20260818_execution_control_lifecycle/current-state.md)、[方案](work/20260818_execution_control_lifecycle/solution.md)、[验证](work/20260818_execution_control_lifecycle/verification.md)、[完成审计](work/20260818_execution_control_lifecycle/completion-audit.md) | 已闭环；失效架构先重裁、计划按控制需要建立，skill 每轮重路由但正文只按实际失效恢复 | `global/AGENTS.md`、`development/skill-routing` | 承接常驻上下文与模型交互面合同；requirements、README、三阶段 evidence 与部署 Validate 已消费候选；真实安装状态由部署 `Status` 读取 | 未压缩重复读取复发、压缩后遗漏已选正文或批量重载历史 skill、已知变化仍沿用旧正文、计划明显错配，或架构判断失效后仍按旧方案完成 |
| Source Query Gateway | [P11 交付链](work/20260819_source_metrics_and_benchmark_tooling/requirements.md)、[P12 评估运行时交付链](work/20260820_independent_codex_evaluation_runtime/requirements.md)、[分支计划](../development/source-query-gateway/plan.md) | P0—P11 产品实施已闭环；P12 独立评估运行时已修复并以零重连、真实 scc 边界完成验证，同时确认当前 scc `@more` 不能让独立 Codex 直接形成正确续页命令；产品修正尚未获授权 | `tools/srcq`、`development/code-search-benchmark`、`source-query`、`global/AGENTS.md`、Windows bootstrap | 替代代码搜索早期方案，消费 LSP Companion 与外部 scc；部署入口、模型路由、hyperfine benchmark 和后继 srcq 分页设计消费 P11/P12 | 新查询失败、后端/协议变化、模型投影质量或成本退化、新消费者、正式产品身份残留、可重复共享缺口，或用户授权修正已确认的 scc 分页提示缺口 |
| VS Code LSP MCP Companion | [组件方案](../mcp/vscode-lsp-mcp/PLAN.md)、[当前组件入口](../mcp/vscode-lsp-mcp/README.md) | 已形成组件与受验证 Windows release；PLAN 保留架构基线，不作为开放任务表 | `mcp/vscode-lsp-mcp` | Source Query Gateway 消费其查询协议；公开工具或协议变化需回到该分支复核 | 安全边界、Provider 协议、公开工具或发布生命周期改变 |
| 代码搜索早期改进 | [历史记录](../development/code-search-workflow-improvement-plan.md) | 已由 Source Query Gateway 替代，只保留迁移前证据 | 无当前运行 owner | 迁移证据由 Source Query Gateway 保留；没有当前执行消费者 | 仅作证据追溯，不重新启用旧 skill/sgy 入口 |

当前没有已授权的开放实施项。P12 已确认一个待用户裁决的产品缺口：scc model 页尾只有 `after=<cursor>`，独立 Codex 会误形成直接 `srcq scc --after` 并失败；评估框架修复不授权顺带改变 srcq 输出合同。真实 srcq 安装升级仍由用户暂停，可能的 Codex Publish 仍需针对当次操作明确授权。

## 5. 2026-08-16 实践结论

Source Query Gateway P10 的真实代理实践表明：局部输出更短、默认预算更大或命令配方更具体，都不能证明完整任务更省；质量或实验边界无效的低成本结果不能采纳。固定预读、失败回合和错误 owner 会放大完整上下文成本，在实际 owner 修正规则适用边界比向全局规则或工具增加补偿特例更有效。最终候选保持质量并降低完整路径的上下文成本，但没有证明速度改善，因此只采纳证据直接覆盖的收益。

这些结论支持第 3 节的完整决策链、必要时的同质量比较、单机制迭代和正确 owner 原则，不把专项实验数字外推为项目固定阈值。具体计数、身份、逐调用事实和证据限制只由 [往返审计](../development/source-query-gateway/evidence/round-trip-audit-p10.md)、[日期化分支汇总](../development/source-query-gateway/plan.md#38-2026-08-16-p10-实践证据与总体计划复核)和 [完成审计](../development/source-query-gateway/evidence/completion-audit-p10.md)维护。

同日的 Delivery Workflow 后继实践把上述原则应用到流程规则自身：固定要求完整读取统一阶段合同会把未触发细则带入上下文，应在 skill 主入口按当前动作选择唯一阶段 owner；执行上下文先闭合当前目标、直接支配上游、直接依赖结果和适用约束，仅在真实不确定性、影响传播或最终复核时扩展。条件引用选择属于路由验证的共享职责，不应为每个 skill 建独立评估入口。独立评估的单次过选或漏选也不能直接证明 oracle 错误，必须先对照触发时点和当前正式 owner。具体结构证据、失败归因与完成边界保留在[后继完成审计](work/20260816_agentbase_delivery_workflow_context_economy/completion-audit.md)。

同日的任务完成复核后继实践进一步确认：同一事实对象被多个目标引用时，辅助视图应保存一次完整对象并显式表达关系，而不是把完整证据复制到每条关系中。该规范化只有在字段、关系、快照、游标和预算裁剪仍形成可解析闭包时才是有效降本；本轮真实输入的具体字节与适用边界只保留在[任务复核完成审计](work/20260816_task_completion_context_dedup/completion-audit.md)，不提升为项目固定压缩门槛。

任务结果诊断后继实践进一步确认：结果“被当前状态引用”、任务合同 revision 一致、来源快照当前和结果没有其他诊断是不同生命周期事实，辅助视图不得用一个含糊的 current/stale 计数代替。后继验证形成新的目标证据时，应以自己的 `evidence_for`、执行来源快照和直接验证明确覆盖目标；历史结果及其诊断保持不可改写，由最终模型按目标选择当前适用证据。具体字段、真实旧工作区的 8 项诊断和验证边界只保留在[诊断语义完成审计](work/20260816_task_result_diagnostic_semantics/completion-audit.md)，不把 CLI 提升为整体完成裁判。

## 6. 2026-08-17 模型可见输出实践结论

工具输出的首要合同不是“统一序列化”，而是“当前消费者下一步必须知道什么”。模型视图应先按动作投影最小充分证据，再在候选表示之间用真实 tokenizer 和可读性比较；machine 视图则保留完整、稳定、可解析的协议。两种视图必须由同一 canonical 计算和正式 owner 生成，避免为降 Token 引入第二套事实源；预算不足时裁剪完整低优先级单元并返回可定位恢复信息，不截断语义字段。具体投影、真实工作区样本、Token 对照和边界保留在[输出审计](work/20260817_model_visible_tool_output_contract/output-audit.md)，不把单次比例提升为全项目固定阈值。

## 7. 2026-08-17 模型交互面实践结论

更深层的问题不是 JSON、YAML 或 HJSON 的选择，而是把存储对象和传统工程输出误当成与消费者无关的中性载体。进入模型上下文或交给模型修改之前，应先确定事实 owner、实际消费者、当前判断或修改责任和内容生命周期：模型读取面只提供最小充分证据，模型修改面强调稳定局部边界、唯一决定位置和直接验证，机器面保持稳定完整；模型或人维护的语义真源可派生机器产物，程序维护的机器真源则通过有界投影、查询或受验证语义入口服务模型。格式只在完成这次职责投影之后用真实 Token、可读性和可定位性比较。

本轮把该上位合同接入 Delivery Workflow 的阶段 Markdown、Task Table Manager 的结构化任务资产和 Codex Event Logger 的机器日志恢复面。Event Logger 的真实 turn 证明，同一次有界事实读取可在保留恢复充分性和显式 machine 合同的同时显著减少模型上下文；具体 Token、文件操作归并和环境边界只由[交互审计](work/20260817_model_interaction_surface_contract/interaction-audit.md)维护，不提升为统一阈值或通用格式要求。`source_snapshot` 表示与插件迁移仍是独立事项，没有被该原则顺带改变。

来源快照后继实践确认：执行来源身份必须在最终模型预算投影选定后捕获，否则机器记录会声称模型读过实际已被裁掉的正文。完整 ID—指纹映射由 Task Table Manager 作为内容寻址机器资产维护，模型只读取并传递会影响完成动作的引用、成员数和完整性；机器视图在同一 owner 中展开映射并保持缺失、损坏、不完整和逐来源陈旧诊断。旧内联结果继续可读，但唯一完成入口把旧输入单向外部化，新结果不再让模型复制机器指纹。具体格式、预算场景和迁移证据只由[来源快照完成审计](work/20260817_task_source_snapshot_receipt/completion-audit.md)维护。

后继 CLI 与生成导航审计进一步确认：模型面不能机械删除所有零值。表示“当前没有候选、依赖或结果”的语义零需要显式保留，而机器信封中的计数零、`truncated:false` 和正常状态默认值可以省略；只有截断时才增加总数与精确恢复位置。写入回执、查询页和生成 Markdown 应分别由当前命令 owner 投影，不能用一个通用稀疏函数猜测字段意义。具体命令与相近非触发场景由[最终横向完成审计](work/20260817_generated_model_navigation/completion-audit.md)及本文件的四项后继索引维护。

## 8. 2026-08-17 常驻读取面实践结论

常驻规则、skill description 和接手文档虽然都会被模型读取，但读取时点与 owner 不同，不能统一按篇幅压缩：全局规则只合并同一 owner 内的重复不变量；description 只保留正文加载前会改变选择的正向、相近非触发和必要协同边界；handoff 只维护当前版本、真实安装、直接证据、未决边界和下一入口，历史展开由正式审计持有。当前平台存在相似指令、句式相近或文件接近上限都不能证明语义可删除。

候选先通过静态合同、detached Routing/Policy/References、恢复清单和部署 Validate，再使用同一 tokenizer 比较成本。具体合并项、单项 Token 和 Policy 诊断限制只保留在[读取面审计](work/20260817_persistent_context_surface/context-surface-audit.md)与[验证记录](work/20260817_persistent_context_surface/verification.md)，不提升为固定压缩比例，也不扩张到 `source_snapshot` 或插件迁移。

## 9. 2026-08-18 推理深度生命周期实践结论

推理深度设置、设置在 next turn 生效和下一轮是否自动开始是三个独立机制：线程设置入口只更新并读回 conversation state，不发送 turn；Goal 只在需要跨轮持续执行时承载续轮。因此，用户未固定档位时的自主选择不应以 Goal 为前提，用户明确固定的范围则作为更高优先约束，不能被最低充分原则或额度动机猜测覆盖。临时配置只服务当前工作，不需要任务表、Hook、Goal 字段或脚本状态形成第二真源。

长对话下的配置读回不能依赖字段位于固定尾部。当前约 19 MB 的真实 snapshot 已证明固定窗口会把存在的配置误报为不可读；有界实现应扫描真实 JSON 结构路径并忽略正文字符串中的同名文本。该工具直接供模型读取，因此默认只投影成功、操作和实际档位，完整传输、线程、host 与诊断字段保留在显式 machine 视图。具体实验、帧大小、测试和证据身份只由[验证记录](work/20260818_reasoning_effort_lifecycle/verification.md)维护。

后继实践确认，目标档位判断、当前状态查询和实际设置还具有不同成本，不能压成一句“需要变化才使用”。目标判断应在下一段实质工作前独立于领域 skill、计划和 Goal；只有状态证据能改变动作时才查询，只有实际错配且剩余工作能摊销当前轮中断、续轮等待与恢复时才设置。这样长探索不会因内容路由漏判，短任务、已有充分读回和纯设计讨论也不会承担固定工具成本；用户显式状态或设置请求仍直接触发。

## 10. 2026-08-18 执行控制与 Skill 上下文生命周期实践结论

Skill 的适用性与正文有效性是两个生命周期：每个 new turn 都应按当前请求重新路由，但 turn 边界本身不会使同一来源、仍在有效上下文且未变化的完整正文失效；上下文压缩使正文不可用时，只恢复本轮重新选中的 skill 及当前动作所缺引用。名称、摘要和历史使用记录不能代替正文，也不应触发历史 skill 的批量恢复。这样既不跳过规则，又避免用持久缓存、版本账本或每轮文件探测制造第二状态源。真实重复读取、压缩替换历史、官方渐进披露合同、Token 对照和独立用例保留在[验证记录](work/20260818_execution_control_lifecycle/verification.md)。

同一轮还明确了执行控制的两个前置边界：计划是模型为跨步骤保持关键状态而选择的控制手段，用户是否说出“计划”只影响可见交付；职责或架构证据使方案失效时，应先回到最早失效层重裁，再继续已授权实现，不能先按旧架构做完后才告知。两者与 skill 生命周期都在 `global/AGENTS.md` 的全局内核收口，专项 skill 只按触发承担领域方法。

## 11. 重开与维护

- 新需求或新证据先定位到现有子计划和 owner；能由现有入口承接时不新增计划。
- 跨计划共享职责、根需求或正式入口变化时，更新本文件的方向、索引和影响结论；专项细节只写回对应子计划。
- 已关闭子计划出现适用失败时重开其交付链或建立明确后继，不静默改写历史完成证据。
- 发布、远端外部写入和其他高风险动作始终按当前用户授权与项目规则裁决；历史子计划中的授权不向当前动作继承。
- 没有新失败、协议变化、新消费者或可重复共享机制时保持收益边缘，不为计划持续存在而制造任务。
