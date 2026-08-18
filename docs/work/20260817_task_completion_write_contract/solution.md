# Task completion 写入合同方案

## SOL-001 分离语义输入和永久结果验证

- 状态: confirmed
- 解决: GAP-001, GAP-003
- 满足: AC-001, AC-002, AC-004

新增 completion 输入规范化层：默认接受语义正文，由 CLI 注入机器 envelope；读取与部分写恢复继续使用永久结果验证器。识别上一版完整 envelope 时校验并单向规范化，同时返回迁移诊断。

## SOL-002 增加 task revision CAS

- 状态: confirmed
- 解决: GAP-001
- 满足: AC-001, AC-005
- 依赖: SOL-001

为 `complete` 增加必需的 `--expected-task-revision`，在锁内先比较当前任务合同，再处理任何快照或结果写入。语义输入永久结果使用该 revision；旧 envelope 必须与其一致。

## SOL-003 在写前门禁失效收据身份

- 状态: confirmed
- 解决: GAP-002
- 满足: AC-003, AC-005
- 依赖: SOL-001, SOL-002

在结果文件和状态文件发生变化前解引用所选收据。资产缺失、不可读或内容身份不一致使用结构化可恢复门禁；缺收据、覆盖不完整和逐来源陈旧继续沿既有诊断，历史结果查询行为不变。

## SOL-004 迁移合同、场景和消费者证据

- 状态: confirmed
- 解决: GAP-001, GAP-002, GAP-003
- 满足: REQ-001, AC-001, AC-002, AC-003, AC-004, AC-005, CON-001
- 依赖: SOL-001, SOL-002, SOL-003

更新 Task Table Manager 正式说明、CLI 帮助和测试辅助输入；验证语义输入、旧 envelope、旧内联快照、task/state CAS、有效收据、三类失效收据零写入、写后资产丢失诊断、部分写恢复、machine 读取以及 Delivery Workflow 摘要。完成后继续按 REQ-012 审计其他模型交互面，不执行 Codex 发布。
