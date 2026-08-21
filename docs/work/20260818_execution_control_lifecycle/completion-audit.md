# 执行控制与 Skill 上下文生命周期：完成审计

## 重开原因

2026-08-21 的九题评测准备证明，原 AC-036 证据只覆盖“是否建立计划”和“条件相当时优先纵向闭环”，没有覆盖多个任务共享未证前提、首个真实消费者、失败遮蔽和昂贵批量验证。原完成判定在该范围内被反例推翻；本文件以当前候选重新审计，不沿用旧结论为运行期行为证明。

## 目标证据

| 目标 | 当前结果与直接证据 | 判定 |
| --- | --- | --- |
| AC-007 按端到端成本渐进加载上下文 | skill 选择、正文有效性和引用生命周期仍分离；新增 skill 只按两类控制问题加载引用 | 满足 |
| AC-024 纳入目标成立所需的职责调整 | 架构与长期 owner 仍由 `change-governance`；新执行 owner 明确排除单个领域故障和职责裁决，没有吸收治理职责 | 满足 |
| AC-036 共享前提先闭合真实消费者 | 全局不变量、`execution-governor` 控制循环、Delivery 投影和 Task `hard` 依赖形成单向职责链；独立切片已验证 Routing、Policy 与 References | 仓库合同满足；真实执行未验证 |
| AC-050 目标档位、状态查询与切换收益分层 | 复杂执行的目标与状态价值归执行控制，稳定工作由模型直接判断，`reasoning-governor` 只承担线程读写与生命周期 | 仓库合同满足；真实自主切换未验证 |

## 职责与消费者闭合

- `docs/requirements.md` 持有纵向消费者目标；`global/AGENTS.md` 只保留共享未知先证实、成立前不扩量和反例熔断的不变量。
- `execution-governor` 是运行期下一动作 owner，但不持有计划、任务状态或完成结论；`delivery-workflow`、`task-table-manager`、`change-governance` 与 `reasoning-governor` 各自只消费其控制结论并维护原职责。
- `development/skill-routing` 已把第 12 个 skill 接入必需清单、正反例、条件引用与当前 evidence；DirectCompatibility 生命周期清单包含稳定资产身份，插件 payload 仍由同一必需 skill 集生成。
- 没有新增控制日志、状态文件、缓存、Hook、Goal 字段或 CLI 门禁；任务中的 `hard` 关系只在真实消费证明或首个消费者证据时成立。
- 96/96 Routing、96/96 Policy、27/27 References 与零模型基础设施均通过；它们不被提升为 skill 内实际行为证明。

## 完成判定

第一版仓库候选的职责、规则、skill、任务投影、路由、引用和资产生命周期已经闭合。只包含本次暂存内容与原 HEAD 的独立临时 Git tree 已通过 skill 校验、96-case 合同、6-suite 路由基础设施和正式部署 Validate，其中基线 Windows SWE 确定性入口为 45 tests；当前组合工作树的 Validate 也通过并运行 66 tests。后一个数量包含接手时已有的评测 dirty 候选，只证明两者当前组合没有触发适用失败，不把该候选纳入本次完成范围。该结论只证明未发布仓库候选，不证明真实 Codex 已加载或运行期行为已改变；安装状态保持不变，真实行为验收留到用户另行授权发布后的新任务。
