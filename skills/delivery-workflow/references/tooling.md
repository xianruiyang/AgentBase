# workctl 辅助合同

工具入口：

```text
python <SkillDir>/scripts/workctl.py <command> --work-dir <AbsoluteWorkDir>
```

## 常用命令

```text
init      创建阶段文档、任务目录和最小 manifest
protect   记录 requirements 与 user-design 的用户确认快照元数据
outline   返回某阶段的条目类型、文件和建议字段
index     从当前 Markdown 重建 .work-cache/index.json
status    摘要报告语义条目和可读取的任务状态
coverage  报告各类 ID、未决项和引用分布
context   在字符预算内返回某个 ID 及邻接条目
impact    返回引用指定 ID 的下游条目
render    生成 WORK_STATUS.md 只读视图
```

这些命令都是可选辅助；文件量小或 CLI 不可用时可直接读写阶段文档。默认输出为有界紧凑 JSON，人工阅读时使用 `--pretty`。`context` 必须设置合理 `--budget`，仍需更多内容时按返回 ID 精确读取。

`workflow.json` 中 `protected-baseline.json`、`.work-cache/index.json`、`WORK_STATUS.md` 和 `task-table.json` 的管理路径固定；阶段文档路径可按项目正式位置配置。固定管理路径只防止缓存或视图覆盖语义真源、任务合同或结果。

## 快照、索引与诊断

- `init` 只创建 manifest、阶段模板和空任务目录，不填写语义结论。
- `protect` 记录确认者、确认引用、文档指纹和当时 ID；它不能自行证明用户已确认、目标足够或内容正确。确认者或引用缺失、空白或不是 `user` 时仍保存快照并返回诊断，由模型回到文档及真实对话来源裁决。开始新执行周期时使用 `--new-cycle`，旧快照保留在 `history`。
- 快照缺失、确认条目状态不一致、没有最终目标、ID 变化或文档漂移都只返回诊断。查询和索引仍以当前 Markdown 为准，由模型对照用户确认来源决定当前执行周期。
- `index` 检查 ID、阶段归属、重复和引用；`coverage` 只统计显式关系；`impact` 只返回潜在受影响对象。它们均不判断语义成立。
- `status` 和 `render` 尽力读取 `$task-table-manager` 摘要；任务存储中某个记录无法读取时返回局部诊断，不让任务域故障阻断交付文档查询。
- 重复 ID 是诊断；只有 `context/impact` 确实需要一个唯一对象时，才就该次精确查询拒绝歧义输入。

## 允许的局部门禁

`workctl` 只能用下列类型阻断当前命令：

- `WORK-PATH` / `WORK-OVERWRITE`：路径越界、生成物覆盖真源，或初始化/快照覆盖已有数据。
- `WORK-LOCK` / `WORK-SNAPSHOT-RACE`：工作区正在写入，或快照取得期间来源发生变化。
- `WORK-LIMIT` / `WORK-INPUT-UNREADABLE`：当前命令无法有界、可确定地读写必需输入。
- `WORK-AMBIGUOUS-TARGET`：精确命令需要唯一 ID，但当前匹配不唯一。

门禁错误必须返回 `gate.id`、`gate.risk`、`gate.scope`、`gate.recovery` 和 `gate.retryable`。不在此清单内的缺失、空白、非标准值、漂移、状态、覆盖度或内容问题必须保存为可读结果并附诊断，不得伪装成通用输入错误。

`$task-table-manager` 的 `taskctl context` 可消费当前 Markdown 重建的上游索引。缓存缺失或陈旧时，工具尝试在内存中重建并返回诊断；不改写任务状态。
