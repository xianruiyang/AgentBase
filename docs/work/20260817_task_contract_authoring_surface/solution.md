# Task 合同 authoring 交互面方案

## SOL-001 建立任务语义输入规范化层

- 状态: confirmed
- 解决: GAP-001, GAP-002
- 满足: AC-001, AC-002, AC-004

从永久 `validate_task` 中复用语义正文规范化，新增 authoring 输入识别：新输入由入口注入 schema/revision，完整 envelope 走上一版兼容并返回诊断，部分机器字段拒绝。

## SOL-002 让 add/update 拥有 revision 生命周期

- 状态: confirmed
- 解决: GAP-001
- 满足: AC-001, AC-002
- 依赖: SOL-001

语义 add 固定 revision 1；update 先按 `--expected-task-revision` 比较当前记录，再生成下一 revision。部分写、owner 和任务语义诊断保持现有职责。

## SOL-003 稀疏化默认 draft 而保持 machine canonical

- 状态: confirmed
- 解决: GAP-001
- 满足: AC-003
- 依赖: SOL-001

model 投影从顶层 draft task.record 移除 schema/revision，保留 ID 与全部非空语义字段；显式 machine 继续返回完整 canonical JSON。

## SOL-004 闭合合同、兼容和消费者验证

- 状态: confirmed
- 解决: GAP-001, GAP-002
- 满足: REQ-001, AC-001, AC-002, AC-003, AC-004, CON-001
- 依赖: SOL-001, SOL-002, SOL-003

迁移正式 task contract/tooling/SKILL 说明和常规测试输入，新增语义 add/update、model/machine draft、完整 envelope 兼容、部分机器字段拒绝、revision/部分写回归，并重验 taskctl、workctl 和静态合同。
