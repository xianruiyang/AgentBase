# Windows sandbox 所有权修复方案

## SOL-001 移交 Windows sandbox 后端并闭合部署消费者

- 状态: verified-in-repository
- 解决: GAP-001
- 满足: REQ-001, AC-001, AC-002, AC-003, CON-001

已从 portable source 与静态 allowlist 移除 `[windows] sandbox`，把稳定生命周期身份迁移为 `transferred`；global/deployment 文档明确宿主和评测的独立 owner。portable merge、完整部署与生命周期测试分别证明宿主值保留、实际 Publish 消费者不覆盖该值、收据保留 provenance 且不安排删除。正式 Validate 通过，真实安装 Status 也确认当前 `unelevated` 值不再属于 source contract；本轮没有 Publish。
