# Windows sandbox 所有权修复验证

> 生命周期：历史完成记录。2026-08-30 起，评测运行时合同已由 `docs/work/20260830_development_environment_governance/` 接替；本文关于 `sandbox-setup`、elevated 评测后端和候选 runner 的现在时描述只说明当时边界，不再定义当前入口或待办。当前合同以 `development/agent-evaluation/README.md`、`docs/requirements.md` 和 `docs/plan.md` 为准。

| 检查 | 结果 | 证明范围 |
| --- | --- | --- |
| `test_portable_config.ps1` | pass | portable merge 保留宿主 `[windows] sandbox = "unelevated"`，该值不进入受管 projection，重复合并保持稳定 |
| `test_managed_asset_lifecycle.ps1` | pass | `present → transferred` 保留最后受管 fingerprint，不产生 retired config 删除 |
| `test_manage_agentbase.ps1` | pass | 完整模拟 Publish、Status、增量发布和 Rollback 保留宿主值；manifest 收据把 `config:windows/sandbox` 标记为 `transferred`；模型 evaluator 禁用 |
| 正式 `manage_agentbase.ps1 -Action Validate` | pass；67 tests | portable source、生命周期、部署、路由和 evaluator-disabled Windows SWE 基础设施合同有效；未触发 elevated setup、管理员批准或模型 |
| 真实 `DirectCompatibility + InstallPortableSettings Status` | `installed_matches_source=true` | 本机仍为 `sandbox = "unelevated"`，新源码不再把它识别为安装漂移；旧 manifest 的 source/install/lifecycle 收据过期，因此 formal publication 仍为 false |
| 正式 `DirectCompatibility + InstallPortableSettings` Publish | `published=true`、`changed=0` | 只更新正式生命周期收据，没有改写任何安装文件；回滚/收据目录为 `<CODEX_ROOT>\backups\AgentBase-20260822-173018-7cdc4621` |
| 发布后 Status | formal published、gap 0 | 当前值仍为 `sandbox = "unelevated"`；manifest 中 `config:windows/sandbox.state=transferred` |

当前运行、仓库复发机制和正式部署生命周期均已验证；本次 Publish 授权已经消费完毕，不向后续操作继承。
