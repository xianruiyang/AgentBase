# taskctl 辅助合同

工具入口：

```text
python <SkillDir>/scripts/taskctl.py <command> --task-dir <AbsoluteTaskDir>
```

## 查询与存储

```text
init        建立固定 tasks/state/results 目录和 task-table.json
draft       输出最小候选任务 JSON，不写文件
add/update  保存模型已编写的任务合同
show/list   有界返回任务、状态、结果和局部诊断
deps/dependents/impact  查询任务图，不裁决依赖是否成立
next/context  生成选择建议和有界执行上下文
completion-context  从当前 Markdown 分页返回 REQ/AC/UDES、CON、全部 DCR 与候选证据
status/render  生成可重建的执行摘要和 TASK_TABLE.md
```

查询默认使用有界紧凑 JSON，需要时使用 `--pretty`。当任务很少或 CLI 不可用时，可直接维护并读取合同文档；CLI 不是开始、推进、完成或重开任务的许可者。

`task-table.json` 的 `tasks/`、`state/`、`results/`、`.work-cache/index.json` 和 `TASK_TABLE.md` 路径固定，只为防止生成物覆盖语义真源或结果记录。

## 状态与结果命令

```text
claim       记录领取意图
start       记录开始实际工作
note        写入有界进度、状态、阻塞原因或下一动作
complete    保存结果记录并标记 done
reopen      记录完成结论或合同已失效
release     清除领取意图并回到 todo
```

写命令返回新 revision。`add` 创建新记录，不需要预期 revision；`update` 必须传调用方刚读到的 `--expected-task-revision`，所有状态写命令必须传调用方刚读到的 `--expected-state-revision`。缺少预期 revision 或与当前值不匹配都用 `TASK-REVISION` 阻断，因为 CLI 无法证明不会覆盖并发写入。owner 不一致、已 done、从非典型状态 complete/reopen/release，以及阻塞原因与状态不一致都返回诊断，由模型根据文档和真实工作判断。

`retired` 表示任务不再属于当前执行投影，应在 note 中记录原因及替代任务或上游决策 ID。这不删除历史。

内置状态、依赖类型、来源 ID 格式、reasoning hint、项目相对 mutation scope 和去重列表是推荐合同。只要 JSON 结构仍可解释，空白、缺失或非标准的语义文本会以空值或原值保存并返回诊断，不借助 CLI 把文档语义强制改写成内置枚举。只有任务 ID、revision、`result_ref` 等 CLI 实际用于定位记录、并发比较或解引用存储的字段必须满足机械门禁。

结果 JSON 在原有 `outcome/outputs/changed_files/verification/unresolved/invalidated_source_ids` 外可包含：

- `evidence_for`：本结果声称支持的 `REQ/AC/UDES/DES/SOL` 等上游 ID。
- `evidence_refs`：可直接查看的测试、日志、文件、页面或其他证据引用；至少包含 `ref`，可附 `kind` 和 `note`。
- `source_snapshot`：生成结果时所依赖上游 ID 到指纹的映射。与当前索引不一致时标记陈旧，不将结果伪装成损坏数据。

`completion-context` 同时使用任务合同的 `source_ids` 和结果的 `evidence_for` 建立候选映射；后者可直接把验收证据关联到 `REQ/AC/UDES`。若未显式提供 `source_snapshot`，`complete` 会对这两类当前可唯一定位的来源一起记录指纹。

`completion-context` 的 `deferred_changes` 流对当前 Markdown 中全部 `DCR` 分页，并返回每项的原始 `status`。它不根据内置状态集判断哪些条目会阻断完成；该结论由模型按交付文档、用户确认和证据裁决。

`completion-context` 返回的目标、约束和 DCR 条目以 `workflow.json.documents` 中的完整工作区相对路径标识 `document`，不把不同目录中的同名阶段文档压缩成相同文件名。

`completion-context` 续页必须传首页 `snapshot_id`，一次只选择一个结果流，并原样传回该流上一页返回的 `target_next_after_id`、`constraint_next_after_id`、`deferred_next_after_id` 或 `candidate_next_after_id`。游标必须精确标识同一快照中该流的一项；未知游标无法机械确定续点，工具拒绝该次续页并要求使用已返回游标或从首页重审，不得按字符串大小猜测位置而漏掉复核项。

首页无法从当前 Markdown 重建索引时仍返回局部诊断，供模型直接检查文档；携带 `snapshot_id` 的续页若遇到同一故障，则无法机械确认仍属于首页快照，使用 `TASK-INPUT-UNREADABLE` 只阻断该次续页。修复报告的输入后必须丢弃旧游标和快照，从首页重新取得复核上下文。

## 局部门禁

`taskctl` 只能用下列类型阻断当前命令：

- `TASK-PATH` / `TASK-OVERWRITE`：路径越界、生成视图覆盖真源，或破坏性覆盖已有记录。
- `TASK-LOCK` / `TASK-REVISION`：工作区并发写入，或已有记录写入缺少调用方已读 revision、期望 revision 已过期。
- `TASK-LIMIT` / `TASK-INPUT-UNREADABLE`：当前命令无法有界读取，JSON/schema/必需字段的类型与身份使当前对象无法确定解释，最终复核续页游标无法标识当前快照中的续点，或续页时无法重建当前 Markdown 以核对快照身份；不得用它阻断仍可保留并诊断的非标准语义值。批量查询中单个损坏记录应被隔离并诊断，不阻断其他记录。
- `TASK-AMBIGUOUS-TARGET`：精确写入或查询需要唯一 ID，但当前匹配不唯一。
- `TASK-PAGINATION-SNAPSHOT`：`completion-context` 续页会混用两个任务/文档快照。

门禁错误必须返回 `gate.id`、`gate.risk`、`gate.scope`、`gate.recovery` 和 `gate.retryable`。依赖环、owner、状态流转、可解析的非标准枚举/ID/描述性路径、重复值、快照/缓存漂移、上游未决、覆盖度和结果来源时效性均是诊断。

`list`、`next`、`deps` 和 `dependents` 的普通分页是建议性查询；游标失效时提示从首页重读即可。`completion-context` 的分页则属于一次完成证据复核，续页必须传回 `snapshot_id`；只有这一处因快照变化阻断并要求重审。
