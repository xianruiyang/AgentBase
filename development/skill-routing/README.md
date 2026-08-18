# Skill routing validation

本目录维护 AgentBase 全局规则与关键 skill 的静态触发合同，以及只读取脱离仓库 capsule、不读取隐藏期望的分阶段独立评估。它证明候选在给定请求下应选择哪些 skill、适用哪些粗粒度行为和应读取哪些治理引用；不证明 skill 内步骤或具体任务执行已经正确完成。

## 正式产物

- [`trigger-cases.json`](trigger-cases.json)：所需 skill、触发用例、严格路由用例、策略标签和条件引用选择的测试 oracle。
- [`validate_contract.ps1`](validate_contract.ps1)：规则、skill、项目入口、相对引用和触发集合的静态合同。
- [`build_routing_evaluation.ps1`](build_routing_evaluation.ps1)：构建 Routing、Policy 或 References 阶段的 detached capsule。
- [`validate_routing_results.ps1`](validate_routing_results.ps1)：验证独立结果的身份、输入声明、完整性和期望。
- [`record_routing_attempt.ps1`](record_routing_attempt.ps1)：正式尝试生命周期的唯一 owner；评估执行前 `Begin`，执行后以结果或执行失败 `Finish`，所有结局都落入有界分类收据。
- [`merge_routing_evidence.ps1`](merge_routing_evidence.ps1)：唯一正式证据合并入口；只接受三份已经完成且通过的 attempt ID 与对应结果，再原子刷新当前证据。
- [`evidence/current.json`](evidence/current.json)：本地 Validate 与 Publish 使用的唯一当前路由策略证据。
- [`evidence/attempts.json`](evidence/attempts.json)：当前评估周期的有界尝试账本；部署 Validate 只用它证明没有未完成尝试且当前三阶段结果各有通过收据，不从它反推 skill 正确性。

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
& '.\development\skill-routing\record_routing_attempt.ps1' -Action Begin -Phase Routing -ProjectRoot (Get-Location).Path -EvaluatorId '<routing-run-id>' -EvaluatorModel '<model>' -EvaluatorRuntime '<runtime>'
# 在独立运行中执行 Routing capsule；无论是否得到结果都必须 Finish。
& '.\development\skill-routing\record_routing_attempt.ps1' -Action Finish -Phase Routing -ProjectRoot (Get-Location).Path -AttemptId '<routing-attempt-id>' -ResultsPath '<routing-result>.json'
& '.\development\skill-routing\build_routing_evaluation.ps1' -Phase Policy -ProjectRoot (Get-Location).Path -RoutingResultsPath '<routing-result>.json'
& '.\development\skill-routing\build_routing_evaluation.ps1' -Phase References -ProjectRoot (Get-Location).Path -RoutingResultsPath '<routing-result>.json'
# Policy 与 References 同样各自 Begin、独立执行并 Finish 后再合并。
& '.\development\skill-routing\merge_routing_evidence.ps1' -ProjectRoot (Get-Location).Path -RoutingResultsPath '<routing-result>.json' -PolicyResultsPath '<policy-result>.json' -ReferenceResultsPath '<reference-result>.json' -RoutingAttemptId '<routing-attempt-id>' -PolicyAttemptId '<policy-attempt-id>' -ReferenceAttemptId '<reference-attempt-id>' -OutputPath '.\development\skill-routing\evidence\current.json'
```

每个结果必须记录唯一运行 ID、实际模型、运行环境、UTC 时间、`detached-capsule` 模式、未访问仓库/隐藏期望的声明和身份哈希。候选规则、skill 描述、外部 skill 摘要或请求集合变化后，旧证据失效。

`record_routing_attempt.ps1` 是正式尝试生命周期的唯一 owner。每次真实 evaluator 执行必须先 `Begin`，使 `started` 收据先于外部运行持久化；随后必须用同一 attempt ID `Finish`。有结果时登记入口校验身份与 oracle 并记录 `passed`，或以 `identity_or_schema`、`oracle_violation` 记录失败；evaluator 没有产出结果时用 `-ExecutionFailureSummary` 记录 `execution_failed`。未完成的 `started` 收据会阻断正式 Validate 和 Publish，不能通过重新执行掩盖。

每份收据只保存 phase、周期、候选/输入/capsule/result 哈希、evaluator 身份、开始与完成 UTC 时间、结果、最多 500 字符的失败摘要、与前一次相比发生变化的身份字段和可选重试理由，不保存原始模型日志。同一 phase、candidate、input 与 capsule 的第二次运行必须显式传入 `-RetryJustification`，并且每个不变输入最多两次；达到上限后必须改变候选或评估输入，不能原样刷到成功。

`evidence/attempts.json` 由登记入口在独占锁下原子维护，一个活跃周期最多六份收据。候选或 Routing 输入改变后，只有旧周期不存在未完成尝试才开始新周期；新账本保留上一周期 ID、账本 SHA-256 与收据数，旧正文通过 Git 历史恢复，不在当前模型读取面无限累积。`validate_routing_attempt_history.ps1` 负责结构、周期、唯一 evaluator、未完成尝试、每输入两次上限、六份收据上限及当前成功收据接入。它是开发与发布门禁消费的机器真源，不是模型默认读取面；人和模型通过本节合同、验证回执或精确 attempt ID 读取所需事实，不复制完整历史。

仓库首次引入该合同使用 `initialize_routing_attempt_history.ps1` 从已经验证的 `current.json` 通过 Begin/Finish 导入三份 `baseline_import` 收据，并明确声明更早尝试未被重建；此迁移入口拒绝覆盖已有历史。

`detached-capsule` 是输入隔离合同，不等于操作系统沙箱。尝试收据只证明正式验证输入、结果和重试边界可审计，也不证明行为正确；执行行为仍由 skill 回归、组件 release gate 和具体任务的直接验收负责。
