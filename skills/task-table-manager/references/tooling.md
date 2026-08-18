# taskctl 辅助合同

工具入口：

```text
python <SkillDir>/scripts/taskctl.py <command> --task-dir <AbsoluteTaskDir>
```

## 输出面

- `--view model` 是默认值，面向直接进入 Codex 上下文的结果；使用分行的紧凑 HJSON 风格文本，只保留缺失后会改变当前任务判断、动作、验证或恢复的字段，不输出正常成功 envelope、空集合、默认零值或重复机器身份。该视图服务模型阅读，不承诺机器解析；程序必须使用 machine 视图。
- model 与 machine stdout/stderr 均由 CLI 固定为 UTF-8，不依赖 Windows 当前控制台代码页。
- `--view machine` 面向程序、测试和完整字段检查，保持既有紧凑 JSON 合同；需要缩进 JSON 时同时使用 `--pretty`。`--pretty` 不适用于 model 视图。
- 两种视图消费同一个命令 handler 的权威结果；renderer 不重新计算任务状态、诊断、候选关系、分页或证据时效。模型预算由 `--model-token-budget` 控制，并在选择语义单元时生效；机器 `context/show/completion-context` 的既有 `--budget` 仍表示 JSON 字符预算。
- 若调用方此前依赖默认 JSON，迁移为显式 `--view machine`；没有已证实消费者时不保留第二个隐式默认入口。

## 查询与存储

```text
init        建立固定 tasks/state/results/snapshots 目录和 task-table.json
draft       输出最小候选任务，不写文件；model 省略 schema/revision，machine 返回完整 canonical
add/update  从含稳定 ID 的模型语义正文生成完整永久任务合同
show/list   有界返回任务、状态、结果和局部诊断
deps/dependents/impact  查询任务图；后继查询返回首条路径与该边消费内容
next/context  生成选择建议；context --capture 产生最终模型可见来源的持久收据
completion-context  从当前 Markdown 分页返回 REQ/AC/UDES、CON、全部 DCR 与候选证据
status/render  生成可重建的执行摘要和 TASK_TABLE.md
```

查询默认使用有界 model 视图；程序解析时显式使用 machine 视图。`draft` 的 model 视图保留稳定任务 ID 与非空语义字段，可作为模型 authoring 指引；显式 machine draft 保持完整 `task.record`，供程序和永久格式检查，不要求模型把其 schema/revision 复制回输入。当任务很少或 CLI 不可用时仍按正式合同继续；CLI 可用时，永久任务、状态和结果 JSON 通过带 revision 的写命令维护，不直接编辑生成视图或绕过存储职责。CLI 不是开始、推进、完成或重开任务的许可者。

`show` 的 model 视图以顶层 ID 标识对象，task/state/result 不重复 schema 或 task ID；task/state revision、结果 task revision、结果引用、语义正文、诊断与来源收据摘要仍保留。`list/deps/dependents/impact/next` 的完整非空页不重复列表长度、`truncated:false` 或零诊断计数；截断时返回总数和精确 `after_id`，`impact` 与 dependents 一样接受该续页参数。空页仍明确返回 matched/dependency/dependent/candidate 数，因为“没有候选或关系”是查询结论而不是默认成功值。

`status` 和 `render` 的结果摘要使用明确作用域：`referenced_result_count` 表示当前状态文件实际引用的结果数，`task_revision_stale_result_count` 只表示结果记录的任务 revision 与当前合同不一致，`source_snapshot_issue_result_count` 表示至少含一项收据缺失、资产异常、覆盖不完整或逐来源陈旧诊断的结果数；同时返回含诊断结果数、结果诊断条目数和按 kind 计数。上述字段互不替代，也不表示目标证据充分或整体完成。

`status` 的 model 视图只显示非零状态、异常、结果进展和实际诊断；正常空诊断、完整 protected baseline 及所有零计数只保留在 machine 视图。`context` 的 model 视图保留当前任务合同、状态、直接依赖、必要上游正文、异常、恢复信息和 `{ref,count,complete}` 来源收据，不输出完整指纹映射；无 `--capture` 时只提示捕获入口。快照成员从最终 Token 预算投影实际保留的上游生成，预算移除正文时同步移除成员并标记不完整。machine 视图继续返回完整映射。`completion-context` 的 model 视图保留目标、约束、DCR、候选结果摘要、诊断、证据引用、快照 ID 和精确游标，但省略完整来源映射。

