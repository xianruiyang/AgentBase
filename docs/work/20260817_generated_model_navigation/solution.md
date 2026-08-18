# 生成式模型导航摘要方案

## SOL-001 稀疏生成 Task 导航摘要

- 状态: implemented
- 解决: GAP-001
- 满足: AC-001, AC-002, AC-003
- 动作与结果: taskctl render 只列非零状态/问题，以一句话表达无结果或无任务，保留结果存在时的验证数和完整任务明细
- 依赖: DES-001, DES-002
- 风险: 只改变可重建 Markdown 排版；machine render 和任务文件不变
- 验证: review/无结果、完成结果、损坏结果、空单元格占位和 model/machine 回归

## SOL-002 稀疏生成 Work 导航摘要

- 状态: implemented
- 解决: GAP-001
- 满足: AC-001, AC-002
- 动作与结果: workctl render 省略零语义/任务/问题行，显式表达无任务、partial/unavailable 和无结果，未决 ID 空结论保持
- 依赖: DES-001, DES-003
- 风险: 只改变可重建 WORK_STATUS；索引、保护快照、任务摘要和 machine JSON 不变
- 验证: 空任务、partial、真实结果/诊断、确认来源与完整回归
