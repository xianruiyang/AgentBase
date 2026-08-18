# 模型设计

## DES-001 Agent 配置唯一 owner

- 状态: confirmed
- 关联目标: REQ-001, UDES-001

`global/config.toml` 唯一维护默认子代理与默认档位，`global/agents/luna.toml`、`global/agents/sol.toml` 各自唯一维护角色身份、职责和显式档位。部署 validator 只校验合同，不复制角色正文。Terra 通过 `managed_asset_lifecycle.json` 完成从受管 present 到 retired 的单向转换。

## DES-002 两阶段尝试生命周期

- 状态: confirmed
- 关联目标: REQ-002, UDES-002

`record_routing_attempt.ps1` 是正式尝试生命周期唯一 owner：`Begin` 在 evaluator 执行前原子写入 `started` 收据；`Finish` 以同一 attempt ID 写入 `passed`，或以 `identity_or_schema`、`oracle_violation`、`execution_failed` 结束。`merge_routing_evidence.ps1` 只消费三份已通过 attempt ID，不再隐式创建尝试。

## DES-003 有界活跃周期

- 状态: confirmed
- 关联目标: AC-004, AC-005

`evidence/attempts.json` 只保存一个活跃 Routing capsule 周期，每周期最多六份收据，每个不变输入最多两份。周期变化时在新账本保留上一周期 ID、完整文件 SHA-256 和收据数；旧正文由 Git 历史承担恢复，不建立无限增长的第二历史文件。
