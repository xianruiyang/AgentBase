# taskctl 任务合同写入

本文件只用于 `init/draft/add/update`。任务字段、依赖语义和模型 authoring 边界同时继承 [task-contracts.md](task-contracts.md)。

## 命令职责

```text
init        建立固定 tasks/state/results/snapshots 目录和 task-table.json
draft       输出最小候选任务，不写文件
add/update  从含稳定 ID 的模型语义正文生成完整永久任务合同
```

`draft` 的 model 视图保留稳定任务 ID 与非空语义字段，省略 schema/revision；显式 machine draft 返回完整 canonical `task.record`，供程序和永久格式检查。CLI 不自动把文档变成任务。

`add/update --file` 的模型输入包含任务 `id` 和语义字段，不包含 schema/revision。`add` 注入初始 revision；`update` 必须传调用方刚读到的 `--expected-task-revision` 并注入下一 revision。上一版完整 task envelope 仍由相同入口单向规范化并返回兼容诊断，不能要求模型长期同步机器字段。

`add/update` 在任务合同与初始状态提交后、释放同一工作区锁前自动刷新 `TASK_TABLE.md`。machine 回执的 `table_view.status` 区分 `refreshed/stale`；刷新失败不回滚真源，返回 `task_table_refresh_failed` 与显式 `render` 恢复动作。

写命令的 model 回执只返回目标、写后 revision、有效异常和必要恢复；空诊断、空警告、零计数和 `recovered_partial_write:false` 省略，恢复确实发生时保留 true，问题被上限截断时才返回总数。完整写入回执由 `--view machine` 提供。

永久 `tasks/`、`state/`、`results/` 和 `snapshots/` 路径固定；CLI 可用时不直接编辑 `tasks/*.json`、生成视图或其他机器资产绕过路径、原子写入和 CAS 职责。

## 门禁与诊断

- `TASK-PATH` / `TASK-OVERWRITE`：路径越界、生成物覆盖语义真源或破坏性覆盖已有记录。
- `TASK-LOCK` / `TASK-REVISION`：工作区并发写入、已有记录写入缺少调用方已读 revision 或 revision 冲突。
- `TASK-LIMIT` / `TASK-INPUT-UNREADABLE`：输入无法有界读取，或 JSON/schema/必需身份使目标无法确定解释。
- `TASK-AMBIGUOUS-TARGET`：精确写入需要唯一 ID，但当前匹配不唯一。

owner、依赖环、状态、来源 ID、任务粒度、mutation scope、上游未决和验证字段都只诊断，不阻断仍可确定对象的写入。
