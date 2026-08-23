# 当前状态与差距

## OBS-001 0.4.1 cursor 与 snapshot 能精确续页但模型动作冗长

- 状态: confirmed
- 关联: AC-001, AC-002, CON-003

`srcq 0.4.1` 在首个未完成 model 页面持久化完整原生捕获，以 `q1.<snapshot>.<view>.<offset>` 生成 cursor；续页会核对 backend、engine/version、cwd 与原生 argv fingerprint 并从 snapshot 投影，已有证据证明不重扫。但 model `@next` 同时重复 query 控制面、cursor 和全部原生 argv，模型必须准确复制一整串不透明文本。

## OBS-002 真实使用推翻了完整长命令已经模型友好的结论

- 状态: confirmed
- 关联: AC-001, AC-003, UDES-001

用户在 2026-08-22 直接观察到当前分页要求填写长 cursor，模型复制正确率和使用便利性仍差；随后的项目源码定位查询也实际返回了包含 32 位 snapshot、view、offset、正则、路径和 glob 的完整 `@next`，续页动作本身显著重复当前判断不需要的内容。该反例覆盖 0.4.1 的 model 交互结论，不推翻 machine cursor 或 snapshot 正确性。

## OBS-003 当前候选已形成同 owner 短句柄路径

- 状态: confirmed
- 关联: AC-001, AC-002, AC-003, CON-003

当前 `0.4.2` 候选增加根级 `srcq more <HANDLE>` 与有界 continuation registry。第一条真实 scc fixture 路径已由 PowerShell 7 直接从 `@next srcq more q1` 取得第二页，特殊 argv 保持且原生 invocation log 为 1；并发八个进程分配到八个不同句柄，缺失或 payload 损坏的句柄以 code 125 失败且调用次数不增加。

## GAP-001 模型必须重建未显示的控制面语法

- 状态: resolved
- 关联: REQ-001, AC-001, AC-003, OBS-002, OBS-003

0.4.1 虽然不再要求模型从游标片段重建语法，却把同一复杂度变成需要逐字复制的完整命令，仍由模型承担无必要的 cursor/argv 传递。0.4.2 候选把这些状态收回 query owner，model 只传递短句柄；纵向、并发和拒绝路径已经覆盖原错误机制，machine cursor 与显式 offset 没有改变。

## OBS-004 0.4.2 存储有界但可见编号持续增长

- 状态: confirmed
- 关联: REQ-002, AC-004, AC-005, CON-004

0.4.2 只有需要续页、machine full 或 full receipt 时才持久化查询快照，最多保留 32 份 snapshot 和 128 条 continuation 记录；旧记录会淘汰，并非每次读取永久保存。但新句柄取现存最大十进制编号加一，淘汰仍按数值从小到大，因此可见编号跨任务持续增长，且直接回卷会错误删除新生成的低编号记录。

## GAP-002 临时句柄生命周期与无限可见编号不一致

- 状态: resolved
- 关联: REQ-002, AC-004, AC-005, OBS-004

0.4.2 把有界临时游标的显示编号当成持续增长序列，造成无必要的长编号；只对分配器取模又会被旧的数值淘汰顺序破坏。0.4.3 候选已在同一 continuation registry owner 中实现六位环形分配、环形年龄淘汰和活动记录不覆盖，并保留旧七位记录的过渡读取；完整组件验证已通过，Release 与真实安装证据另见验证记录。
