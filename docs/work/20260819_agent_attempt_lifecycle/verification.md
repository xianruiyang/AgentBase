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

2026-08-23 的语义角色后继候选已完成上述确定性验证，并保留根 README、Windows SWE sandbox 候选、`vendor/` 与 requirements 的评测合同 dirty 边界。本轮用户已单独授权一次按真实安装模式发布；本节在 Publish 与 Status 读回后补充实际收据。
