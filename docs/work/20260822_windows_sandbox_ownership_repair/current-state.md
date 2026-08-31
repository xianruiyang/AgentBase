# Windows sandbox 所有权修复现状

> 生命周期：历史完成记录。2026-08-30 起，评测运行时合同已由 `docs/work/20260830_development_environment_governance/` 接替；本文关于 `sandbox-setup`、elevated 评测后端和候选 runner 的现在时描述只说明当时边界，不再定义当前入口或待办。当前合同以 `development/agent-evaluation/README.md`、`docs/requirements.md` 和 `docs/plan.md` 为准。

## OBS-001 全局 portable source 错误拥有 elevated 后端

- 状态: confirmed
- 来源: `global/config.toml`、部署生命周期和发布清单

事故时项目真源定义 `[windows] sandbox = "elevated"`，并把 `config:windows/sandbox` 登记为 `present`。该值会要求 Codex 在启动时使用尚未完成宿主初始化的 elevated 后端；用户切换到 `unelevated` 后恢复启动。

## OBS-002 最近一次 srcq Publish 没有写配置

- 状态: confirmed
- 来源: `AgentBase-20260822-153600-61708e97/manifest.json` 与事故后 Status

15:36 的 Publish 只替换三个 `source-query` 文件，未写 `config.toml`。事故后 Status 显示源码和发布清单仍一致，而安装配置因用户恢复为 `unelevated` 与二者不同；因此本次 Publish 不是写入动作，但此前 AgentBase portable settings 是错误值的长期 owner。

## OBS-003 评测已有独立显式 elevated owner

- 状态: confirmed
- 来源: `development/agent-evaluation` 正式入口与确定性门禁

只有 `sandbox-setup` 可以初始化持久 elevated runtime；普通 Validate/Publish 不运行该入口。全局配置不需要也不应复制评测后端选择。

## GAP-001 宿主选择与测试选择被错误耦合

- 状态: confirmed
- 关联: REQ-001, DES-001, OBS-001, OBS-003

同一个 `elevated` 值既被当作日常 Codex 启动配置，又被当作评测隔离前提，导致未完成的测试宿主设置阻断普通应用启动，并使后续 AgentBase 发布可能覆盖用户恢复值。
