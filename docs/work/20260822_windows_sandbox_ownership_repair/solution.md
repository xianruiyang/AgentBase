# Windows sandbox 所有权修复方案

> 生命周期：历史完成记录。2026-08-30 起，评测运行时合同已由 `docs/work/20260830_development_environment_governance/` 接替；本文关于 `sandbox-setup`、elevated 评测后端和候选 runner 的现在时描述只说明当时边界，不再定义当前入口或待办。当前合同以 `development/agent-evaluation/README.md`、`docs/requirements.md` 和 `docs/plan.md` 为准。

## SOL-001 移交 Windows sandbox 后端并闭合部署消费者

- 状态: verified-and-published
- 解决: GAP-001
- 满足: REQ-001, AC-001, AC-002, AC-003, CON-001

已从 portable source 与静态 allowlist 移除 `[windows] sandbox`，把稳定生命周期身份迁移为 `transferred`；global/deployment 文档明确宿主和评测的独立 owner。portable merge、完整部署与生命周期测试分别证明宿主值保留、实际 Publish 消费者不覆盖该值、收据保留 provenance 且不安排删除。正式 Publish 的 `changed=0`，证明没有改写安装文件；发布后 Status 确认当前 `unelevated` 保持、生命周期为 `transferred` 且 gap 0。
