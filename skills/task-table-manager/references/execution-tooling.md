# taskctl 执行状态、结果与来源

本文件用于 `context`、`claim/start/note/complete/reopen/release`。执行、恢复和并行领取同时继承 [execution.md](execution.md)。

## 上下文与来源收据

`context` 从任务 `source_ids` 沿当前语义引用读取传递祖先。model 视图保留当前任务合同、状态、直接依赖、必要上游正文、异常、恢复信息和 `{ref,count,complete}` 来源收据，不输出完整指纹映射；无 `--capture` 时只提示捕获入口。

`context --capture` 在最终模型 Token 预算确定实际返回正文后保存完整 ID—指纹映射。预算移除正文时同步移除快照成员并标记不完整；输出截断或来源无法唯一定位时先补齐输入并重新捕获，或明确限定结果边界。machine 视图返回完整映射。

## 状态命令

```text
claim       记录领取意图
start       记录开始实际工作
note        写入有界进度、状态、阻塞原因或下一动作
complete    保存结果记录并标记 done
reopen      记录完成结论或合同已失效
release     清除领取意图并回到 todo
```

所有状态写命令必须传调用方刚读到的 `--expected-state-revision`。命令记录模型已经作出的判断，不决定该判断是否被允许。`retired` 表示任务不再属于当前执行投影，应在 note 中记录原因和替代任务或上游决策 ID；它不删除历史。

`state/<ID>.json` 的 `started_at` 与 `ended_at` 由 CLI 以 UTC RFC3339 秒级时间维护，模型不提供时间参数：显式 `start` 或状态首次进入 `in_progress` 时填充尚为空的 `started_at`；状态进入 `done/retired` 时填充 `ended_at`；离开终态时清空 `ended_at`，但保留同一任务第一次实际开始时间。旧状态缺少字段时按 `null` 读取，不推测历史时间，只在后续真实转换中写入。时间与状态、revision、结果引用在同一锁和 CAS 边界内提交。

内置状态、依赖类型、来源 ID 格式、reasoning hint、项目相对 mutation scope 和去重列表是推荐合同。可解析的非标准语义值保留原值并返回诊断，不用 argparse 枚举把文档语义改写成工具许可。

状态写入的 model 回执返回顶层任务 ID、写后 revision 和去掉 schema、重复 task ID、空字段后的语义状态，已有起止时间保持可见；`complete` 另在顶层返回一次 `result_ref`。空诊断与正常默认值省略，完整回执由 machine 视图提供。

## 完成写入

模型通过 `--result-file` 只提交 `outcome/outputs/changed_files/verification/unresolved/invalidated_source_ids/evidence_for/evidence_refs/metadata` 等语义字段；空列表可省略。`schema/task_id/task_revision/source_snapshot/source_snapshot_ref` 由命令目标、CAS 和收据参数维护，不属于新模型输入。

- `evidence_for`：本结果声称支持的 `REQ/AC/UDES/DES/SOL` 等上游 ID。
- `evidence_refs`：可直接查看的测试、日志、文件、页面或其他证据引用；至少包含 `ref`，可附 `kind` 和 `note`。
- `source_snapshot_ref`：指向 `context --capture` 生成的内容寻址执行来源映射；模型通过 `complete` 参数传入。

`complete --expected-task-revision <REV> --source-snapshot-ref <REF>` 还必须携带当前 state revision。task/state 两项 CAS 分别证明没有把结果绑定到更新后的任务合同、没有覆盖更新后的执行状态；任一缺少或冲突都在创建结果或新状态前阻断。

显式收据在写入前必须存在、结构可读且内容身份一致；否则使用 `TASK-INPUT-UNREADABLE` 阻断且不改变结果或状态。未提供收据、覆盖不足和逐来源陈旧只诊断。历史结果后来出现资产异常仍只在读取时诊断并保留历史。

旧内联来源结果继续可读；上一版完整完成输入由同一入口单向规范化，旧映射内容寻址外部化并返回兼容诊断，新永久结果不得同时持有引用和映射。后继验证提交自己的收据、`evidence_for` 和直接证据，不改写旧结果。

## 门禁与诊断

- `TASK-PATH` / `TASK-OVERWRITE`：路径越界、错误目标或破坏性覆盖。
- `TASK-LOCK` / `TASK-REVISION`：工作区并发写入，或 task/state 的调用方已读 revision 缺失、过期。
- `TASK-LIMIT` / `TASK-INPUT-UNREADABLE`：输入无法有界解释，或显式 completion 收据不存在、不可读、身份不一致。
- `TASK-AMBIGUOUS-TARGET`：状态写入需要唯一 ID，但当前匹配不唯一。
- `TASK-SNAPSHOT-CONFLICT`：一次捕获或完成输入指定两个不同来源快照，无法证明实际使用版本。

owner 不一致、非典型状态流转、依赖未完成、上游未决、快照覆盖不足或陈旧、结果为空、验证不足和历史资产异常都只诊断。
