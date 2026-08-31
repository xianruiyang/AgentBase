# Windows sandbox 所有权修复完成审计

> 生命周期：历史完成记录。2026-08-30 起，评测运行时合同已由 `docs/work/20260830_development_environment_governance/` 接替；本文关于 `sandbox-setup`、elevated 评测后端和候选 runner 的现在时描述只说明当时边界，不再定义当前入口或待办。当前合同以 `development/agent-evaluation/README.md`、`docs/requirements.md` 和 `docs/plan.md` 为准。

| 目标 | 状态 | 直接证据与边界 |
| --- | --- | --- |
| REQ-001 / AC-001 | verified and published | 用户恢复后的 `unelevated` 可以启动；项目真源已删除该键，正式 manifest 生命周期为 `transferred`，发布后 Status 为 formal published、gap 0 |
| AC-002 | verified | 评测 elevated 后端仍只由显式 `sandbox-setup` 与候选 runner 拥有；正式 Validate/Publish 合同不初始化它 |
| AC-003 | verified and published | 配置、生命周期、完整部署消费者和正式 Validate 均通过；真实 Publish 为 `changed=0`，发布后宿主值不变且 gap 0 |
| CON-001 | superseded by explicit authorization | 用户随后明确授权本次 Publish；只执行该次发布，没有继承为后续授权 |

错误 owner、未来源码覆盖机制和旧发布收据均已闭合。当前 Codex 保持 `unelevated`，AgentBase 不再拥有 Windows sandbox 后端；本修复没有开放实施或部署项。
