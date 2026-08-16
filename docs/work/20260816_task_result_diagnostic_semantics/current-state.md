# 任务结果诊断与证据时效语义：现状分析

## OBS-001 当前真实状态摘要把结果时效问题显示为零

- 状态: confirmed
- 来源: 2026-08-16 对上一交付工作区运行当前项目 `taskctl status`
- 关联: AC-001, AC-002, AC-007

工作区有 2 个 done 任务和 2 个带验证结果；响应同时返回 `diagnostic_count: 0` 与 `results.stale_result_count: 0`。该响应只直接证明当前字段值，不证明结果没有其他诊断。

## OBS-002 同一快照的候选结果实际包含八项诊断

- 状态: confirmed
- 来源: 2026-08-16 对同一工作区运行当前项目 `completion-context --target-id REQ-001`
- 关联: AC-001, AC-004, AC-007

顶层 `diagnostic_count` 为 0，但 `T001-NORMALIZE-CANDIDATES.result_diagnostics` 有 8 项：1 项 `result_source_snapshot_incomplete` 和 7 项 `result_source_snapshot_stale`；后继 `T002-VERIFY-DELIVER` 没有结果诊断。响应已返回完整事实，但零值顶层汇总没有声明其只覆盖查询诊断。

## OBS-003 stale_result_count 只统计任务合同 revision

- 状态: confirmed
- 来源: 直接读取 `summarize_loaded_task_storage`
- 关联: AC-002, DES-002, DES-003

现有实现只在 `result.current_for_task_revision` 为假时增加 `stale_result_count`，不调用 `result_diagnostics`，因此来源快照缺失、不完整或陈旧不会进入该计数。`render` 的人类文本把它描述为“合同修订后陈旧结果”，但 JSON 字段未保留该限定。

## OBS-004 completion-context 分开构造查询与结果诊断但没有汇总关系

- 状态: confirmed
- 来源: 直接读取 `completion_context_locked`
- 关联: AC-001, AC-003, DES-002, DES-003

顶层 `diagnostics` 只由存储、索引和结果读取失败组成；每个候选对象另行调用 `result_diagnostics`。顶层 `diagnostic_count` 只取前者长度，预算裁剪后候选目录会重建，但没有同步重建任何结果诊断汇总。

## OBS-005 当前测试保护嵌套诊断但没有保护汇总语义

- 状态: confirmed
- 来源: 直接读取 `tests/test_taskctl.py`
- 关联: AC-007, DES-005

现有测试验证 Markdown 改变后候选结果含 `result_source_snapshot_stale`，也验证合同 revision 改变后 `stale_result_count` 为 1；没有用同一场景断言顶层诊断汇总、来源问题结果数或相近正常场景的零值。

## OBS-006 后继结果没有完整声明对前置目标的重新覆盖

- 状态: confirmed
- 来源: 直接读取上一工作区 T001/T002 任务合同和结果
- 关联: AC-004, DES-004

T002 硬依赖 T001，并记录受影响回归和真实机制复测，且自己的来源快照当前、无结果诊断；但 `evidence_for` 只列出 `REQ-002`、`AC-006`、`UDES-001` 和 `OBS-007`，没有明确覆盖 T001 声称支持的全部目标。现有完成审计仍可依据直接验证判断最近版本成立，但任务结果投影不能把依赖或验证文案自动提升为对所有前置目标的当前证据。

## GAP-001 完成复核诊断汇总不满足结构无歧义

- 状态: superseded
- 后继证据: OBS-007, OBS-008
- 关联: OBS-001, OBS-002, OBS-004, REQ-001, AC-001

顶层零值与当前页真实结果诊断并存，模型必须深入遍历候选才能发现缺口，违反辅助视图结构无歧义和陈旧证据保持可见的目标。

## GAP-002 状态字段把结果引用位置和时效维度混在含糊命名中

- 状态: superseded
- 后继证据: OBS-007, OBS-008
- 关联: OBS-001, OBS-003, REQ-001, AC-002

`current_result_count` 实际表示状态当前引用的结果，`stale_result_count` 只表示任务 revision 陈旧；字段名无法直接排除来源快照陈旧，导致不同生命周期概念被误读为同一有效性结论。

## GAP-003 后继验证的当前证据表达缺少正式约束和 oracle

- 状态: superseded
- 后继证据: OBS-007
- 关联: OBS-005, OBS-006, REQ-002, AC-004, AC-005

