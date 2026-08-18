# 现状与差距

## OBS-001 原 Agent 配置

- 状态: confirmed
- 证据: 修改前 `global/agents/` 与 `global/config.toml`
- 关联: GAP-001

修改前仓库管理 Luna、Terra、Sol 三个角色；各角色未显式拥有独立推理档位，默认子代理设置统一决定推理档位。

## GAP-001 角色与用户指定档位不一致

- 状态: confirmed
- 关联: OBS-001, DES-001, AC-001, AC-002, AC-003

三角色清单和共享默认档位无法表达用户指定的 Luna/max、Sol/medium 两级设计，Terra 也仍会作为发布资产安装。

## OBS-002 原尝试登记时点

- 状态: confirmed
- 证据: 修改前 `record_routing_attempt.ps1`、`merge_routing_evidence.ps1`、`evidence/attempts.json`
- 关联: GAP-002, GAP-003

原正式入口只有取得结果后才登记，merge 隐式接收三个结果；evaluator 在结果产生前失败时没有 attempt ID 或失败收据。账本把所有运行追加在单个文件中，没有周期级容量上限。

## GAP-002 执行失败可消失

- 状态: confirmed
- 关联: OBS-002, DES-002, AC-004

结果文件产生前的 evaluator 失败无法由正式门禁证明，后续运行可能掩盖该失败。

## GAP-003 活跃账本可无界增长

- 状态: confirmed
- 关联: OBS-002, DES-003, AC-005

每个不变输入的重试上限不能限制候选持续变化后的总文件增长，长期模型与机器读取成本没有明确边界。
