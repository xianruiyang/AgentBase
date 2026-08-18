# Task 查询模型投影设计

## DES-001 查询 model projection 是正式适配 owner

- 状态: confirmed
- 关联: REQ-001, UDES-001

各 query handler 继续计算完整 canonical 结果，machine renderer 不变；`task_model_projection` 增加 show、列表、关系和 next 的命令专用投影，不在存储层改变字段。

## DES-002 show 按对象职责去除重复信封

- 状态: confirmed
- 关联: AC-001, DES-001

顶层持有查询目标 ID；task 保留合同 revision 与语义，state 保留状态 revision 与非空状态字段，result 保留结果 task revision、正文和 provenance。完整来源映射继续只显示 count，机器视图可展开。

## DES-003 page more 统一表达截断恢复

- 状态: confirmed
- 关联: AC-002, AC-003, DES-001

list/deps/dependents/impact 共用 `{total,after_id}` 恢复投影；next 使用 `{candidate_count,after_id}`，推荐总数仅在与候选总数不同且发生截断时补充。空页保留各命令自己的零或总数结论。

## DES-004 impact parser 完成复用合同

- 状态: confirmed
- 关联: AC-004

impact 继续复用 dependents handler 并强制 recursive；parser 同步注册 `--after-id`，使 Namespace 输入与被复用 handler 的必需属性一致，不复制一套递归实现。
