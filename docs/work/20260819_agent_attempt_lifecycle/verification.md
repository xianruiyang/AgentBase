# 验证记录

## Agent 与部署生命周期

- `test_portable_agents.ps1`：通过；固定 `evidence`、`experiment` 语义身份和安全 schema，但允许未来只在 TOML 中替换模型与受支持档位；名称错配、危险模型标识、重复语义、未知档位、额外字段和敏感内容均被拒绝。
- `test_portable_config.ps1`：通过；未分类子代理回退读回为 Luna/medium，宿主主线程模型、默认推理深度和 Windows sandbox 继续不归 portable settings 所有。
- `test_managed_asset_lifecycle.ps1`：通过；新 skill 与两份语义代理为 present，旧 Luna/Sol 与 Terra 为 retired，生命周期转换有效。
- 首次干净候选 `test_manage_agentbase.ps1` 暴露最终评测把项目自定义代理与评测运行 profile 错当成同一集合，46 项确定性测试中 6 error、1 failure。修复位于原消费者：`candidate_capability_contract` 分别投影项目 `evidence/experiment` 与独立 evaluator `Sol/medium、Luna/max`；当前 dirty 工作树的该目标测试 1/1 通过。
- 修复后的独立暂存 worktree 中，`test_manage_agentbase.ps1` 全部通过；其多次嵌入的 Windows SWE 确定性门禁每次均为 46/46，默认/portable settings/Plugin、Status、Publish 沙箱、退役路径和 Rollback 全部闭合，没有触碰真实 Codex。
- 同一干净候选的正式 `manage_agentbase.ps1 -Action Validate` 返回 `valid: true`。

## 正式尝试生命周期

- `development/skill-routing/test_routing_attempt_history.ps1`：通过；覆盖 baseline 导入、Begin/Finish、执行失败、未完成阻断、带理由的第二次尝试、第三次拒绝、merge attempt ID 绑定和周期轮换哈希链。
- `development/skill-routing/validate_routing_attempt_history.ps1`：当前 schema 2 账本有效，活跃周期为 3/6 收据，每个不变输入最多两次。
- `development/skill-routing/validate_contract.ps1`：通过；93 cases、52 strict routing、10 strict references，11/11 skill 具备正向与非触发覆盖，并静态约束两阶段入口、执行失败、三 attempt ID 合并和活跃周期上限。

## 历史发布与当前候选边界

- 初始实施完成后的真实 `DirectCompatibility + InstallPortableSettings Status` 只读返回 `published:false`；差距包括已安装 payload/manifest 与当前源码不一致、生命周期清单陈旧和退役 Terra 仍存在。
- 用户随后明确授权本次发布。正式 Publish 返回 `published:true`、`changed:3`，退役路径为 `agents\terra.toml`，唯一回滚备份为 `C:\Users\gzxt\.codex\backups\AgentBase-20260819-001202-f1169bf2`。
- 发布后同范围只读 Status 返回 `published:true`。
- `git diff --check` 退出成功；仅报告 Git 的 CRLF→LF 工作区提示，没有空白错误。
- 本轮没有安装软件；本次 Publish 授权已经消耗。
- 用户随后明确授予 AgentBase 持续 Git 维护与私有远端同步权限。功能改动形成提交 `384c8ed`，持续授权与接手状态形成独立治理提交；两者按非强制方式同步 `main` 到现有 `origin`。

2026-08-23 的语义角色后继候选完成上述确定性验证，并保留根 README、Windows SWE sandbox 候选、`vendor/` 与 requirements 的评测合同 dirty 边界。实现提交 `0aba411` 已非强制推送到私有 `origin/main`。用户单独授权后，从该提交的独立干净 worktree 以 `DirectCompatibility + InstallPortableSettings` 正式 Publish：`published:true`、`changed:16`，退役 `agents\luna.toml` 与 `agents\sol.toml`，回滚备份为 `C:\Users\gzxt\.codex\backups\AgentBase-20260823-030345-c7ac8ea8`；发布后同范围 Status 返回 `published:true`。

## 2026-08-23 should 默认委派修订

- 用户要求不运行独立测试并手动发布；本次没有运行功能测试、完整回归、Windows SWE 或正式部署 Validate/Publish。
- 在用户叫停前，路由刷新的 Routing 与 Policy 阶段已经返回通过；References 阶段随后被终止，并以 `execution_failed` 收据闭合。三阶段没有合并为新 `current.json`，因此它们不构成当前正式路由证据。
- 按用户明确要求，手动将 `global/AGENTS.md`、`subagent-orchestration/SKILL.md`、`agents/openai.yaml` 和 `references/coordination.md` 四个变更文件应用到当前 Codex 根目录；未做发布后 Status 或哈希读回。手动回滚备份为 `C:\Users\gzxt\.codex\backups\AgentBase-manual-20260823-050357`。
- 安装只证明文件复制成功；当前已启动任务不会追溯加载新规则，`should` 触发、非触发和并发选择均未做新任务行为验收。

