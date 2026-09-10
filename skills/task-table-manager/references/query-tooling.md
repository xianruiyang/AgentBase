# taskctl 查询与导航

本文件只用于 `show/list/deps/dependents/impact/next/status/render`。

## 命令职责

```text
show/list                   有界返回任务、状态、结果和局部诊断
deps/dependents/impact      查询任务图；后继查询返回首条路径与该边消费内容
next                        返回候选和建议排序，不决定下一项工作
status/render               生成可重建的执行摘要和 TASK_TABLE.md
```

`show` 的 model 视图以顶层 ID 标识对象，task/state/result 不重复 schema 或 task ID；task/state revision、结果 task revision、结果引用、语义正文、诊断和来源收据摘要仍保留。

`list/deps/dependents/impact/next` 的完整非空页省略列表长度、`truncated:false` 和零诊断计数；截断时返回总数和精确 `after_id`，`impact/dependents` 接受该参数续页。空页仍返回 matched/dependency/dependent/candidate 数，因为无候选或关系也是查询结论。

`next` 排序只供建议。模型仍按用户优先级、硬依赖、关键风险、共享前置、冲突、当前能力和最近可验证闭环选择；`recommended` 或任务深度不签发执行许可。`hard` 依赖未完成时可用 `--include-blocked` 查看并继续分析或准备。

`status` 和 `render` 的结果摘要按明确作用域区分：`referenced_result_count` 是当前状态文件实际引用的结果数；`task_revision_stale_result_count` 是结果记录的 task revision 与当前合同不一致；`source_snapshot_issue_result_count` 是至少含一项收据缺失、资产异常、覆盖不完整或逐来源陈旧诊断的结果数。它们与含诊断结果数、结果诊断条目数和按 kind 计数互不替代，也不表示目标证据充分或整体完成。两者还从活跃任务的非空执行检查点、任务范围、关联 DCR 和结构写回漂移派生 `active_frontiers`；每项保留 task/state 真源路径与 revision。model 预算不足时依次移除 DCR 正文、按完整任务单元缩减；单项仍过大时保留身份、真源、任务结果、前沿、消费者、最近证据与下一动作的有界投影，明确列出缩短或省略字段和 `context`/machine 恢复入口。正常空诊断、无前沿任务、完整 protected baseline 和机器零计数只保留在 machine 视图或省略。

`render` 在工作区锁内取得一致任务快照，复用 `status` 非零摘要并附生成路径。`add/update` 和状态写命令自动调用同一 renderer；显式 `render` 用于主动重建或恢复陈旧展示。`TASK_TABLE.md` 记录 UTC 刷新时间，并只为有检查点、关联 DCR 或结构漂移的活跃任务额外生成“当前执行前沿”；明细保留全部列和 state 的 UTC `started_at/ended_at`，空单元格以 `—` 占位。占位符不写回合同，也不表示模型裁决为“无”。无任务或结果引用时明确区分已读空集合与未知；有结果但验证数为零时保留该缺口。

`state_writeback_drift_count` 保留全部此类结构漂移的数量，即使有界诊断页或活跃前沿没有展开对应记录；`result_history_state_write_drift` 则定位结构与任务身份匹配、但尚未被当前 state 引用的下一 revision 结果，通常对应 `complete` 两阶段写入在 state 提交前中断。诊断同时给出 result/current task revision：结果仍适用且合同未变时可按相同输入恢复；结果已失效或合同已变时，先用 CAS state note 记录旧尝试已被越过。它是带恢复动作的 advisory：不得把结果自动晋升为 current result 或完成结论，也不得把较早历史结果误报为漂移。

`task-table.json`、`.work-cache/index.json` 和 `TASK_TABLE.md` 分别是登记、缓存和生成视图，不是任务或语义修改入口。

## 门禁与恢复

- `TASK-PATH`：查询路径越界或对象不在任务工作区。
- `TASK-LIMIT` / `TASK-INPUT-UNREADABLE`：当前查询无法有界读取，或单一对象的身份/结构无法确定解释；批量查询中的损坏记录应隔离并诊断，不阻断其他记录。
- `TASK-AMBIGUOUS-TARGET`：精确查询需要唯一 ID，但当前匹配不唯一。

`list/next/deps/dependents/impact` 的普通分页是建议性查询；游标失效时提示从首页重读，不为普通导航建立快照阻断。
