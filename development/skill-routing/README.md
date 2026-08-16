# Skill routing validation

本目录维护 AgentBase 全局规则与关键 skill 的静态触发合同，以及只读取脱离仓库 capsule、不读取隐藏期望的分阶段独立评估。它证明候选在给定请求下应选择哪些 skill、适用哪些粗粒度行为和应读取哪些治理引用；不证明 skill 内步骤或具体任务执行已经正确完成。

## 正式产物

- [`trigger-cases.json`](trigger-cases.json)：所需 skill、触发用例、严格路由用例和策略标签的测试 oracle。
- [`validate_contract.ps1`](validate_contract.ps1)：规则、skill、项目入口、相对引用和触发集合的静态合同。
- [`build_routing_evaluation.ps1`](build_routing_evaluation.ps1)：构建 Routing、Policy 或 References 阶段的 detached capsule。
- [`validate_routing_results.ps1`](validate_routing_results.ps1)：验证独立结果的身份、输入声明、完整性和期望。
- [`merge_routing_evidence.ps1`](merge_routing_evidence.ps1)：合并三个不同独立运行的结果。
- [`evidence/current.json`](evidence/current.json)：Validate、Publish 与 CI 使用的唯一当前路由策略证据。

## 静态合同

全局规则或 skill 触发语义变化时，先同步 `trigger-cases.json` 中适用的正向、相近非触发、混合意图和严格用例，再运行：

```powershell
& '.\development\skill-routing\validate_contract.ps1' -ProjectRoot (Get-Location).Path
```

静态通过只证明文件结构、必要语义、项目入口和测试 oracle 自洽，不证明模型行为已经改变。

## 独立评估

首次 Routing capsule 只包含路由前可见的候选全局规则、skill frontmatter、外部 skill 摘要和请求。首次结果通过隐藏 oracle 后，Policy capsule 只加入始终可见规则与行为标签；References capsule 只加入已选治理用例与 `change-governance` 正文。三个阶段必须由不同的独立运行完成：

```powershell
& '.\development\skill-routing\build_routing_evaluation.ps1' -ProjectRoot (Get-Location).Path
& '.\development\skill-routing\build_routing_evaluation.ps1' -Phase Policy -ProjectRoot (Get-Location).Path -RoutingResultsPath '<routing-result>.json'
& '.\development\skill-routing\build_routing_evaluation.ps1' -Phase References -ProjectRoot (Get-Location).Path -RoutingResultsPath '<routing-result>.json'
& '.\development\skill-routing\merge_routing_evidence.ps1' -ProjectRoot (Get-Location).Path -RoutingResultsPath '<routing-result>.json' -PolicyResultsPath '<policy-result>.json' -ReferenceResultsPath '<reference-result>.json' -OutputPath '.\development\skill-routing\evidence\current.json'
```

每个结果必须记录唯一运行 ID、实际模型、运行环境、UTC 时间、`detached-capsule` 模式、未访问仓库/隐藏期望的声明和身份哈希。候选规则、skill 描述、外部 skill 摘要或请求集合变化后，旧证据失效。

`detached-capsule` 是输入隔离合同，不等于操作系统沙箱。执行行为仍由 skill 回归、组件 release gate 和具体任务的直接验收负责。
