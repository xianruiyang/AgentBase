# AgentBase 总计划

## 1. 文档职责

本文件是 AgentBase 唯一的项目级计划入口，维护当前总体方向、跨计划决策、子计划索引、可复用实践结论和重开条件。项目长期目标与约束只由 [requirements.md](requirements.md) 定义；子计划继续拥有各自的需求、设计、任务、结果和详细证据；当前安装状态由正式部署入口读回。本文件不复制这些内容，也不产生执行授权、发布授权或完成判定。

维护项目或启动新一轮工作时，先从本文件确定所属子计划和正式 owner；已有子计划能够承接时回到该入口，只有目标、职责或生命周期确实独立时才新增子计划。子计划形成、关闭、替代或重开后同步更新本文件的入口和结论，不在 README、历史方案或进度说明中维护第二份总计划。

## 2. 总体方向

AgentBase 持续把根需求落实为可跨项目复用的 Codex 协作维护能力：有效洞察并与用户共同校准需求，以证据形成和维护权威职责，让方案、任务、消费者与验证沿目标闭环，并可靠维护规则、skill、工具、配置、部署和发布链。

所有改进依次保证需求对齐、正确性、授权、安全、可维护性和完成证据；质量同等充分时降低端到端 Token，前两者不变差时再提升速度。有效规划后优先沿当前目标链形成最近的可验证闭环；思考深度随真实不确定性、后果、可逆性和验证负担调整，不按任务形式固定。

## 3. 跨计划决策合同

1. 从用户需求和项目事实识别真实差距，不从现有实现、旧测试、任务状态或工具输出反推目标。
2. 在决定行为的正式 owner 修正问题，闭合当前消费者、派生产物和旧同责路径；不得用上下层补偿特例制造平行入口。
3. 优化模型取得充分证据并形成可靠结论的完整决策链，不以单个文件、skill、stdout、调用次数或局部预算代替总体结果。
4. 候选先通过质量与证据门禁；成本确实影响当前方案选择时，才按对应子计划的适用协议比较完整决策链，总计划不维护固定数值基线或要求每轮量化。速度只在质量和上下文成本不退化时参与选择。
5. 一次只改变一个有直接证据支持的机制；机制与适用输入未变时不为期待不同结果重跑，低成本但质量、oracle 或实验边界无效的结果不得成为目标。
6. 常驻规则只吸收跨任务重复、能稳定改变动作且属于其职责的不变量；专项协议、样本、原始运行和审计保留在对应子计划或 `development/`。

## 4. 子计划索引

