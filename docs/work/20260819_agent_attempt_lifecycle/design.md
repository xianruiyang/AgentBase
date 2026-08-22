# 模型设计

## DES-001 Agent 配置唯一 owner

- 状态: superseded
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

## DES-004 语义角色与易变模型配置分层

- 状态: confirmed
- 关联目标: REQ-003, UDES-003

`global/AGENTS.md` 唯一维护主代理何时默认选择 `evidence` 或 `experiment`、何时直接完成，以及不可移交的正式责任。该规则以 `should` 明确请求可推翻的默认委派，不使用只限制不触发的“只有…才”许可句，也不升级为绝对创建义务。`global/agents/evidence.toml`、`experiment.toml` 各自唯一维护实际模型、档位和角色自身约束；`global/config.toml` 只维护未分类子代理的回退。部署 validator 校验可移植 schema 与安全边界，不复制当前模型或档位。

## DES-005 编排 skill 持有有界交接协议

- 状态: confirmed
- 关联目标: REQ-003, AC-009

`subagent-orchestration` 持有必要输入、独立边界和委派净收益的详细判断，以及最小 capsule、evidence packet、主代理逐项接纳、实验隔离、反例熔断、并发资格和无后代代理合同。全局规则已请求默认委派时本 skill 可以自动选中；它只细化选择和交接，不把净收益改成强制创建。静态证据、实验结果和主代理生产实现形成单向链；子代理输出不成为状态真源或完成裁判。