写命令的 model 回执只确认后续动作需要的事实：`add/update` 返回目标和写后 revision；状态命令返回顶层任务 ID 与去掉 schema、重复 task ID 和空字段的写后语义状态；`complete` 另在顶层返回一次结果引用。空诊断、空警告、零计数和 `recovered_partial_write:false` 省略，恢复确实发生时保留 true，问题条目被输出上限截断时才额外返回总数。`render` 复用 `status` 的非零摘要并附加生成路径。完整写入回执仍由 `--view machine` 提供。

`task-table.json` 的 `tasks/`、`state/`、`results/`、`snapshots/`、`.work-cache/index.json` 和 `TASK_TABLE.md` 路径固定，只为防止生成物覆盖语义真源、结果或不可变来源证据。

`render` 生成的摘要只列实际非零状态、进展和问题；没有任务或没有结果引用时用一句明确结论区分已读取的空集合与未知。存在结果时即使带验证数为零也保留该缺口。任务明细固定保留全部列；没有可显示值的单元格使用 `—` 占位，避免长文本换行时产生列错位错觉。占位符只属于生成视图，不写回任务合同、状态或结果，也不表示模型已经裁决该字段语义为“无”。模型不得直接编辑 `TASK_TABLE.md` 改变任务；修改通过任务合同或状态命令进入唯一结构化真源，再重新生成视图。

## 状态与结果命令

```text
claim       记录领取意图
start       记录开始实际工作
note        写入有界进度、状态、阻塞原因或下一动作
complete    保存结果记录并标记 done
reopen      记录完成结论或合同已失效
release     清除领取意图并回到 todo
```

写命令返回新 revision。`add/update --file` 的新模型输入包含任务 `id` 和语义字段，不包含 schema/revision；`add` 注入初始 revision，`update` 必须传调用方刚读到的 `--expected-task-revision` 并注入下一 revision。上一版完整 task envelope 仍由相同入口规范化并返回兼容诊断。所有状态写命令必须传调用方刚读到的 `--expected-state-revision`。缺少预期 revision 或与当前值不匹配都用 `TASK-REVISION` 阻断，因为 CLI 无法证明不会覆盖并发写入。owner 不一致、已 done、从非典型状态 complete/reopen/release，以及阻塞原因与状态不一致都返回诊断，由模型根据文档和真实工作判断。

`complete` 除 state revision 外还必须传调用方执行时读取的 `--expected-task-revision`。两项 CAS 分别证明没有把结果绑定到更新后的任务合同、没有覆盖更新后的执行状态；任一缺少或冲突都在创建快照兼容资产、结果或新状态前阻断。

`retired` 表示任务不再属于当前执行投影，应在 note 中记录原因及替代任务或上游决策 ID。这不删除历史。

内置状态、依赖类型、来源 ID 格式、reasoning hint、项目相对 mutation scope 和去重列表是推荐合同。只要 JSON 结构仍可解释，空白、缺失或非标准的语义文本会以空值或原值保存并返回诊断，不借助 CLI 把文档语义强制改写成内置枚举。只有任务 ID、revision、`result_ref` 等 CLI 实际用于定位记录、并发比较或解引用存储的字段必须满足机械门禁。

模型通过 `--result-file` 提交的 JSON 只写 `outcome/outputs/changed_files/verification/unresolved/invalidated_source_ids/evidence_for/evidence_refs/metadata` 等语义字段；空列表可以省略。`schema/task_id/task_revision/source_snapshot/source_snapshot_ref` 由命令目标、CAS 和收据参数维护，不属于新模型输入。永久结果仍保持完整 `task.result` 机器合同，其中：

- `evidence_for`：本结果声称支持的 `REQ/AC/UDES/DES/SOL` 等上游 ID。
- `evidence_refs`：可直接查看的测试、日志、文件、页面或其他证据引用；至少包含 `ref`，可附 `kind` 和 `note`。
- `source_snapshot_ref`：指向 `context --capture` 生成的内容寻址执行来源映射；模型通过 `complete` 参数传入，工具附加到永久结果。

`context` 从任务 `source_ids` 沿当前语义引用读取传递祖先。`--capture` 在最终模型预算候选确定后保存实际返回正文对应的完整映射，并返回可传给 `complete` 的引用、成员数和完整性；若输出截断或来源无法唯一定位，模型先补齐输入并重新捕获，或明确限定结果边界。

`complete --expected-task-revision <REV> --source-snapshot-ref <REF>` 保存模型语义结果并附加已有收据；它先确认引用资产存在、结构可读且内容身份一致，再以当前索引比较覆盖不足和逐来源陈旧，不在完成时生成当前指纹冒充实际输入。前三项在新写入时属于无法兑现显式持久引用的机械失败，使用 `TASK-INPUT-UNREADABLE` 阻断且不改变结果或状态；未提供收据、覆盖不足和陈旧只诊断。历史结果后来出现同类资产异常仍只在读取时诊断。历史内联结果继续读取；上一版完整完成输入由该入口规范化，旧式内联快照内容寻址外部化并返回兼容诊断，新永久结果不得同时持有引用和映射。

