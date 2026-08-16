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
| Source Query Gateway | [分支计划](../development/source-query-gateway/plan.md) | P0—P10 已闭环；当前身份达到质量与 Token 采纳门槛，未证明速度改善 | `tools/srcq`、`source-query`、`vscode-lsp-mcp` | 替代代码搜索早期方案，消费 LSP Companion 的公开查询能力，并由 `source-query` skill 与部署 payload 使用 | 新查询失败、后端/协议变化、新消费者或可重复共享缺口 |
| VS Code LSP MCP Companion | [组件方案](../mcp/vscode-lsp-mcp/PLAN.md)、[当前组件入口](../mcp/vscode-lsp-mcp/README.md) | 已形成组件与受验证 Windows release；PLAN 保留架构基线，不作为开放任务表 | `mcp/vscode-lsp-mcp` | Source Query Gateway 消费其查询协议；公开工具或协议变化需回到该分支复核 | 安全边界、Provider 协议、公开工具或发布生命周期改变 |
| 代码搜索早期改进 | [历史记录](../development/code-search-workflow-improvement-plan.md) | 已由 Source Query Gateway 替代，只保留迁移前证据 | 无当前运行 owner | 迁移证据由 Source Query Gateway 保留；没有当前执行消费者 | 仅作证据追溯，不重新启用旧 skill/sgy 入口 |

当前没有未闭环的项目级实施阶段。组件的常规维护由其 README、需求、设计和测试合同承接，不因列入本表自动创建任务。

## 5. 2026-08-16 实践结论

Source Query Gateway P10 的真实代理实践表明：局部输出更短、默认预算更大或命令配方更具体，都不能证明完整任务更省；质量或实验边界无效的低成本结果不能采纳。固定预读、失败回合和错误 owner 会放大完整上下文成本，在实际 owner 修正规则适用边界比向全局规则或工具增加补偿特例更有效。最终候选保持质量并降低完整路径的上下文成本，但没有证明速度改善，因此只采纳证据直接覆盖的收益。

这些结论支持第 3 节的完整决策链、必要时的同质量比较、单机制迭代和正确 owner 原则，不把专项实验数字外推为项目固定阈值。具体计数、身份、逐调用事实和证据限制只由 [往返审计](../development/source-query-gateway/evidence/round-trip-audit-p10.md)、[日期化分支汇总](../development/source-query-gateway/plan.md#38-2026-08-16-p10-实践证据与总体计划复核)和 [完成审计](../development/source-query-gateway/evidence/completion-audit-p10.md)维护。

## 6. 重开与维护

- 新需求或新证据先定位到现有子计划和 owner；能由现有入口承接时不新增计划。
- 跨计划共享职责、根需求或正式入口变化时，更新本文件的方向、索引和影响结论；专项细节只写回对应子计划。
- 已关闭子计划出现适用失败时重开其交付链或建立明确后继，不静默改写历史完成证据。
- 发布、远端外部写入和其他高风险动作始终按当前用户授权与项目规则裁决；历史子计划中的授权不向当前动作继承。
- 没有新失败、协议变化、新消费者或可重复共享机制时保持收益边缘，不为计划持续存在而制造任务。
