# 模型可见工具输出合同：方案设计

## SOL-001 建立最低充分作用域的正式规则链

- 状态: confirmed
- 解决: GAP-001
- 满足: REQ-001, REQ-002, DES-001, DES-002

在项目根需求增加消费者感知输出目标；在全局 AGENTS 只加入模型调用时的消费者选择、字段准入、同源投影和格式测量原则；在项目 AGENTS 加入开发与验证责任。taskctl/workctl 的命令、字段和迁移动作只写入各自 skill/tooling，不把领域协议常驻全局规则。

验证：检查三层职责无重复决定、规则结构与静态合同通过，并由脱离仓库的评估确认新原则没有迫使普通工具总是加载机器输出。

## SOL-002 为 taskctl 建立默认 model 与显式 machine 视图

- 状态: confirmed
- 解决: GAP-001, GAP-002
- 满足: REQ-001, REQ-002, REQ-003, DES-003, DES-004
- 依赖: SOL-001

保留现有 handler 与 JSON 字段作为同一权威机器结果，增加统一 view 选择和模型文本 renderer。status、context、completion-context 采用命令专属投影；普通成功省略 envelope、空值和正常零值，错误保留 gate、原因与恢复。模型 Token 预算使用与 srcq 同类的保守估算，在 renderer 前按语义单元保留核心信息和精确续查；machine 继续使用现有字符预算和 pretty JSON。CLI 自身固定 stdout/stderr UTF-8，并在不设置 `PYTHONUTF8` 的宿主入口复测中文。

任务执行 context 因结果合同需要继续返回现有 source_snapshot 映射；completion-context 只返回来源问题诊断和证据摘要，不复制完整映射。本版本不改变快照事实、结果时效或分页裁决。

验证：现有 JSON 测试全部显式使用 machine 并保持通过；新增默认 model、低预算、异常、completion-context 无完整快照和真实工作区决策覆盖测试。

## SOL-003 为 workctl 接入同一输出面合同

- 状态: confirmed
- 解决: GAP-001, GAP-002
- 满足: REQ-001, REQ-002, REQ-003, DES-003, DES-004
- 依赖: SOL-001

workctl 使用与 taskctl 相同的 view 名称、默认选择、模型文本语法、UTF-8 输出和 Token 估算，但在 delivery-workflow owner 内独立决定 status、context、coverage、impact 等字段优先级。受保护目标内容、实际关系和分页事实仍来自现有 index；renderer 不重判阶段或完成语义。

验证：现有 JSON 回归显式 machine 后保持通过；新增 model 状态、上下文、错误、低预算和机器一致性测试。

## SOL-004 迁移消费者并验证完整决策链

- 状态: confirmed
- 解决: GAP-003
- 满足: AC-003, AC-005, AC-008, DES-005, CON-001
- 依赖: SOL-002, SOL-003

更新两项 skill、tooling、项目静态合同和适用触发评估，使模型调用默认消费 model，程序示例显式选择 machine。使用当前真实工作区分别采集典型 status、context、completion-context，逐项确认关键状态、异常、证据与恢复入口没有丢失，再比较 machine/model 的估算 Token 和适用 tokenizer 计数；只有质量证据成立时记录节省。

沿根 README 的正式 owner 复核其他模型可见或机器协议入口，分别确认已由 srcq 覆盖、保持 machine-only、需要独立生命周期合同或仍缺真实质量证据；不得因为建立了全局原则就把 task/work renderer 机械复制到事件日志、推理深度、QQ、MCP 或部署工具，也不得把它们误标为已经迁移。

验证：两组件回归、静态合同、路由/策略/引用评估、部署候选 Validate 和真实输出审计通过。正式 Publish 不属于本方案的隐含动作，必须另获当次授权。
