# Windows sandbox 所有权修复验证

| 检查 | 结果 | 证明范围 |
| --- | --- | --- |
| `test_portable_config.ps1` | pass | portable merge 保留宿主 `[windows] sandbox = "unelevated"`，该值不进入受管 projection，重复合并保持稳定 |
| `test_managed_asset_lifecycle.ps1` | pass | `present → transferred` 保留最后受管 fingerprint，不产生 retired config 删除 |
| `test_manage_agentbase.ps1` | pass | 完整模拟 Publish、Status、增量发布和 Rollback 保留宿主值；manifest 收据把 `config:windows/sandbox` 标记为 `transferred`；模型 evaluator 禁用 |
| 正式 `manage_agentbase.ps1 -Action Validate` | pass；67 tests | portable source、生命周期、部署、路由和 evaluator-disabled Windows SWE 基础设施合同有效；未触发 elevated setup、管理员批准或模型 |
| 真实 `DirectCompatibility + InstallPortableSettings Status` | `installed_matches_source=true` | 本机仍为 `sandbox = "unelevated"`，新源码不再把它识别为安装漂移；旧 manifest 的 source/install/lifecycle 收据过期，因此 formal publication 仍为 false |

当前运行和仓库复发机制已经验证；真实 Publish 与发布后 gap 0 仍需用户针对该次操作明确授权。