| 子计划 | 正式入口 | 当前结论 | 主要 owner | 跨计划依赖与消费者 | 重开或替代条件 |
| --- | --- | --- | --- | --- | --- |
| 根需求收益边缘持续优化 | [方案](work/20260814_agentbase_requirement_edge_optimization/solution.md)、[现状与证据](work/20260814_agentbase_requirement_edge_optimization/current-state.md) | 已闭环；SOL-001—SOL-006 的长期结论已进入当前总计划 | `global/AGENTS.md`、核心 skill、路由与部署验证 | 其余当前子计划继承根需求；全局规则或 skill 变化由路由与部署合同消费 | 新的根需求差距、适用失败或跨计划共享机制 |
| Delivery Workflow 自审 | [方案](work/20260812_agentbase_delivery_workflow_self_review/solution.md) | 已闭环；作为后续十二轮审查的基线 | `delivery-workflow`、`task-table-manager` | 十二轮审查承接该基线，当前工作流与任务合同继续消费其稳定结论 | 已修机制复发或任务存储/工作流合同改变 |
| Delivery Workflow 十二轮审查 | [方案](work/20260812_agentbase_delivery_workflow_twelve_round_audit/solution.md) | 已闭环；详细轮次结论保留在该交付链 | `delivery-workflow`、`task-table-manager`、`change-governance` | 依赖自审基线；阶段、任务与治理合同变化需沿三项 skill 的消费者复核 | 阶段语义、快照、分页、影响闭合或任务合同改变 |
| Delivery Workflow 渐进上下文下一版 | [方案](work/20260816_agentbase_delivery_workflow_context_economy/solution.md)、[完成审计](work/20260816_agentbase_delivery_workflow_context_economy/completion-audit.md) | 已闭环；阶段合同按动作加载，执行使用最小语义闭包，条件引用评估支持多个 skill | `delivery-workflow`、`development/skill-routing` | 承接既有交付合同并保持 `task-table-manager` 压缩消费者职责；路由与插件分发消费新增引用 | 阶段引用误选、必要语义缺失、全量预读复发、完成审计漏项或真实任务质量/端到端成本退化 |
| Task completion-context 证据去重 | [方案](work/20260816_task_completion_context_dedup/solution.md)、[完成审计](work/20260816_task_completion_context_dedup/completion-audit.md) | 已闭环；页级目录只返回一次完整任务证据，目标以 ID 保持关系，预算与分页闭包不变 | `task-table-manager` | 承接交付链最终复核与任务结果；路由证据和部署 payload 消费变更后的 skill | 目标关联、证据字段、预算闭包或分页退化，出现真实旧格式消费者，或进一步重复已对完整决策链造成可证实成本 |
| Task 结果诊断与证据时效语义 | [方案](work/20260816_task_result_diagnostic_semantics/solution.md)、[完成审计](work/20260816_task_result_diagnostic_semantics/completion-audit.md) | 已闭环；查询诊断、结果诊断、任务 revision 陈旧和来源快照问题分层表达，后继当前证据不改写历史结果 | `task-table-manager` | 承接完成复核输出、状态与生成视图；`delivery-workflow` 状态视图、路由证据和部署 payload 消费新合同 | 分层计数与唯一候选目录不一致，旧歧义字段复现，后继结果自动抑制旧诊断，或新证据没有明确覆盖目标与当前来源 |
| 模型可见工具输出双视图 | [方案](work/20260817_model_visible_tool_output_contract/solution.md)、[输出审计](work/20260817_model_visible_tool_output_contract/output-audit.md)、[消费者复核](work/20260817_model_visible_tool_output_contract/consumer-impact.md)、[完成审计](work/20260817_model_visible_tool_output_contract/completion-audit.md) | 已闭环；taskctl/workctl 默认模型视图只投影当前动作所需证据，显式 machine 视图保留稳定完整合同，两者由同一 canonical 计算与 owner 维护 | `global/AGENTS.md`、`task-table-manager`、`delivery-workflow` | `srcq` 提供既有模型输出成本估算实践；任务与交付消费者、路由验证和部署 payload 消费新合同；其余模型可见入口保持各自 owner，未被误标为已迁移 | 模型视图遗漏完成当前动作的必要证据、重新暴露机器信封或完整快照、machine 合同退化、预算恢复不可定位，真实 tokenizer/阅读质量比较不再成立，或其他 owner 出现可证实的同类高成本输出 |
| Source Query Gateway | [分支计划](../development/source-query-gateway/plan.md) | P0—P10 已闭环；当前身份达到质量与 Token 采纳门槛，未证明速度改善 | `tools/srcq`、`source-query`、`vscode-lsp-mcp` | 替代代码搜索早期方案，消费 LSP Companion 的公开查询能力，并由 `source-query` skill 与部署 payload 使用 | 新查询失败、后端/协议变化、新消费者或可重复共享缺口 |
| VS Code LSP MCP Companion | [组件方案](../mcp/vscode-lsp-mcp/PLAN.md)、[当前组件入口](../mcp/vscode-lsp-mcp/README.md) | 已形成组件与受验证 Windows release；PLAN 保留架构基线，不作为开放任务表 | `mcp/vscode-lsp-mcp` | Source Query Gateway 消费其查询协议；公开工具或协议变化需回到该分支复核 | 安全边界、Provider 协议、公开工具或发布生命周期改变 |
| 代码搜索早期改进 | [历史记录](../development/code-search-workflow-improvement-plan.md) | 已由 Source Query Gateway 替代，只保留迁移前证据 | 无当前运行 owner | 迁移证据由 Source Query Gateway 保留；没有当前执行消费者 | 仅作证据追溯，不重新启用旧 skill/sgy 入口 |

当前没有未闭环的项目级实施阶段。组件的常规维护由其 README、需求、设计和测试合同承接，不因列入本表自动创建任务。

## 5. 2026-08-16 实践结论

