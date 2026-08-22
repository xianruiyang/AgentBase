# 完成审计

| 目标 | 当前状态 | 直接证据与剩余边界 |
| --- | --- | --- |
| REQ-001 / AC-001 | verified in candidate | model 页尾为 `@more` + `@next srcq more q<number>`；不再暴露 cursor、控制面或 argv |
| AC-002 | verified in candidate | 特殊 argv 从记录恢复，snapshot fingerprint 通过，fixture 原生调用次数保持 1；machine cursor 未变 |
| AC-003 / UDES-001 | verified in candidate | PowerShell 7 从第一页短命令直接取得第二页；并发、缺失和损坏边界均有工具事件 |
| CON-001 / CON-002 | superseded | 用户已明确替代旧“禁止 more”和“禁止安装/Publish”边界；历史证据保留但不约束当前周期 |
| CON-003 | verified in candidate | 无参数 last-query 未实现；每页不可变新句柄、受管周期内单调不复用；过期不误指或重扫 |

query model renderer、CLI、同 owner spool、source-query skill、组件文档、交付链与静态合同已经迁移，0.4.2 仓库候选的最小充分验证通过。正式 release、真实安装、Codex Publish、部署读回和 Git 最终同步仍未完成，因此 P14 与本周期整体状态保持开放；这些外部门禁完成且没有适用失败后再更新为已完成。
