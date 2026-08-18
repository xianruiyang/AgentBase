# workctl 模型回执投影方案

## SOL-001 修正 baseline 状态与诊断投影

- 状态: implemented
- 解决: GAP-001
- 满足: AC-001
- 动作与结果: helper 改用 `status` 并补齐 confirmation ref；status 与 coverage 按各自顶层诊断能力选择是否内嵌详细问题
- 依赖: DES-001, DES-002
- 风险: 仅改变 model 字段，machine status/快照不变
- 验证: drifted projection 与 status/coverage 去重测试

## SOL-002 增加 protect/render/impact 专用投影

- 状态: implemented
- 解决: GAP-001
- 满足: AC-002, AC-003
- 动作与结果: protect 返回当前保护回执，render 复用 status 稀疏摘要，impact 只在截断时返回总数
- 依赖: DES-003, DES-004
- 风险: 依赖旧默认文本做程序解析的消费者应使用既有 machine 视图
- 验证: 默认 CLI 与 machine/永久资产对照、真实截断与完整列表场景、完整回归
