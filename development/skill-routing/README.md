# Skill routing validation

本目录维护 AgentBase 全局规则与关键 skill 的静态触发合同，以及只读取脱离仓库 capsule、不读取隐藏期望的分阶段独立评估。它证明候选在给定请求下应选择哪些 skill、适用哪些粗粒度行为和应读取哪些治理引用；不证明 skill 内步骤或具体任务执行已经正确完成。

## 正式产物

- [`trigger-cases.json`](trigger-cases.json)：所需 skill、触发用例、严格路由用例、策略标签和条件引用选择的测试 oracle。
- [`validate_contract.ps1`](validate_contract.ps1)：规则、skill、项目入口、相对引用和触发集合的静态合同。
- [`build_routing_evaluation.ps1`](build_routing_evaluation.ps1)：构建 Routing、Policy 或 References 阶段的 detached capsule。
- [`validate_routing_results.ps1`](validate_routing_results.ps1)：验证独立结果的身份、输入声明、完整性和期望。
- [`record_routing_attempt.ps1`](record_routing_attempt.ps1)：验证并登记一次正式阶段结果；失败也留下有界分类收据，相同输入的新运行必须声明一次重试理由。
- [`merge_routing_evidence.ps1`](merge_routing_evidence.ps1)：唯一正式合并入口；先通过尝试登记入口接收三个独立结果，再原子刷新当前证据。
- [`evidence/current.json`](evidence/current.json)：本地 Validate 与 Publish 使用的唯一当前路由策略证据。
- [`evidence/attempts.json`](evidence/attempts.json)：正式评估尝试的审计真源；部署 Validate 只用它证明当前三阶段结果各有通过收据，不从它反推 skill 正确性。

## 静态合同

全局规则或 skill 触发语义变化时，先同步 `trigger-cases.json` 中适用的正向、相近非触发、混合意图和严格用例，再运行：

```powershell
& '.\development\skill-routing\validate_contract.ps1' -ProjectRoot (Get-Location).Path
```

静态通过只证明文件结构、必要语义、项目入口和测试 oracle 自洽，不证明模型行为已经改变。

## 独立评估

首次 Routing capsule 只包含路由前可见的候选全局规则、skill frontmatter、外部 skill 摘要和请求。首次结果通过隐藏 oracle 后，Policy capsule 只加入始终可见规则与行为标签；References capsule 只加入首次路由已选中的条件引用型 skill 正文及相应用例，当前覆盖 `change-governance`、`delivery-workflow` 与 `task-table-manager`。三个阶段必须由不同的独立运行完成：

```powershell
& '.\development\skill-routing\build_routing_evaluation.ps1' -ProjectRoot (Get-Location).Path
& '.\development\skill-routing\build_routing_evaluation.ps1' -Phase Policy -ProjectRoot (Get-Location).Path -RoutingResultsPath '<routing-result>.json'
& '.\development\skill-routing\build_routing_evaluation.ps1' -Phase References -ProjectRoot (Get-Location).Path -RoutingResultsPath '<routing-result>.json'
& '.\development\skill-routing\merge_routing_evidence.ps1' -ProjectRoot (Get-Location).Path -RoutingResultsPath '<routing-result>.json' -PolicyResultsPath '<policy-result>.json' -ReferenceResultsPath '<reference-result>.json' -OutputPath '.\development\skill-routing\evidence\current.json'
```

每个结果必须记录唯一运行 ID、实际模型、运行环境、UTC 时间、`detached-capsule` 模式、未访问仓库/隐藏期望的声明和身份哈希。候选规则、skill 描述、外部 skill 摘要或请求集合变化后，旧证据失效。

`merge_routing_evidence.ps1` 是正式尝试的唯一接收方。它按 Routing、Policy、References 分别调用登记入口：每份收据只保存 phase、候选/输入/capsule/result 哈希、evaluator 身份、UTC 时间、结果、最多 500 字符的失败摘要、与前一次相比发生变化的身份字段和可选重试理由，不保存原始模型日志。完全相同的已通过结果可以幂等复用，不形成新尝试；同一 phase、candidate、input 与 capsule 的新 evaluator 结果默认拒绝，明确传入对应的 `-RoutingRetryJustification`、`-PolicyRetryJustification` 或 `-ReferenceRetryJustification` 后至多允许一次。再次失败后必须改变候选或评估输入，不能原样刷到成功。

`evidence/attempts.json` 由登记入口在独占锁下原子维护，`validate_routing_attempt_history.ps1` 负责结构、唯一 evaluator、每输入最多两次及当前成功收据接入。它是开发与发布门禁消费的机器真源，不是模型默认读取面；人和模型通过本节合同、验证回执或精确 attempt ID 读取所需事实，不复制完整历史。仓库首次引入该合同使用 `initialize_routing_attempt_history.ps1` 从已经验证的 `current.json` 导入三份 `baseline_import` 收据，并明确声明更早尝试未被重建；此入口拒绝覆盖已有历史。

`detached-capsule` 是输入隔离合同，不等于操作系统沙箱。尝试收据只证明正式验证输入、结果和重试边界可审计，也不证明行为正确；执行行为仍由 skill 回归、组件 release gate 和具体任务的直接验收负责。
