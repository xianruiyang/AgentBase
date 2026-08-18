# Task 写入回执投影设计

## DES-001 model projection 是唯一回执适配 owner

- 状态: confirmed
- 关联: REQ-001, UDES-001

命令 handler 继续产生完整机器事实，`task_model_projection` 按命令职责派生模型回执；不得在 handler 或永久文件中删除机器字段，也不新增第二次状态计算。

## DES-002 合同写入回执

- 状态: confirmed
- 关联: AC-002, DES-001

`add/update` 返回任务 ID 与写后 task revision；`add` 另返回初始 state revision。只有发生部分写恢复时返回恢复标志；诊断非空时返回可见条目，只有总数大于可见条目数时再返回总数。

## DES-003 状态写入回执

- 状态: confirmed
- 关联: AC-001, AC-002, DES-001

状态命令返回顶层任务 ID，以及去掉 schema、重复 task ID 和空字段后的写后语义状态。`complete` 在顶层返回一次结果引用；警告与诊断采用同一有界条目/溢出总数规则。

## DES-004 render 复用 status 稀疏语义

- 状态: confirmed
- 关联: AC-003, DES-001

`render` 不维护第二套结果摘要压缩规则，而是复用 `status` 的非零任务/结果摘要并附加生成路径；仅补充非零 review 数。
