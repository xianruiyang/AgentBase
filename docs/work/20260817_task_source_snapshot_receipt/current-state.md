# Task 来源快照收据现状

## OBS-001 模型视图复制完整指纹映射

- 状态: confirmed
- 关联: DES-001, DES-002

`task_context_model` 把 canonical `source_snapshot` 原样放入模型视图；结果合同又要求模型把该映射复制进结果。当前交付链的 `T004-DELIVER.r4.json` 实际保存 17 个完整 SHA-256 指纹。

## OBS-002 预算投影和来源快照成员脱节

- 状态: confirmed
- 关联: AC-001, DES-002

`task_model_variants` 会为满足模型预算逐项移除 `upstream`，但不调整 `source_snapshot` 或 `source_snapshot_complete`。因此永久结果可记录模型最终视图中没有正文的来源。

## OBS-003 逐来源诊断依赖完整映射

- 状态: confirmed
- 关联: AC-003, DES-003

当前 `result_diagnostics` 用记录映射逐项比较当前索引，能区分缺失、不完整和每个来源的陈旧；只用一个整体摘要哈希会丢失该能力。

## OBS-004 历史内联结果是当前真实消费者

- 状态: confirmed
- 关联: AC-004, DES-004

仓库既有交付链保存了内联 `source_snapshot` 结果，状态、show、completion-context 和 workctl 摘要仍会读取这些结果；兼容路径有真实对象，但新写入没有继续内联的理由。

## GAP-001 模型交互面和机器证据职责未分离

- 状态: confirmed
- 关联: REQ-001, AC-001, AC-002, OBS-001, OBS-002

模型承担了机器指纹传递职责，且快照身份不能准确证明最终可见输入。

## GAP-002 新存储必须保留当前诊断和历史读取

- 状态: confirmed
- 关联: AC-003, AC-004, OBS-003, OBS-004

现有代码只从结果内联映射诊断；缺少快照资产 owner、引用校验、机器展开和单向兼容。
