# 验证记录

## Agent 与部署生命周期

- `development/codex-deployment/test_portable_agents.ps1`：通过；固定两份角色文件，Luna/max、Sol/medium，错误档位和额外角色均被拒绝。
- `development/codex-deployment/test_managed_asset_lifecycle.ps1`：通过；当前 present/retired 集合及转换合同有效。
- `development/codex-deployment/test_manage_agentbase.ps1`：首次运行暴露旧测试把所有 retired path 都当作不依赖 portable settings 的 skill，无法覆盖新增的 `agents/terra.toml`。测试消费者改为按生命周期的真实 path、kind、mode 与 settings scope 建夹具后通过；覆盖默认 DirectCompatibility、带设置 DirectCompatibility、Plugin、Status、Publish 沙箱和 Rollback。该测试只在仓库沙箱发布，没有触碰真实 Codex。
- `development/codex-deployment/manage_agentbase.ps1 -Action Validate`：最终返回 `valid: true`。

## 正式尝试生命周期

- `development/skill-routing/test_routing_attempt_history.ps1`：通过；覆盖 baseline 导入、Begin/Finish、执行失败、未完成阻断、带理由的第二次尝试、第三次拒绝、merge attempt ID 绑定和周期轮换哈希链。
- `development/skill-routing/validate_routing_attempt_history.ps1`：当前 schema 2 账本有效，活跃周期为 3/6 收据，每个不变输入最多两次。
- `development/skill-routing/validate_contract.ps1`：通过；93 cases、52 strict routing、10 strict references，11/11 skill 具备正向与非触发覆盖，并静态约束两阶段入口、执行失败、三 attempt ID 合并和活跃周期上限。

## 发布与差异边界

- 初始实施完成后的真实 `DirectCompatibility + InstallPortableSettings Status` 只读返回 `published:false`；差距包括已安装 payload/manifest 与当前源码不一致、生命周期清单陈旧和退役 Terra 仍存在。
- 用户随后明确授权本次发布。正式 Publish 返回 `published:true`、`changed:3`，退役路径为 `agents\terra.toml`，唯一回滚备份为 `C:\Users\gzxt\.codex\backups\AgentBase-20260819-001202-f1169bf2`。
- 发布后同范围只读 Status 返回 `published:true`。
- `git diff --check` 退出成功；仅报告 Git 的 CRLF→LF 工作区提示，没有空白错误。
- 本轮没有安装软件；本次 Publish 授权已经消耗。
- 用户随后明确授予 AgentBase 持续 Git 维护与私有远端同步权限。功能改动形成提交 `384c8ed`，持续授权与接手状态形成独立治理提交；两者按非强制方式同步 `main` 到现有 `origin`。
