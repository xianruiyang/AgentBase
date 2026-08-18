# Task 合同 authoring 交互面设计

## DES-001 taskctl add/update 是唯一 authoring owner

- 状态: confirmed
- 关联: REQ-001, UDES-001

`taskctl add/update` 唯一把模型任务正文规范化为永久 `task.record`。`id` 继续由模型合同持有；`schema` 和 `revision` 由入口按新增或 CAS 更新生命周期注入。

## DES-002 语义输入和永久读取分离验证

- 状态: confirmed
- 关联: AC-001, AC-002, AC-004, DES-001

永久记录继续使用完整验证器。authoring 输入若是无 schema 的对象，只允许语义字段并由入口构建 envelope；若是完整 `task.record`，按上一版兼容校验。只出现部分机器字段时拒绝，避免无声明混合合同。

## DES-003 draft model 投影移除机器字段

- 状态: confirmed
- 关联: AC-003, DES-001

`draft` handler 继续产生同一完整 canonical 任务；model renderer 在识别顶层 `task.record` 时只移除 schema/revision，machine renderer 不变。renderer 不重新计算任务语义。

## DES-004 revision 生命周期保持机械且原子

- 状态: confirmed
- 关联: AC-001, AC-002, DES-001

语义 add 固定从 revision 1 开始；语义或旧式 update 均先比较当前 revision，再写入 `current + 1`。旧式 add 的非初始 revision 继续按上一版诊断兼容，部分写恢复仍比较完整 canonical 记录。
