# 方案

## SOL-001 改为阶段可见指纹与语义 Routing 绑定

- 状态: completed
- 解决: GAP-001
- 关联: DES-001, REQ-001

升级 capsule/result schema 与 fingerprint schema；Routing、Policy、References 分别计算候选和输入身份，Policy 删除 Routing 依赖，References 只绑定相关条件引用选择。隐藏 oracle 变化继续直接复验旧结果。

## SOL-002 增加增量计划与 evidence reuse

- 状态: completed
- 解决: GAP-001, GAP-002
- 关联: DES-002, DES-004, REQ-002, REQ-003

增加 model/machine 双视图 planner、Reuse 收据、阶段 receipt ID 和可复用 merge。用回归覆盖零运行、单阶段变化、Routing/Policy 并行、References 延后判断、协议变化全阶段失效、来源 evidence 篡改拒绝和六收据上限。

## SOL-003 增加隔离 Codex runner

- 状态: completed
- 解决: GAP-003, GAP-002
- 关联: DES-003, REQ-002, REQ-003

把 bootstrap 与 evaluator 共享的 npm 原生 CLI 布局收口到 `development/common/codex_cli_runtime.ps1`，把模型 shell 过滤收口到同目录的共享 JSON policy，并把临时 home/auth hardlink、仓库外 workdir、read-only/ephemeral、结构化输出和 Begin/Finish 收口到唯一 runner。runner 校验 policy hash 后生成严格 `-c` 参数，未来 evaluator runtime 记录该 hash；cases-only 成功路径仍拒绝所有 tool event，当前 capsule/evidence 不因不可见安全加强重采样。失败保存有界分类收据并清理临时状态，不保存模型原始日志。

## SOL-004 完成一次 schema 迁移与独立刷新

- 状态: completed
- 解决: GAP-001, GAP-002, GAP-003
- 依赖: SOL-001, SOL-002, SOL-003

因 evaluator 协议本身变化建立新的三阶段证据；Routing 与 Policy 可并行，References 在 Routing 后运行。后续 generation 以 staging 跨代搬运仍有效阶段：最终当前证据只重新运行 References，随后同一正式入口返回 `already-current` 和零模型调用。完成部署 Validate，但不 Publish。

## SOL-005 建立统一确定性测试与正式门禁消费者

- 状态: superseded
- 解决: GAP-004
- 关联: DES-006, REQ-004

增加并行、限时、限输出的统一基础设施测试入口和模型禁用边界，把现有六组回归收口为一个零 Token 命令。该研究基础设施及其回归仍保留；把它和模型 evidence 接成部署消费者的部分已由 SOL-006 替代。回归继续覆盖跨代搬运中途崩溃续传、测试禁用 evaluator 和所有失败路径进程/临时状态清理。

## SOL-006 退出模型 evidence 的部署职责

- 状态: completed
- 解决: GAP-006
- 关联: DES-007, REQ-004, AC-010

保留确定性触发合同、隔离 evaluator、planner、收据和恢复能力，但把模型 refresh 定位为显式路由研究。删除 Validate、Deploy、Status 和新部署 manifest 对 `current.json` 及 attempt ledger 的读取、匹配和机器身份投影；部署继续以 payload 指纹、managed-asset lifecycle 和回滚目标形成完整闭环。

新 manifest 使用 schema 9；schema 8 历史部署继续可被 Status 与 Rollback 读取，其旧 routing evidence 字段不再参与当前性判断。项目规则和组件说明不再要求规则或 skill 修改后为了部署刷新模型 evidence；只有实际研究路由行为、诊断已发生的路由失败，或修改 evaluator 基础设施时才进入相应研究与确定性回归入口。
