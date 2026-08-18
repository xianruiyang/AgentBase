# workctl 模型回执投影设计

## DES-001 work_model_projection 是唯一适配 owner

- 状态: confirmed
- 关联: REQ-001, UDES-001

命令 handler 继续返回完整 canonical 事实。model projection 按命令选择保护回执、影响列表或生成回执；machine renderer 和永久资产不变。

## DES-002 baseline issue 投影按 status 与调用位置分层

- 状态: confirmed
- 关联: AC-001, DES-001

baseline helper 使用当前 `status` 字段。`status` 命令在 baseline 节点返回状态与来源，详细诊断只使用顶层有界诊断；`coverage` 没有顶层诊断，因此在 baseline 节点保留同一诊断。正常 `protected` 且无诊断时不显示 baseline。

## DES-003 protect 与 render 回执复用既有语义

- 状态: confirmed
- 关联: AC-002, DES-001

protect model 回执从 handler 已验证 summary 选择当前周期事实并把诊断放在一个位置。render 调用 `work_status_model` 投影同一 semantic/task summary，再附加输出路径；正常 `tasks.status=available` 作为成功默认值省略，非正常状态保留。

## DES-004 impact 保持完整列表或显式恢复

- 状态: confirmed
- 关联: AC-003, DES-001

未截断时 ID 与 affected 列表已经自描述；截断时用 `more` 返回 affected 总数和 true，避免把必要恢复事实当冗余删除。
