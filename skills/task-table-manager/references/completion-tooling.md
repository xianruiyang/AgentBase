# taskctl 最终复核上下文

本文件只用于 `completion-context`。该命令辅助模型取得最终复核证据，不判断需求是否满足，也不返回整体通过值。

## 目标与候选证据

`completion-context` 从当前 Markdown 分页返回每个 `REQ/AC/UDES`、`CON`、全部 `DCR` 和关联任务结果。model 视图保留目标正文、候选结果摘要、产出、验证、未决项、诊断、证据引用、来源收据摘要、snapshot ID 和精确游标，省略完整来源映射；machine 视图保留完整结构。

每页只在顶层 `candidate_tasks` 中返回一次完整候选任务证据。对象以任务 ID 为键，值不重复任务 ID；每个 `targets[]` 只用有序 `candidate_task_ids` 引用当前页候选，并返回该目标的候选总数、返回数、结果数、带验证结果数、截断状态和精确游标。预算移除目标时同步移除无人引用任务，不得产生悬空 ID。

`query_diagnostics` 只放存储、索引、结果读取和当前语义目标定位的查询级问题。`diagnostic_summary` 分层返回 `query_diagnostic_count`、当前唯一候选目录中的含诊断结果数、`task_revision_stale_result_count`、`source_snapshot_issue_result_count`、结果诊断条目数和按 kind 计数；只覆盖当前最终保留页，不用无作用域的 `diagnostic_count` 混合两层。

`deferred_changes` 流返回当前 Markdown 中全部 DCR 及其原始状态，不根据内置状态集筛选阻断项。目标、约束和 DCR 的 `document` 使用 `workflow.json.documents` 中的完整工作区相对路径，不压缩成可能冲突的文件名。

## 分页与快照

首页返回 `snapshot_id`。续页一次只选择一个结果流，并原样传回该流上一页的 `target_next_after_id`、`constraint_next_after_id`、`deferred_next_after_id` 或 `candidate_next_after_id`。游标必须精确标识同一快照中的一项；未知游标不得按字符串大小猜测。

首页无法从当前 Markdown 重建索引时仍返回局部诊断，供模型直接检查文档。携带 snapshot ID 的续页若无法重建当前 Markdown，就不能证明仍属于首页快照，只阻断该次续页；修复输入后丢弃旧游标与快照，从首页重新取得上下文。

## 门禁与恢复

- `TASK-LIMIT` / `TASK-INPUT-UNREADABLE`：当前页无法有界读取，或续页无法重建当前文档并核对快照身份。
- `TASK-AMBIGUOUS-TARGET`：精确目标无法唯一定位。
- `TASK-PAGINATION-SNAPSHOT`：续页会混用两个任务或文档快照。

任务或文档在最终复核中改变时必须从第一页重审。DCR 是否阻断、目标证据是否充分和整体是否完成始终由模型按 Delivery Workflow 当前用户确认范围裁决。
