# Agent 与 Skill 指令面收敛：验证

## 已通过的源码与组件验证

- `development/codex-deployment/test_portable_agents.ps1`：`tests : pass`。覆盖当前三份源角色、独立替换中文正文仍通过、英文模型语义、name/model 身份错配、重复角色、额外字段和敏感内容拒绝。
- `development/skill-routing/validate_contract.ps1`：93 个用例、52 个严格路由、10 个严格引用用例通过；11/11 项目 skill 均有正向与非触发覆盖。新增 Task Table Manager authoring、查询、执行和最终复核动作族进入 References oracle。
- Task Table Manager：`python -m unittest discover -s skills/task-table-manager/tests -p test_*.py` 通过 92/92，用时 100.038 秒；新增顶层帮助断言覆盖 `next` 建议边界、最终复核边界和 `complete` 的 CAS/来源收据职责。
- PowerShell 语法：`portable_agents.ps1`、`manage_agentbase.ps1`、`test_portable_agents.ps1` 与 `validate_contract.ps1` 均可由 `[scriptblock]::Create` 解析。
- 插件 payload：`development/plugin-packaging/build_plugin.ps1` 成功，官方构建产物包含 Task Table Manager 的共享 tooling 与四个动作族引用；构建产物仍是忽略的可重建资产。
- `git diff --check` 通过。

这些检查证明当前源码结构、静态 owner、CLI 行为回归和插件组装成立；custom agent 的真实宿主质量与成本仍不由这些检查证明，skill 路由则由下述 detached evaluator 单独覆盖。

## 独立路由证据

三个不同的 `codex exec --ephemeral` 只读运行分别只消费脱离仓库的 Routing、Policy 和 References capsule；三者均声明未访问仓库或隐藏期望，并使用不同 evaluator id 与 runtime。正式 `merge_routing_evidence.ps1` 已验证身份、输入声明、哈希绑定、case 完整性、严格期望和引用选择后原子刷新 `development/skill-routing/evidence/current.json`：

- candidate bundle SHA-256: `F29BEE77353CCB144A6DAD5EBE9EC054A72D8A7116ADC175ECEA1740C09A1836`
- Routing: 93/93，capsule `8F672E0AD42E55EE8375B9762FDF8BB0AF81524C0574F3819911668B4EE79A1A`
- Policy: 93/93，capsule `9743F54C12DA2F8AB0F3A683A27B4FF5B1C59EA397DD20E452CFE02AE7D63EDC`
- References: 26/26，capsule `1F1DAD2D74A797DA1E4505BCC204D64BAC6440A9BF4E8BA1F5CBAF2776DC7C77`

独立评估在闭合过程中实际暴露并推动了以下真源修正，而不是手改评估结果：

- `change-governance` 明确排除仅需求/风险校准和上游稳定下的常规最终复核；
- `codex-qq-hook` 明确未发送原因未确认时必须联选 `change-governance`；
- `task-table-manager` 明确交付证据改变既有任务合同、依赖、状态或结果时触发；
- `reasoning-governor` 明确已确认固定只需保持、或有效读回已匹配时不重复使用；
- 三个原先隐含 owner、局部门禁或文档权威的案例改为直接表达待验证契约；
- `delivery-workflow` 明确最终复核也先读取公共 artifact contract，跨 taskctl 命令族的 feedback 案例直接表达查询与执行动作。

最终 `validate_routing_results.ps1` 报告三阶段证据满足声明约束；`manage_agentbase.ps1 -Action Validate` 返回 `valid: true`。

## 未验证与非目标

- 未执行 custom agent 的真实宿主路由、质量或成本比较，因此没有改变 `global/config.toml` 的 Luna/max 默认值。
- 2026-08-18 已在用户针对当次操作明确同意后，以 `DirectCompatibility + InstallPortableSettings` 运行正式 `Publish`；入口报告 `published:true`、18 个受管理项改变，回滚备份为 `<CODEX_ROOT>\backups\AgentBase-20260818-180544-7f1850ae`，随后同范围 `Status` 再次读回 `published:true`。当前 Codex 运行不会追溯加载本轮候选，行为仍需在新任务或重启后使用。
- 安装和 srcq 新版本继续按用户要求延后；本轮没有构建、安装或迁移 srcq。
