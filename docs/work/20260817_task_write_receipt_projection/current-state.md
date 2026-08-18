# Task 写入回执投影现状与证据

## OBS-001 状态写回执复制机器信封

- 状态: confirmed
- 来源或证据: `taskctl.py` 修改前的 `task_model_projection` 通用回退与各状态命令返回值
- 事实/推断/未知: 事实
- 关联目标: AC-001
- 可证明上限: 默认 model 视图会保留完整 `state`，其中含 `schema: task.state` 与和顶层 `id` 重复的 `task_id`

## OBS-002 默认值和重复结果引用进入模型输出

- 状态: confirmed
- 来源或证据: `claim/start` 返回 `warning_count`，全部状态写返回 `diagnostic_count`，`add/complete` 返回恢复布尔值，旧通用稀疏函数只移除空容器而不移除零和 false
- 事实/推断/未知: 事实
- 关联目标: AC-001, AC-002
- 可证明上限: 正常成功回执包含零计数和 false；`complete` 同时在 state 与顶层返回同一个结果引用

## OBS-003 render 未使用既有 status 稀疏摘要

- 状态: confirmed
- 来源或证据: `render` handler 返回完整计数摘要，旧 model projection 直接走通用回退；`task_status_model` 已有非零摘要逻辑
- 事实/推断/未知: 事实
- 关联目标: AC-003
- 可证明上限: 同一 CLI 内已存在正确压缩 owner，但 render model 消费者未接入

## GAP-001 写入命令缺少消费者适配

- 状态: resolved
- 来源或证据: OBS-001—OBS-003
- 事实/推断/未知: 由直接实现结构推出
- 关联目标: REQ-001
- 可证明上限: 根因位于 model projection 的命令覆盖不足，不在永久数据格式或 machine renderer
