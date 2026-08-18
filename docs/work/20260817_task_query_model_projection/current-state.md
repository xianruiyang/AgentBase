# Task 查询模型投影现状与证据

## OBS-001 show 复制三种机器信封

- 状态: confirmed
- 来源或证据: 真实工作区 `taskctl show T001-IMPLEMENT-DIAGNOSTIC-CONTRACT` 修改前输出
- 事实/推断/未知: 事实
- 关联目标: AC-001
- 可证明上限: 默认 model 输出包含 task/result schema、state schema、三处任务 ID 和默认 `current_for_task_revision:true`

## OBS-002 普通分页输出保留重复计数与默认值

- 状态: confirmed
- 来源或证据: 同一真实工作区 list/deps/dependents/next 修改前输出
- 事实/推断/未知: 事实
- 关联目标: AC-002, AC-003
- 可证明上限: 完整列表仍返回等于列表长度的 count、`truncated:false`、`diagnostic_count:0`；list 还返回所有零状态

## OBS-003 语义零与成功默认值不能同规则处理

- 状态: confirmed
- 来源或证据: 真实工作区 next 返回零候选；测试工作区 T001 没有依赖
- 事实/推断/未知: 事实
- 关联目标: AC-003
- 可证明上限: 删除全部零值会把“无候选/无依赖”退化成不表达查询结论，不能使用通用递归删零替代命令语义

## OBS-004 impact 正式命令稳定崩溃

- 状态: confirmed
- 来源或证据: 真实工作区执行 `taskctl impact --id T001-IMPLEMENT-DIAGNOSTIC-CONTRACT --limit 5`
- 事实/推断/未知: 事实
- 关联目标: AC-004
- 可证明上限: `command_dependents` 读取 `args.after_id`，impact parser 未定义该属性，触发 `AttributeError`

## GAP-001 查询消费者覆盖与 parser/handler 合同不完整

- 状态: resolved
- 来源或证据: OBS-001—OBS-004
- 事实/推断/未知: 由代码路径和真实运行直接证明
- 关联目标: REQ-001
- 可证明上限: 修正位于 taskctl query projection 与 impact parser，不要求改图算法或存储