每个 `completion-context` 响应页只在顶层 `candidate_tasks` 中返回一次完整候选任务证据。该对象以任务 ID 为键，值保留状态、合同修订、结果引用与摘要、产出、验证、未决项、失效来源、证据关联与引用、执行来源快照和结果诊断；值内不重复任务 ID。每个 `targets[]` 用有序 `candidate_task_ids` 引用本目标当前候选页，并继续返回该目标的候选总数、返回数、结果数、带验证结果数、截断状态和精确游标。顶层目录必须恰好覆盖当前页目标实际引用的任务，不得重复完整对象、产生悬空 ID，或在预算移除目标后保留无人引用任务。

`completion-context` 用 `query_diagnostics` 返回存储、索引、结果读取和当前语义目标定位的查询级诊断；`diagnostic_summary` 分别返回 `query_diagnostic_count`、当前候选目录的含诊断结果数、任务 revision 陈旧结果数、来源快照问题结果数、结果诊断条目数、按 kind 计数和两层总数。汇总只覆盖当前响应页最终保留的目标及其唯一候选目录，预算移除目标后同步重建；完整结果诊断不复制到汇总。只存在查询诊断或只存在候选结果诊断时，另一层明确为零，不用无作用域的 `diagnostic_count` 代表两者。

`completion-context` 的 `deferred_changes` 流对当前 Markdown 中全部 `DCR` 分页，并返回每项的原始 `status`。它不根据内置状态集判断哪些条目会阻断完成；该结论由模型按交付文档、用户确认和证据裁决。

`completion-context` 返回的目标、约束和 DCR 条目以 `workflow.json.documents` 中的完整工作区相对路径标识 `document`，不把不同目录中的同名阶段文档压缩成相同文件名。

`completion-context` 续页必须传首页 `snapshot_id`，一次只选择一个结果流，并原样传回该流上一页返回的 `target_next_after_id`、`constraint_next_after_id`、`deferred_next_after_id` 或 `candidate_next_after_id`。游标必须精确标识同一快照中该流的一项；未知游标无法机械确定续点，工具拒绝该次续页并要求使用已返回游标或从首页重审，不得按字符串大小猜测位置而漏掉复核项。

首页无法从当前 Markdown 重建索引时仍返回局部诊断，供模型直接检查文档；携带 `snapshot_id` 的续页若遇到同一故障，则无法机械确认仍属于首页快照，使用 `TASK-INPUT-UNREADABLE` 只阻断该次续页。修复报告的输入后必须丢弃旧游标和快照，从首页重新取得复核上下文。

## 局部门禁

`taskctl` 只能用下列类型阻断当前命令：

- `TASK-PATH` / `TASK-OVERWRITE`：路径越界、生成视图覆盖真源，或破坏性覆盖已有记录。
- `TASK-LOCK` / `TASK-REVISION`：工作区并发写入，或已有记录写入缺少调用方已读 revision、期望 revision 已过期。
- `TASK-LIMIT` / `TASK-INPUT-UNREADABLE`：当前命令无法有界读取，JSON/schema/必需字段的类型与身份使当前对象无法确定解释，显式 completion 收据无法解析为存在且身份一致的不可变资产，最终复核续页游标无法标识当前快照中的续点，或续页时无法重建当前 Markdown 以核对快照身份；不得用它阻断仍可保留并诊断的非标准语义值。批量查询和历史读取中的单个损坏记录应被隔离并诊断，不阻断其他记录。
- `TASK-AMBIGUOUS-TARGET`：精确写入或查询需要唯一 ID，但当前匹配不唯一。
- `TASK-SNAPSHOT-CONFLICT`：一次捕获或完成输入同时指定两个不同来源快照，工具无法证明实际使用版本；改用同一收据后重试。
- `TASK-PAGINATION-SNAPSHOT`：`completion-context` 续页会混用两个任务/文档快照。

门禁错误必须返回 `gate.id`、`gate.risk`、`gate.scope`、`gate.recovery` 和 `gate.retryable`。依赖环、owner、状态流转、可解析的非标准枚举/ID/描述性路径、重复值、快照/缓存漂移、上游未决、覆盖度和结果来源时效性均是诊断。

`list`、`next`、`deps` 和 `dependents` 的普通分页是建议性查询；游标失效时提示从首页重读即可。`completion-context` 的分页则属于一次完成证据复核，续页必须传回 `snapshot_id`；只有这一处因快照变化阻断并要求重审。
