# 执行控制与 Skill 上下文生命周期：完成审计

## 目标证据

| 目标 | 当前结果与直接证据 | 判定 |
| --- | --- | --- |
| AC-007 按端到端成本渐进加载上下文 | 每轮重新路由与正文有效性已经分离；未压缩复用、压缩后按需恢复、历史未选 skill 不重载、已知变化重读均有独立场景 | 满足 |
| AC-024 纳入目标成立所需的职责调整 | 全局规则要求在继续失效方案前说明并返回最早失效层；实施中发现共享 owner 被复制的场景选择 `change-governance` 与 `architecture_integrated` | 满足 |
| AC-036 有效规划后优先形成纵向验证闭环 | 建立计划改由跨步骤不确定性、依赖、顺序、分工、验收或恢复状态决定；复杂正例和简单反例均通过独立 Policy | 满足 |

## 职责与消费者闭合

- `docs/requirements.md` 持有长期验收语义；`global/AGENTS.md` 持有跨项目执行控制和 skill 上下文生命周期不变量。生命周期属于全局选择与上下文 owner，不复制到 11 个 skill 正文。
- `global/README.md` 只更新稳定能力索引；`development/skill-routing/trigger-cases.json`、`validate_contract.ps1` 和 `evidence/current.json` 分别消费标签定义、机械合同和独立证据，没有建立第二套行为真源。
- 没有新增 skill 缓存、版本账本、Hook、每轮文件探测或 Goal 状态；当前上下文决定正文是否可用，已知内容变化直接使旧正文失效。
- 11/11 skill 的正向与非触发覆盖仍成立；三阶段证据和部署 validator 消费同一候选 bundle，没有用静态规则存在或 Token 变短替代行为 oracle。
- 没有改变 `source_snapshot`、插件迁移、远程 CI、工具输出合同或真实 Codex 安装内容。

## 完成判定

当前范围的需求、正式 owner、正反例、压缩边界、成本边界、独立 Routing/Policy/References 和部署候选均已闭合，没有适用验证失败或同责第二入口。当前范围作为未发布仓库候选已完成；由于本轮没有当次发布授权，真实 Codex 继续使用上一次已发布内容，候选行为尚未在新任务中做运行时验收。
