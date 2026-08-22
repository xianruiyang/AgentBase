# Windows sandbox 所有权修复设计

## DES-001 分离便携命令策略与宿主 Windows 后端

- 状态: confirmed
- 关联目标: REQ-001, AC-001, AC-002

`global/config.toml` 继续拥有跨机器稳定的 `sandbox_mode`，但 `windows.sandbox` 由目标宿主或 Codex UI 唯一拥有。评测 elevated 隔离是测试运行时职责，只由 `development/agent-evaluation` 的显式入口选择和初始化，不向日常 Codex 配置投影。

## DES-002 用 transferred 生命周期退出旧 owner

- 状态: confirmed
- 关联目标: AC-001, AC-003

部署资产生命周期保留 `config:windows/sandbox` 的稳定身份，把状态从 `present` 改为 `transferred`。该状态携带最后一次受管 provenance，但不产生写入或删除动作；新的主机也不会从 portable source 获得该键。
