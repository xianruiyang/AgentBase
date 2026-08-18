# 生成式模型导航摘要现状与证据

## OBS-001 当前真实 TASK_TABLE 展开全部零状态与零结果

- 状态: confirmed
- 来源或证据: `docs/work/20260817_model_visible_tool_output_contract/TASK_TABLE.md`
- 事实/推断/未知: 事实
- 关联目标: AC-001
- 可证明上限: 已闭环四任务工作区除 `done:4` 外仍列出六个零状态、需复核零和五类零结果问题

## OBS-002 当前真实 WORK_STATUS 重复同类默认值

- 状态: confirmed
- 来源或证据: `docs/work/20260817_model_visible_tool_output_contract/WORK_STATUS.md`
- 事实/推断/未知: 事实
- 关联目标: AC-001, AC-002
- 可证明上限: 阶段摘要列出三项零闭合计数，任务区列出六个零状态及多项零结果问题；“未决 ID：无”已是正确语义空结论

## OBS-003 完整任务行仍是必要导航

- 状态: confirmed
- 来源或证据: 同一 TASK_TABLE 的四项任务行与既有占位回归
- 事实/推断/未知: 事实
- 关联目标: AC-003
- 可证明上限: 明细行承担对象、状态、owner、依赖、结果引用和 revision 定位，不能按摘要零值规则删除

## GAP-001 stdout 已消费者化而生成导航摘要仍固定展开

- 状态: resolved
- 来源或证据: OBS-001—OBS-003 及本轮 taskctl/workctl model projection
- 事实/推断/未知: 直接比较两个正式读取面推出
- 关联目标: REQ-001
- 可证明上限: 修正应位于 Markdown render owner，不改变 machine summary 或真源
