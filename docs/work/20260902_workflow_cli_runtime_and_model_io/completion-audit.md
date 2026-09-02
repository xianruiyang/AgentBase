# Workflow CLI 运行时与模型输入输出：完成审计

更新时间：2026-09-02

## 当前结论

本专项对用户目标已完成：`workctl` 与 `taskctl` 由 `tools/workflow-cli` 统一维护并形成独立 Windows 安装运行时；当前主机已安装 0.1.0 并具有唯一 User PATH 条目。skill 只消费 PATH 命令，不再携带 CLI 源码或模板。model 视图使用按动作投影与可解析短回执，machine 视图继续保存完整身份和程序合同。

## 目标覆盖

- REQ-001、AC-001、AC-002：独立 owner、版本、受验证包、Install/Upgrade/Status/Uninstall、PATH 与安装目录命令读回已覆盖。
- REQ-002、AC-003：taskctl 的持久来源回执与有界复核回执闭合 capture、complete 和 completion-context 续页；完整内容身份只留在机器资产。
- REQ-002、AC-004：workctl 不再向 model 投影确认引用或建议 machine 兜底，保留动作所需正文、诊断与恢复入口。
- CON-001：本轮只安装主机 CLI；没有向 Codex 根目录部署全局规则或 skill，没有创建标签、Release 或分发资产。
- CON-002：字段选择和短回执解析均由命令 owner 实现，没有通用正则清洗器或第二语义真源。

## 保留边界

- 当前 Codex 宿主需要重启后才会从新增 User PATH 解析命令；这不影响已从安装目录取得的安装读回。
- skill 变更使既有 routing evidence 对当前候选失效。用户未要求本轮运行模型路由评测，因此完整部署测试保持未验证；这不影响 workflow-cli 自身安装和 I/O 验收，也不能作为 Codex Deploy 已就绪的声明。
- 本轮未执行 Codex Deploy/Publish 或组件 Release；后续任一 Codex 部署仍需用户针对当次操作明确授权。
