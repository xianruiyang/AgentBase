# 增量独立路由验证需求

## REQ-001 只对变化的模型可见语义重新独立评估

- 状态: confirmed
- 来源: 用户 2026-08-20 要求独立验证不要每次触发、降低耗时与 Token
- 关联: AC-001, AC-002, AC-003

候选变化后，正式入口应按 Routing、Policy、References 各阶段实际暴露给 evaluator 的输入判断是否需要新运行；未改变该阶段模型可见语义且旧结果仍满足当前隐藏 oracle 时复用证据，不因无关文件或其他阶段身份变化触发评估。

## AC-001 阶段身份只绑定真实可见输入

- 状态: confirmed
- 关联: REQ-001

Routing 绑定全局规则、skill description、可用 peer 摘要和请求；Policy 绑定全局规则、行为标签定义和请求；References 绑定被选中的条件引用 skill 正文、相关请求和相关 Routing 选择。文件位置、未暴露正文、metadata、其他阶段 evaluator 身份或隐藏期望不得造成无关失效。

## AC-002 隐藏 oracle 变化先复验旧结果

- 状态: confirmed
- 关联: REQ-001

只改变 expected、forbidden 或 strict oracle 时，不重复同一 evaluator 输入；先用新 oracle 校验既有独立结果，只有模型可见候选或输入随后真实改变时才形成新的正式运行。

## AC-003 未知或协议变化安全扩大

- 状态: confirmed
- 关联: REQ-001

evaluator 指令、输出 schema、指纹算法、阶段边界或无法证明依赖范围的变化，使对应阶段完整失效；不得以复用省 Token 覆盖未知依赖。

## REQ-002 降低正式验证的等待与输出成本

- 状态: confirmed
- 来源: 用户 2026-08-20 指出当前验证太慢且消耗 Token 过多
- 关联: AC-004, AC-005

正式入口应自动给出最小评估计划，允许互不依赖的阶段并行，并让 evaluator 只生成 oracle 所需结果；不要求模型为普通成功用例逐项重复理由或机器身份。

## AC-004 计划可直接指导运行与复用

- 状态: confirmed
- 关联: REQ-002

只读计划同时提供低 Token 模型视图和完整 machine 视图，区分 `evaluate`、`reuse`、`pending-routing`，说明直接原因、用例数、并行关系和下一入口；计划不自行裁决行为正确或启动外部运行。

## AC-005 Policy 可与 Routing 并行

- 状态: confirmed
- 关联: REQ-002

Policy 不依赖 Routing 的 evaluator 身份或选择结果；两者都需刷新时可由不同独立运行并行完成。References 只在新的相关 Routing 选择确定后判断复用或运行。

## REQ-003 独立运行与复用都可审计

- 状态: confirmed
- 来源: 用户此前确认失败必须改进，本轮要求在降本后继续高质量独立验证
- 关联: AC-006, AC-007, AC-008

降低触发频率不得绕过 Begin/Finish、隔离声明、失败分类、重试上限或当前证据与收据的绑定；复用必须由正式入口机械证明来源与阶段身份未变。模型阶段已经通过但后续编排失败时，正式入口不得因丢失阶段结果而再次调用模型。

## AC-006 独立 CLI 入口真实隔离

- 状态: confirmed
- 关联: REQ-003

正式 runner 使用仓库外临时工作目录、read-only sandbox、ephemeral session、临时 Codex home 和结构化输出；只以运行期间只读的硬链接使用现有认证，并从用户级官方模型缓存提取所选模型的一份临时最小目录，禁止插件、应用、hooks、skills、shell 与其他非评估能力。它不得加载真实用户配置、AGENTS、项目 oracle 或模型目录之外的缓存状态；Codex 服务环境与模型 shell 必须分离，模型 shell 消费共享且哈希固定的 secret/network/control 过滤策略。任何 tool event 继续使 cases-only 结果失败，因此该策略加强不改变成功证据的模型可见输入，也不为相同 capsule 创建重采样理由。runner 在 evaluator 执行前 Begin、结束后必定 Finish。

## AC-007 复用收据与当前证据唯一绑定

- 状态: confirmed
- 关联: REQ-003

每个复用阶段记录来源 evidence 哈希、来源 receipt、阶段结果身份和当前评估周期；merge 只接受当前周期内唯一通过的正式运行或复用收据。活跃周期仍最多六份收据，相同 evaluator 输入最多两次真实 evaluator 尝试且后续尝试需要理由；进程启动前的编排失败必须单独分类、单独有界，不冒充模型采样。

## AC-008 已通过阶段可恢复

- 状态: confirmed
- 关联: REQ-003

每个已通过阶段的完整结果在 current evidence 原子合并前保留为本地、忽略提交的 generation staging；下一次正式刷新只在结果身份、文件哈希、语义哈希、evaluator 和 passed receipt 唯一一致时恢复。generation 改变时以不可变旧账本快照证明阶段搬运来源；搬运中途再次中断后继续恢复当前阶段并搬运剩余阶段，合并成功后才删除 staging。原始模型日志、隐藏 oracle 和失败结果不作为恢复真源。

## REQ-004 形成长期统一的评估测试基础设施

- 状态: confirmed
- 来源: 用户 2026-08-20 要求“完成一个评估测试基础架构，彻底解决以后的测试还有评估问题”
- 关联: AC-009, AC-010

评估机制自身应有一个可重复、低成本、不会意外启动模型的统一回归入口；部署只消费能机械证明 payload 结构、身份和可恢复性的确定性合同。模型路由评估保留为显式研究入口，不得因部署而刷新，也不得把采样选择等同于运行时合同。

## AC-009 统一确定性入口覆盖评估机制

- 状态: confirmed
- 关联: REQ-004

单一入口检查全部评估 PowerShell 语法并并行覆盖指纹、capsule、planner、隔离 runtime、attempt ledger、并发、合并、同代恢复、跨代搬运和中断续传；对子进程机械设置禁止 evaluator 的单向测试边界，并提供有界 model/machine 结果。

## AC-010 部署与模型路由研究分层

- 状态: confirmed
- 关联: REQ-004

正式 Validate 与 Deploy 只运行部署 payload 的确定性结构合同并验证受管资产生命周期，不读取、要求或记录 `current.json`、attempt ledger 或模型语义选择。路由基础设施改变时单独运行其零模型回归；模型 evidence 只在明确研究路由行为或诊断已发生的路由失败时由显式 refresh 按 planner 增量产生，任何部署、Status 或测试不得静默触发模型。

## CON-001 原实施周期不部署到真实 Codex 根

- 状态: superseded
- 来源: 项目逐次发布授权合同；当前用户只要求完善与验证

原实施周期允许安装并验证独立 Codex CLI、修改仓库真源、运行独立评估、Validate、提交并同步私有远端，但不向真实 Codex 根目录部署。后续用户已经分别授权真实部署；本条只保留历史边界，不定义当前授权，也不涉及 Release。
