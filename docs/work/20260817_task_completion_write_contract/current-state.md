# Task completion 写入合同现状

## OBS-001 模型输入重复机器 envelope

- 状态: confirmed
- 关联: AC-001, AC-002, DES-001, DES-002

`validate_result_for_task` 当前要求结果输入提供 `schema == task.result`、与命令目标相同的 `task_id` 和当前 `task_revision`，随后又在规范化永久结果时重新生成这些字段。测试辅助结果同样要求模型形态填写三项机器身份。

## OBS-002 task revision 绑定隐藏在模型正文

- 状态: confirmed
- 关联: AC-001, DES-003

`complete` 只有 state revision CAS；任务执行版本取自结果正文。若直接删掉 `task_revision` 并采用完成时当前 revision，旧执行可能被错误绑定到更新后的任务合同，因此必须迁移为独立的调用方 CAS。

## OBS-003 失效收据在落盘后才诊断

- 状态: confirmed
- 关联: AC-003, AC-005, DES-004

`command_complete` 当前先写结果与 `done` 状态，再调用 `hydrate_result_source_snapshot`。对应测试删除快照资产后仍期待 completion 成功并保存悬空引用；损坏和身份不一致同样只在写后返回诊断。

## OBS-004 历史读取和上一版输入是不同生命周期

- 状态: confirmed
- 关联: AC-004, DES-005

仓库多个交付工作区包含永久 `task.result` 历史，必须继续读取。当前正式合同还允许完整结果 envelope 和内联快照作为 `complete` 输入；该兼容可以在唯一写入口规范化，但不应继续定义新模型输入。

## OBS-005 当前消费者范围可收敛

- 状态: confirmed
- 关联: UDES-002, DES-001

仓库内 `--result-file` 的运行消费者只位于 `taskctl` 回归测试；Delivery Workflow 通过任务状态、永久结果和诊断摘要消费输出，不构造 completion 输入。正式合同、测试、历史工作区读取和 workctl 摘要构成本次影响范围。

## GAP-001 模型修改面与机器存储职责混合

- 状态: confirmed
- 关联: REQ-001, AC-001, AC-002, OBS-001, OBS-002

模型被迫同步维护工具已经知道的 schema、任务身份和机器 revision 字段，且执行版本没有作为独立并发前提表达。

## GAP-002 新写入允许制造不可解引用的永久记录

- 状态: confirmed
- 关联: AC-003, AC-005, OBS-003

显式引用在本次写入开始时已经缺失、损坏或身份不匹配仍可推进任务到 `done`，把可机械证明的输入完整性失败降成了写后语义诊断。

## GAP-003 兼容与新模型入口没有分层

- 状态: confirmed
- 关联: AC-004, OBS-004, OBS-005

上一版完整 envelope 的真实迁移职责与新模型输入使用同一默认形态，使机器兼容字段继续进入模型修改面。
