# Task 写入回执投影需求

## REQ-001 模型回执只保留后续动作所需事实

- 状态: confirmed
- 来源: 用户要求模型直接读取的工具输出使用最小充分表示
- 关联: AC-001, AC-002, AC-003

Task Table Manager 的默认模型写入回执只返回目标身份、写后 revision、写后语义状态、结果引用和实际问题；永久记录与显式 machine 输出继续保留完整结构。

## AC-001 不复制永久状态信封

- 状态: confirmed
- 来源: REQ-001
- 关联: REQ-001

`claim/start/note/complete/reopen/release` 的 model 回执不含 `task.state` schema，也不在顶层 ID 之外重复 `task_id`。`complete` 的结果引用只返回一次。

## AC-002 默认成功值不占模型上下文

- 状态: confirmed
- 来源: REQ-001
- 关联: REQ-001

空诊断、空警告、零计数和 `recovered_partial_write:false` 不进入 model 回执；恢复确实发生或问题列表被截断时保留相应事实与总数。

## AC-003 生成视图回执复用稀疏状态摘要

- 状态: confirmed
- 来源: REQ-001
- 关联: REQ-001

`render` 的 model 回执保留输出路径、任务总数、非零状态、非零结果进展或问题以及实际诊断，不重复全部零计数；machine 摘要不变。

## CON-001 本轮边界

- 状态: confirmed
- 来源: 用户授权持续开发；Codex 发布仍需当次明确同意
- 关联: REQ-001

只改变 Task Table Manager 的 model projection、正式合同、测试和项目记录；不改变永久任务数据、machine 输出、Codex 安装或发布状态。
