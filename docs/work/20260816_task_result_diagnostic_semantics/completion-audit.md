# AgentBase 根需求与任务结果诊断语义下一版完成审计

## 审计边界

本审计判断 2026-08-17 当前项目候选是否闭合 `completion-context`、`status` 与 `render` 的诊断汇总歧义，以及后继验证如何提供当前证据而不改写历史结果。项目候选完成不表示实际 Codex 安装已经更新；本轮没有实施 `source_snapshot` 引用池或压缩，也没有处理插件迁移。

## 本轮需求与设计闭合

| 对象 | 直接证据 | 结论 |
| --- | --- | --- |
| REQ-001、AC-001 | `completion-context` 分开返回 `query_diagnostics` 与当前页 `diagnostic_summary`；真实旧工作区报告查询诊断 0、候选结果诊断 8、含诊断候选结果 1 | satisfied |
| AC-002 | `status` 与 `render` 分别返回状态引用结果、任务 revision 陈旧、来源快照问题、含诊断结果、诊断条目和 kind 计数 | satisfied |
| AC-003 | 汇总由最终候选目录重建；预算回归与 12,000 字符真实变体确认目录、目标引用和汇总一致 | satisfied |
| REQ-002、AC-004 | 正式结果合同要求后继结果以自己的 `evidence_for`、执行时 `source_snapshot` 和直接验证声明当前覆盖 | satisfied |
| AC-005 | 旧结果诊断继续存在；CLI 没有新增 pass、resolved diagnostics 或结果到结果的有效性状态 | satisfied |
| REQ-003、AC-006 | `result_diagnostics` 是唯一时效事实源，completion/status/render 和 delivery 状态视图共同使用同一聚合 | satisfied |
| AC-007 | 时效轴、后继证据正反场景、分页预算、真实旧工作区、skill 与项目验证均有直接证据 | satisfied |
| UDES-001、UDES-002 | 本轮完成实际开发并复核正式 owner、合同、消费者、预算、验证与恢复入口，没有把问题压成单字段补丁 | satisfied |
| CON-001—CON-004 | 完整诊断和来源快照保留，没有引入平行有效性状态、来源快照压缩或插件迁移，Codex 发布仍待当次授权 | satisfied |

## 真实输入与生命周期证据

对上一交付工作区 `docs/work/20260816_task_completion_context_dedup` 使用修改后的项目真源复测：

- `status` 报告总诊断 8、结果诊断 8、含诊断结果 1、来源快照问题结果 1、任务 revision 陈旧结果 0；kind 为 1 项 `result_source_snapshot_incomplete` 和 7 项 `result_source_snapshot_stale`。
- `completion-context --target-id REQ-001` 报告查询诊断 0、当前页候选结果诊断 8、含诊断候选结果 1；T001 保留 8 项旧诊断，T002 为 0。
- 该并列结果证明“历史结果陈旧”和“后继结果提供当前候选证据”可以同时成立。后继任务存在或依赖关系本身不消除前者；只有后继结果明确映射和直接验证的目标可采用新证据。
- 12,000 字符预算变体仍返回完整候选 ID 和与最终目录一致的汇总；抽查的 SHA-256 来源指纹均保持 71 字符。本轮没有改变 `source_snapshot` 表示。

## 消费者与验证闭环

- `task-table-manager` 66 项完整回归通过，覆盖查询 0/结果非 0、任务 revision 陈旧、来源快照缺失/不完整/陈旧、后继当前证据、仅依赖非证据、正常零值、分页预算和来源指纹完整性。
- `delivery-workflow` 32 项完整回归通过，生成状态视图已迁移到相同分层语义。
- skill 结构校验通过；项目静态合同确认 73 个路由场景、34 个严格路由、5 个严格引用和 11/11 个 skill 的正向/非触发覆盖。
- detached Routing、Policy、References 独立运行分别覆盖 73、73、19 个场景；最终 Routing 为 73/73，通过结果和两阶段后继结果由正式入口合并到 `development/skill-routing/evidence/current.json`。失败运行未进入正式 evidence，也未用于修改候选规则或 oracle。
- 部署候选 `Validate` 通过，确认 11 个 skill、可移植设置、MCP 身份和路由 evidence；source bundle SHA-256 为 `FA48371094AA1239C7A42AE41AB40E2339E79D3A9FCD60657814387CF25FF3E9`。该动作没有执行 `Publish`。
- 本工作区最终 `completion-context` 一页返回全部 12 个目标、4 个约束和 0 个 DCR，查询诊断为 0。T001 历史实现结果因后续加入独立证据与项目验证现状而保留 1 项来源快照不完整和 1 项陈旧诊断；T002 当前结果明确映射 12 个目标及 4 个约束、来源快照完整且结果诊断为 0。该读回直接证明后继当前证据没有静默清除历史诊断。

## 根需求逐项复核

| 根需求 | 当前正式 owner 与本轮影响 | 当前结论 |
| --- | --- | --- |
| REQ-001 协作维护 | `global/AGENTS.md`、`delivery-workflow` 与总计划；本轮目标由用户确认后进入完整交付链 | 当前候选覆盖 |
| REQ-002 本源高效规则 | 全局质量—Token—速度顺序；本轮增加必要汇总而不删除完整证据 | 当前候选覆盖 |
| REQ-003 动态思考深度 | 全局规则与 `reasoning-governor` | 当前候选覆盖，本轮未改变 owner |
| REQ-004 文档驱动交付 | `delivery-workflow`、阶段文档、任务结果与本审计 | 当前候选覆盖 |
| REQ-005 辅助工具边界 | `task-table-manager` 合同与 `taskctl`；本轮仅提供机械分层事实，不输出整体通过值 | 当前候选覆盖 |
| REQ-006 公共职责生命周期 | `change-governance` 与 task-table 唯一结果诊断 owner；全部仓库消费者已迁移 | 当前候选覆盖 |
| REQ-007 长期成本与授权 | 全局方案与授权合同；不保留旧歧义字段或无真实对象兼容模式 | 当前候选覆盖 |
| REQ-008 直接证据与完成范围 | 模块回归、真实机制读回、独立证据、项目 Validate 与本审计 | 当前候选在声明范围内覆盖 |
| REQ-009 低成本长期任务 | `task-table-manager` 的任务、结果、快照、分页和分层诊断摘要 | 当前候选覆盖并改善复核恢复成本 |
| REQ-010 可移植发布 | 部署身份、payload 与回滚合同 | 项目候选覆盖；实际 Codex 仍是上一发布版本 |
| REQ-011 必要主动联系 | `codex-qq-hook` 的授权与传输职责 | 当前候选覆盖，本轮未改变 owner |

## 完成判断与重开条件

本轮全部 `REQ/AC/UDES/CON` 已有正式产物与适用直接证据，没有 DCR；诊断语义在 task-table-manager 正式 owner 和查询投影合同层闭合，并迁移当前消费者。若分页汇总与最终候选目录不一致，歧义的 current/stale 字段复现，后继结果自动抑制历史诊断，新结果没有明确目标映射、当前来源或直接验证，或发现真实旧字段消费者，应重开本后继计划。任何向实际 Codex 根目录执行 `Publish` 的操作仍须用户针对该次发布明确同意。
