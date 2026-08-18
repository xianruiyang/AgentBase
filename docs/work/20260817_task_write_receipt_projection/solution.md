# Task 写入回执投影方案

## SOL-001 增加合同与状态写入回执投影

- 状态: implemented
- 解决: GAP-001
- 满足: AC-001, AC-002
- 动作与结果: `add/update` 与六个状态写命令进入专用 model projection；永久 handler 和 machine JSON 不变
- 依赖: DES-001—DES-003
- 风险: 依赖旧默认输出做程序解析的调用方必须显式使用既有 `--view machine`
- 验证: 默认 CLI、projection 单元测试、永久文件读回与完整回归

## SOL-002 render 接入既有稀疏状态摘要

- 状态: implemented
- 解决: GAP-001
- 满足: AC-003
- 动作与结果: model render 复用 `task_status_model`，附加输出路径与非零 review 数
- 依赖: DES-004
- 风险: 仅改变默认 model 表示；machine 字段和生成的 `TASK_TABLE.md` 不变
- 验证: model/machine 对照测试与完整回归
