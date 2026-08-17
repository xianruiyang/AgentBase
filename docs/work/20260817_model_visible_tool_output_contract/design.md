# 模型可见工具输出合同：目标设计

## DES-001 项目根需求拥有消费者感知输出目标

- 状态: confirmed
- 满足: REQ-001, REQ-002, REQ-003, AC-003, AC-008

`docs/requirements.md` 定义任何 AgentBase 工具同时服务模型和程序时必须达到的用户结果与验收顺序；它不规定具体字段或 renderer。

## DES-002 全局规则拥有模型调用时的输出选择不变量

- 状态: confirmed
- 满足: REQ-001, AC-001, AC-002, UDES-001

`global/AGENTS.md` 只规定模型在工具调用前识别消费者、优先请求模型视图、按当前动作渐进取得机器或原始内容，并禁止把格式替换当作语义精炼。具体命令和字段留在工具 owner。

## DES-003 工具由一次权威计算形成两个输出面

- 状态: confirmed
- 满足: REQ-001, REQ-002, AC-004, AC-005, AC-006

每个 CLI handler 继续生成权威领域结果；`model` renderer 形成稀疏、动作相关、预算感知的可读文本，`machine` renderer 保持紧凑或 pretty JSON。两种视图的 stdout/stderr 由 CLI 固定为 UTF-8，不继承会让 Codex 误解码的 Windows 控制台代码页。输出面只投影，不重新计算状态、诊断、分页、证据或完成语义。

## DES-004 相关性投影保留在领域 owner

- 状态: confirmed
- 满足: REQ-003, AC-007

`task-table-manager` 决定任务、依赖、结果、证据和完成复核信息在 taskctl 模型视图中的优先级；`delivery-workflow` 决定阶段、关系、目标保护和影响信息在 workctl 模型视图中的优先级。`srcq` 仅作为已经验证的输出面参考，不成为任务或交付语义 owner，也不新增万能压缩器。

## DES-005 项目验证拥有跨输出面一致性与成本门禁

- 状态: confirmed
- 满足: AC-003, AC-008, CON-001

组件测试验证两个 renderer 消费同一 handler 结果、模型预算按语义单元裁剪、机器结构保持兼容；项目静态合同验证正式规则和两项 skill 均声明输出面。真实工作区审计比较典型 model 与 machine 的判断覆盖和 Token 成本，只有质量先成立时才采纳节省。