交付合同已要求重新验证后提交新结果，但 task-table-manager 尚未明确 dependency、候选关系与 `evidence_for/source_snapshot/verification` 的不同职责，也没有测试防止工具自动推断或抑制旧诊断。

## GAP-004 共享 owner 变更尚未闭合全部消费者与独立证据

- 状态: superseded
- 后继证据: OBS-007, OBS-008, OBS-009, OBS-010
- 关联: OBS-003, OBS-004, OBS-005, REQ-003, AC-006, AC-007

正式文档、completion、status、render、生成文本、测试、真实工作区和独立 skill 证据尚未迁移到同一新合同；只修改一个计数字段会留下同源歧义和消费者不一致。

## OBS-007 正式合同、唯一聚合和仓库消费者已经迁移

- 状态: confirmed
- 来源: 2026-08-16 项目真源修改与受影响模块完整回归
- 关联: REQ-001, REQ-002, AC-001, AC-002, AC-003, AC-004, AC-005, AC-006, DES-001, DES-002, DES-003, DES-004, DES-005

`task-table-manager` 现由同一结果诊断聚合函数为 `completion-context`、`status` 与 `render` 提供结果数、诊断条目数、kind 计数、任务 revision 陈旧结果数和来源快照问题结果数；查询诊断与候选结果诊断分层命名，歧义字段已从仓库消费者退出。正式合同明确 dependency 不等于重新验证，后继结果只有通过自己的当前来源快照、目标证据映射和直接验证才可成为当前候选证据，旧结果诊断保持可见。66 项 `task-table-manager` 回归和 32 项 `delivery-workflow` 回归通过；其中正反场景证明后继结果不会自动抑制前置结果诊断，也不会生成第二套 resolved 状态。

## OBS-008 原真实工作区现在返回无歧义诊断汇总

- 状态: confirmed
- 来源: 2026-08-16 使用修改后的项目真源对 `docs/work/20260816_task_completion_context_dedup` 重跑 `status` 与 `completion-context`
- 关联: REQ-001, AC-001, AC-002, AC-003, AC-004, AC-007, DES-002, DES-003

同一历史工作区的 `status` 现报告总诊断 8、结果诊断 8、含诊断结果 1、来源快照问题结果 1、任务 revision 陈旧结果 0，kind 分布为 1 项 `result_source_snapshot_incomplete` 和 7 项 `result_source_snapshot_stale`。`completion-context` 对 `REQ-001` 同时报告查询诊断 0、当前页候选结果诊断 8、含诊断候选结果 1，T001 保留 8 项旧诊断而 T002 为 0；这明确表达新验证可以提供当前候选证据，但不会改写历史结果。12,000 字符预算变体仍返回完整候选 ID 和与最终目录一致的汇总，已采样的 SHA-256 来源指纹保持 71 字符，没有压缩 `source_snapshot` 表示。

## OBS-009 当前 skill 路由、策略和条件引用证据已经闭合

- 状态: confirmed
- 来源: 2026-08-17 detached 三阶段独立评估与正式合并入口
- 关联: REQ-003, AC-006, AC-007, DES-005

最终采用的三个独立运行分别覆盖 Routing 73、Policy 73 和 References 19 个场景；Routing 满足 73/73 个声明的项目 skill 与 peer skill 约束，合并入口确认三阶段唯一运行身份、隔离声明、候选哈希、capsule 哈希、行为标签和条件引用均有效，并刷新 `development/skill-routing/evidence/current.json`。未通过的评估运行没有写入正式 evidence，也没有用于修改候选 skill、测试 oracle 或期望集合。

## OBS-010 项目合同与部署候选验证通过

- 状态: confirmed
- 来源: 2026-08-17 正式项目验证入口
- 关联: REQ-003, AC-006, AC-007, DES-005

`validate_contract.ps1` 确认 73 个路由场景、34 个严格路由场景、5 个严格引用场景以及 11/11 个 skill 的正向和非触发覆盖均有效。`manage_agentbase.ps1 -Action Validate` 在 `DirectCompatibility` 候选范围确认 11 个 skill、可移植设置、MCP 身份和当前路由 evidence 有效，候选 source bundle SHA-256 为 `FA48371094AA1239C7A42AE41AB40E2339E79D3A9FCD60657814387CF25FF3E9`。该验证不执行 `Publish`，也不证明实际 Codex 安装已更新。