## 2026-08-23 可逆操作 Experiment 触发修订

- `experiment` 的触发已从“静态证据无法区分路径”扩展为“独立有界的可逆实际操作能够低成本取得改变正式实现裁决的证据”；已有初步方向、未穷尽静态取证或整体仍以正式实现为主都不再构成排除条件。一次便宜定向循环、无法安全隔离或实验不改变裁决仍由主代理直接完成。
- `subagent-orchestration`、`source-query`、`delivery-workflow`、`task-table-manager` 与 `change-governance` 的 skill quick validation 均通过；全局与项目规则合计 28658 bytes，继续满足为 Codex 默认项目指令上限预留至少 4 KiB 的门禁。
- 路由合同为 119 cases、78 strict routing、24 strict references，13/13 skills 均有正向与非触发覆盖；零模型基础设施为 6 suites、22 个 PowerShell 文件、0 模型调用。
- 正式 Routing 刷新依次暴露并修正四个既有 description 边界：受保护待议上游需要重投影任务表、局部架构风险不自动升级完整 delivery、临时路径只读生命周期评审属于 governance、仅据已知事实纠正错误前提不属于 governance。每次都改变 evaluator 可见输入后再评估，没有对同一输入原样重采样；上一代已通过 Policy 由 `staged_carry_forward` 收据迁移，未重复调用模型。
- 最终 generation `94F0F1833032D2C480AB2E126544842C2907ACBFCC8296F53E350DD877BF4D17` 的 Routing、Policy、References 全部通过当前 oracle，后继计划为 0 evaluate、3 reuse、0 blocked/pending。最后一次刷新只运行 Routing 与 References，Policy carry-forward；`manage_agentbase.ps1 -Action Validate` 的 evaluator-disabled Windows SWE 基础设施 67/67 通过并返回 `valid:true`。
- 本次没有运行 Windows SWE 九题、candidate、qualification、外部 Verifier 或 elevated sandbox 初始化；上述证据只覆盖规则/skill 路由、确定性基础设施和部署候选合同，真实子代理选择仍需新任务消费发布后的指令链。
- 用户针对本次操作明确授权后，`DirectCompatibility + InstallPortableSettings` Publish 再次通过 67/67 evaluator-disabled 基础设施检查，返回 `published:true`、`changed:10`，回滚备份为 `C:\Users\gzxt\.codex\backups\AgentBase-20260823-211434-11afc187`；同范围发布后 Status 返回 `published:true`。

## 2026-08-30 固定角色上下文与拓扑隔离

- `evidence`、`experiment`、`operator` 的共同创建合同已收敛为显式且只用 `fork_turns="none"`；上下文只经有界 capsule 传入，三种角色均明确禁止子代理、新任务和分叉入口。`subagent-orchestration` 与后继受影响的 `delivery-workflow` 均通过 skill quick validation，三份 portable agent 配置测试通过。
- 路由评估中的有效反例促成三项收敛：方案验证维度投影任务成为 `delivery-workflow` 的直接触发；任务、状态和证据回流的引用路由统一到公共/执行合同；`operator` 用例只在对象等价依据已确认时排除执行治理。一个不会改变动作且已有原子用例覆盖的重复 Policy 标签从混合反例中退出强制 oracle。
- 正式 evidence generation `261F82CBD070C0B8ECD3904C9A44E679DBDAD84F832588945ABA94EE65186091` 为 0 evaluate、3 reuse、0 blocked/pending；最终刷新仅运行 References，恢复已通过 Routing，并按当前 oracle 零 Token 重验 Policy。合同检查为 125 cases、84 strict routing、28 strict references，13/13 skills 具备正向与非触发覆盖。
- 干净候选的 `manage_agentbase.ps1 -Action Validate` 返回 `valid:true`。本轮没有运行 Windows SWE 九题、candidate、qualification 或 elevated sandbox；固定角色的真实创建参数与后代代理行为仍须新任务消费发布后的指令链验证。
- 用户针对本次操作明确授权后，从提交 `7a277cb` 的独立干净 worktree 以 `DirectCompatibility + InstallPortableSettings` 正式 Publish，更新 8 个受管路径，回滚备份为 `C:\Users\gzxt\.codex\backups\AgentBase-20260830-040053-a40de1f7`；同范围发布后 Status 返回 `published:true`、0 个正式发布缺口，源码、安装、manifest、路由 evidence 与生命周期均一致。
