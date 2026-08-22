# 完成审计

| 目标 | 当前状态 | 直接证据与剩余边界 |
| --- | --- | --- |
| REQ-001 / AC-001 | verified and released | model 页尾为 `@more` + `@next srcq more q<number>`；不再暴露 cursor、控制面或 argv |
| AC-002 | verified and released | 特殊 argv 从记录恢复，snapshot fingerprint 通过，fixture 原生调用次数保持 1；machine cursor 未变 |
| AC-003 / UDES-001 | verified and released | PowerShell 7 从第一页短命令直接取得第二页；并发、缺失和损坏边界均有工具事件；已安装 0.4.2 与 Windows SWE 哈希固定消费者均完成真实续读 |
| CON-001 / CON-002 | superseded | 用户已明确替代旧“禁止 more”和“禁止安装/Publish”边界；历史证据保留但不约束当前周期 |
| CON-003 | verified and released | 无参数 last-query 未实现；每页不可变新句柄、受管周期内单调不复用；过期不误指或重扫 |

query model renderer、CLI、同 owner spool、source-query skill、Windows SWE 预检消费者、组件文档、交付链与静态合同已经迁移。0.4.2 可重复构建、私有 Release、真实安装、doctor、路由合同、正式 Validate、Codex Publish 和发布后 Status 均有直接证据，源码提交已同步到私有远端；P14 与本周期整体状态关闭。当前任务不会追溯加载刚发布的规则与 skill，模型行为仍须由新任务或重启后的运行消费，这属于部署生命周期边界，不是 P14 未闭合实现项。
