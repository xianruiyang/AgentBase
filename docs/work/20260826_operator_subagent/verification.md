# 第三语义执行子代理验证

## 确定性合同

- `subagent-orchestration` 与 `delivery-workflow` skill 结构检查通过。
- portable-agent 合同接受 `evidence`、`experiment`、`operator` 三个独立角色，并继续拒绝身份、模型、档位、额外字段、敏感内容和重复语义反例。
- 123 个路由案例、managed lifecycle JSON、全局/项目指令预算和 13 个 skill 的正向/非触发覆盖通过静态合同；其中 82 个是严格路由案例，27 个是严格引用案例。

## 正式路由 evidence

- 干净源码 generation 为 `C0241F1D3C319C415F969B3C29D67B34FAE589CFDAFFB5FFDC894C17F1F32F76`，最终计划为 `0 evaluate / 3 reuse / 0 blocked / 0 pending`。
- 每个阶段只取得一次模型结果；Routing 直接通过，Policy 在删除与案例核心无必然关系的隐藏附加标签后重验原结果，References 在修正规则后使用新输入通过，没有对相同可见输入重采样。
- 失败反例形成两项长期修正：维度案例明确“方案 Markdown + taskctl update”的唯一动作与引用集合；Delivery 按实际修改类型选择引用，只有同次修改方案语义和任务/结果合同才双读 planning/execution，单向消费已确认方案只读 execution。
- `authority-change-impact-closure` 不再把普通契约影响闭环强制等同于需求或用户设计基线冲突；受保护基线仍由专门正向案例覆盖。
- 首次干净部署 Validate 证明评测运行时已动态投影 `operator`，但 `candidate_capability_contract` 的确定性测试仍固定期望两个角色；已把该唯一固定集合消费者更新为三角色，评测运行时和最终九题合同不变。

## 发布前待验收

- 部署 Validate 覆盖新资产安装、回滚和生命周期，Windows SWE evaluator 保持禁用。
- 正式 Publish 后同范围 Status 为 published，实际安装中三个配置与源码指纹一致。

规则文件和路由 evidence 只能证明候选结构与选择合同，不证明新任务中的真实模型行为；后者出现反例时按完成审计中的重开条件处理。
