# Windows sandbox 所有权修复需求

> 生命周期：历史完成记录。2026-08-30 起，评测运行时合同已由 `docs/work/20260830_development_environment_governance/` 接替；本文关于 `sandbox-setup`、elevated 评测后端和候选 runner 的现在时描述只说明当时边界，不再定义当前入口或待办。当前合同以 `development/agent-evaluation/README.md`、`docs/requirements.md` 和 `docs/plan.md` 为准。

## REQ-001 AgentBase 发布不得阻断 Codex 正常启动

- 状态: confirmed
- 来源: 用户报告 Codex 因 Windows 设置未完成而无法启动，并要求从根上修复
- 关联: AC-001, AC-002, AC-003, CON-001

AgentBase 的可移植设置不得替目标机器选择或初始化需要宿主能力与用户批准的 Windows sandbox 后端，也不得在普通 Codex 启动时制造必须关闭 sandbox 才能恢复的前置条件。

## AC-001 Windows sandbox 后端由宿主单独拥有

- 状态: confirmed
- 关联: REQ-001

`global/config.toml` 不再定义 `windows.sandbox`；其既有稳定身份从 `present` 显式迁移为 `transferred`。部署合并、Status、Publish 和 Rollback 保留宿主当前值，不删除、不覆盖，也不把它计入当前 portable contract。

## AC-002 评测隔离不依赖全局启动配置

- 状态: confirmed
- 关联: REQ-001

Windows SWE 评测继续只由显式 `sandbox-setup` 和候选 runner 使用 elevated 后端；日常 Validate、Publish 和 Codex 启动不初始化该后端，也不从全局 portable config 继承这一职责。

## AC-003 修复必须覆盖迁移与复发门禁

- 状态: confirmed
- 关联: REQ-001

聚焦测试须证明宿主 `windows.sandbox` 值经过 portable merge 与完整部署发布后保持不变，生命周期收据为 `transferred`，既有 provenance 保留且不进入退休删除；正式 Validate 通过后才形成候选。

## CON-001 本轮不继承 Codex Publish 授权

- 状态: confirmed
- 来源: 项目逐次发布合同；用户本轮只要求修复问题，未明确授权新的 Publish
- 关联: REQ-001

可以修改、验证、提交和同步仓库；不得调用真实 Codex Publish。当前宿主已由用户恢复为 `unelevated`，仓库修复完成后以只读 Status 报告尚待发布的生命周期清单差异。
