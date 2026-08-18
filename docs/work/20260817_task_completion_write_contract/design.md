# Task completion 写入合同设计

## DES-001 completion 写入边界是唯一 owner

- 状态: confirmed
- 关联: REQ-001, UDES-001, UDES-002

`task-table-manager/taskctl complete` 唯一负责把模型语义结果、命令目标、调用方已读 task/state revision 和来源快照收据合成为永久结果与新状态。结果文件输入不再与永久机器记录共用同一外部合同；读取器仍只解释永久 `task.result`。

## DES-002 语义输入规范化为单一永久结果

- 状态: confirmed
- 关联: AC-001, AC-002, DES-001

新结果输入只解析 `outcome`、`outputs`、`changed_files`、`verification`、`unresolved`、`invalidated_source_ids`、`evidence_for`、`evidence_refs` 和可选 `metadata`。CLI 注入 `schema`、`task_id`、`task_revision` 与 `source_snapshot_ref`；永久 schema、读取和 machine 视图不变。

## DES-003 task revision 使用独立 CAS

- 状态: confirmed
- 关联: AC-001, AC-005, DES-001

`complete --expected-task-revision` 表示模型实际执行所依据的任务合同版本，并在工作区锁内与当前任务 revision 比较。它与 `--expected-state-revision` 分别保护合同输入和状态写入，不能互相替代。

## DES-004 收据引用在任何结果或状态写入前验证

- 状态: confirmed
- 关联: AC-003, AC-005, DES-001

显式引用必须通过固定快照目录、支持 schema、规范内容和 SHA-256 身份校验；失败使用 `TASK-INPUT-UNREADABLE` 阻断当前 completion，并引导重新捕获或恢复原资产。通过身份校验后，覆盖度和逐来源时效仍沿既有结果诊断处理。

## DES-005 上一版输入只作入口兼容

- 状态: confirmed
- 关联: AC-004, DES-002

完整 `task.result` 输入作为已发布上一版的真实兼容对象继续接受，先校验其身份和 revision 与命令 CAS 一致，再规范化为同一永久结果并返回迁移诊断。历史永久结果继续由读取合同解释；兼容不会形成第二种永久 schema 或第二写入入口。
