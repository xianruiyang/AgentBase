# workctl 使用合同

工具入口：

```text
python <SkillDir>/scripts/workctl.py <command> --work-dir <AbsoluteWorkDir>
```

## 常用命令

```text
init      创建阶段文档、任务目录和最小 manifest
protect   在用户确认后固化 requirements 与 user-design 基线
outline   返回某阶段的条目类型、文件和建议字段
index     重建 .work-cache/index.json，并摘要报告引用诊断
status    摘要报告语义条目和任务状态
coverage  报告各类 ID、未决项和引用分布
context   在字符预算内返回某个 ID 及邻接条目
impact    返回引用指定 ID 的下游条目
render    生成 WORK_STATUS.md 只读视图
```

默认输出为紧凑 JSON，并限制诊断和条目数量；需要人工阅读时使用 `--pretty`。`context` 必须设置足以覆盖当前工作的 `--budget`，仍需更多内容时按返回的 ID 精确读取，而不是扩大到整个工作区。

`outline --stage` 使用公开阶段名：`requirements`、`user-design`、`design`、`current-state`、`solution`、`deferred-changes`。它和其他命令一样显式接收绝对 `--work-dir`，返回对应阶段文件名，但不会读取或修改阶段正文。

`workflow.json` 中 `protected-baseline.json`、`.work-cache/index.json`、`WORK_STATUS.md` 和 `task-table.json` 的管理路径固定；阶段文档路径可以在固化前按项目正式位置配置。固定管理路径防止缓存或视图被重定向覆盖语义真源、任务合同或结果。

## 工具边界

- `init` 只创建 manifest、阶段模板和空任务目录，不填写真正需求、设计、现状或方案。返回的 `created` 是本次实际产生的路径，`pending` 是后续由 `protect/index/render` 或 `taskctl render` 才会生成的路径。
- `protect` 只在用户已经明确确认需求与用户设计后运行；它在工作区互斥锁内取得一致内容、状态和 ID 快照，并以排他创建方式写入不可覆盖的 `protected-baseline.json`。基线必须至少含一个 `REQ/AC/UDES` 目标。基线创建后，索引发现这两个文件漂移会作为完整性错误停止，模型应恢复原文并登记 `DCR`。
- `index` 检查 ID、阶段归属、重复和引用是否可解析；不判断正文含义是否正确。
- `coverage` 的“已引用”只表示存在显式 ID 关系，不表示语义覆盖成立。
- `impact` 返回潜在受影响对象，是否需要修改由模型判断。
- `render` 输出可重建视图，不得作为状态或语义真源。
- `status` 与 `render` 中的任务摘要调用 `$task-table-manager` 的严格存储摘要，任务、状态或当前结果身份不一致时明确报错，不在 workctl 维护第二套弱解析。
- 除路径越界、输入损坏和覆盖现有工作区外，诊断不阻断模型继续分析。重复身份仍会由 `index` 定位，但依赖唯一身份的 `protect/context/impact` 会拒绝含糊对象。

`$task-table-manager` 的 `taskctl context` 会读取 `.work-cache/index.json` 中的上游条目和基线状态。可修订阶段文档变更后先运行 `workctl index`，即可让任务上下文消费当前内容；缓存缺失只会减少上下文并返回提示，不会改变任务状态。