Source Query Gateway P10 的真实代理实践表明：局部输出更短、默认预算更大或命令配方更具体，都不能证明完整任务更省；质量或实验边界无效的低成本结果不能采纳。固定预读、失败回合和错误 owner 会放大完整上下文成本，在实际 owner 修正规则适用边界比向全局规则或工具增加补偿特例更有效。最终候选保持质量并降低完整路径的上下文成本，但没有证明速度改善，因此只采纳证据直接覆盖的收益。

这些结论支持第 3 节的完整决策链、必要时的同质量比较、单机制迭代和正确 owner 原则，不把专项实验数字外推为项目固定阈值。具体计数、身份、逐调用事实和证据限制只由 [往返审计](../development/source-query-gateway/evidence/round-trip-audit-p10.md)、[日期化分支汇总](../development/source-query-gateway/plan.md#38-2026-08-16-p10-实践证据与总体计划复核)和 [完成审计](../development/source-query-gateway/evidence/completion-audit-p10.md)维护。

同日的 Delivery Workflow 后继实践把上述原则应用到流程规则自身：固定要求完整读取统一阶段合同会把未触发细则带入上下文，应在 skill 主入口按当前动作选择唯一阶段 owner；执行上下文先闭合当前目标、直接支配上游、直接依赖结果和适用约束，仅在真实不确定性、影响传播或最终复核时扩展。条件引用选择属于路由验证的共享职责，不应为每个 skill 建独立评估入口。独立评估的单次过选或漏选也不能直接证明 oracle 错误，必须先对照触发时点和当前正式 owner。具体结构证据、失败归因与完成边界保留在[后继完成审计](work/20260816_agentbase_delivery_workflow_context_economy/completion-audit.md)。

同日的任务完成复核后继实践进一步确认：同一事实对象被多个目标引用时，辅助视图应保存一次完整对象并显式表达关系，而不是把完整证据复制到每条关系中。该规范化只有在字段、关系、快照、游标和预算裁剪仍形成可解析闭包时才是有效降本；本轮真实输入的具体字节与适用边界只保留在[任务复核完成审计](work/20260816_task_completion_context_dedup/completion-audit.md)，不提升为项目固定压缩门槛。

任务结果诊断后继实践进一步确认：结果“被当前状态引用”、任务合同 revision 一致、来源快照当前和结果没有其他诊断是不同生命周期事实，辅助视图不得用一个含糊的 current/stale 计数代替。后继验证形成新的目标证据时，应以自己的 `evidence_for`、执行来源快照和直接验证明确覆盖目标；历史结果及其诊断保持不可改写，由最终模型按目标选择当前适用证据。具体字段、真实旧工作区的 8 项诊断和验证边界只保留在[诊断语义完成审计](work/20260816_task_result_diagnostic_semantics/completion-audit.md)，不把 CLI 提升为整体完成裁判。

## 6. 2026-08-17 模型可见输出实践结论

工具输出的首要合同不是“统一序列化”，而是“当前消费者下一步必须知道什么”。模型视图应先按动作投影最小充分证据，再在候选表示之间用真实 tokenizer 和可读性比较；machine 视图则保留完整、稳定、可解析的协议。两种视图必须由同一 canonical 计算和正式 owner 生成，避免为降 Token 引入第二套事实源；预算不足时裁剪完整低优先级单元并返回可定位恢复信息，不截断语义字段。具体投影、真实工作区样本、Token 对照和边界保留在[输出审计](work/20260817_model_visible_tool_output_contract/output-audit.md)，不把单次比例提升为全项目固定阈值。

## 7. 重开与维护

- 新需求或新证据先定位到现有子计划和 owner；能由现有入口承接时不新增计划。
- 跨计划共享职责、根需求或正式入口变化时，更新本文件的方向、索引和影响结论；专项细节只写回对应子计划。
- 已关闭子计划出现适用失败时重开其交付链或建立明确后继，不静默改写历史完成证据。
- 发布、远端外部写入和其他高风险动作始终按当前用户授权与项目规则裁决；历史子计划中的授权不向当前动作继承。
- 没有新失败、协议变化、新消费者或可重复共享机制时保持收益边缘，不为计划持续存在而制造任务。
