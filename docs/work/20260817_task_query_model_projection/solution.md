# Task 查询模型投影方案

## SOL-001 增加 show/list/relation/next 专用投影

- 状态: implemented
- 解决: GAP-001
- 满足: AC-001, AC-002, AC-003
- 动作与结果: show 去除重复信封；列表、关系和 next 区分完整列表、截断页与语义空结果；非空诊断及截断恢复保留
- 依赖: DES-001—DES-003
- 风险: 只改变默认 model 表示；旧程序解析者继续使用显式 machine
- 验证: 默认 CLI/machine 对照、真实已闭环工作区读回、空/非空/续页场景与完整回归

## SOL-002 补齐 impact 分页参数

- 状态: implemented
- 解决: GAP-001
- 满足: AC-004
- 动作与结果: impact parser 注册 `--after-id`，保持对 dependents handler 和递归算法的单一复用
- 依赖: DES-004
- 风险: 无 machine 字段或图语义变化
- 验证: 默认 impact、非空关系和 after-id 续页回归
