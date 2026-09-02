# workctl 辅助合同

工具入口：

```text
workctl <command> --work-dir <AbsoluteWorkDir>
```

## 输出面

- `--view model` 是默认值，面向直接进入 Codex 上下文的结果；使用分行的紧凑 HJSON 风格文本，只保留当前阶段判断、动作、影响或恢复需要的字段，并省略成功 envelope、空集合、默认零值和正常机器身份。该视图服务模型阅读，不承诺机器解析；程序必须使用 machine 视图。
- model 与 machine stdout/stderr 均由 CLI 固定为 UTF-8，不依赖 Windows 当前控制台代码页。
- `--view machine` 只面向程序、测试和完整字段检查，保持既有紧凑 JSON 合同；需要缩进 JSON 时同时使用 `--pretty`。`--pretty` 不适用于 model 视图。模型预算不足时应按返回的文档与行号缩小查询或提高 `--model-token-budget`，不得切换 machine 视图。
- 两种视图来自同一次工作区索引或命令事实计算；renderer 不重新裁决需求、状态、关系、目标保护或完成语义。模型预算由 `--model-token-budget` 控制并在选择 section 前生效；machine `context` 的既有 `--budget` 仍表示 JSON 字符预算。
- 依赖原默认 JSON 的调用方迁移为显式 `--view machine`；没有已证实消费者时不增加永久兼容分支。

## 常用命令

```text
init      创建阶段文档、任务目录和最小 manifest
protect   记录 requirements 与 user-design 的用户确认快照元数据
outline   返回某阶段的条目类型、当前 manifest 文档路径和建议字段
index     从当前 Markdown 重建 .work-cache/index.json
status    摘要报告语义条目和可读取的任务状态
coverage  报告各类 ID、未决项和引用分布
context   model 按 Token 预算、machine 按字符预算返回某个 ID 及邻接条目
impact    递归返回显式引用指定 ID 的下游条目及首条依赖路径
render    生成 WORK_STATUS.md 只读视图
```

这些命令都是可选辅助；文件量小或 CLI 不可用时可直接读写阶段 Markdown 真源。`outline` 从当前 `workflow.json` 返回阶段实际登记的文档路径，不用内置模板文件名替代项目正式位置。索引及查询结果中每个条目的 `document` 同样保留该完整工作区相对路径，不退化为文件名；不同目录中的同名文档仍可唯一定位。默认输出为有界 model 视图，程序解析时显式使用 machine 视图。`context` 的 model 视图按语义 section 选择当前 ID、直接关系和必要正文，预算不足时保留目标身份、位置和精确恢复；machine 视图继续使用既有 `--budget` 字符预算，仍需更多内容时按返回 ID 精确读取。

`protect` 的 model 回执只保留当前保护 status、cycle、确认来源、保护 ID 数和当前目标数，详细诊断只返回一次；确认引用、完整快照结构与历史只在永久资产或 machine 视图中出现。`status` 的 baseline 异常使用 canonical `status` 字段并在顶层诊断中给出细节；`coverage` 没有独立诊断列表，因此在 baseline 节点保留同一细节。`render` 的 model 回执复用 status 的稀疏 semantic/task 摘要并附加输出路径，正常 `tasks.status=available` 省略，非正常状态保留。`impact` 只在 affected 列表被 `--max-items` 截断时额外返回总数和截断标志。

`render` 只重建 `WORK_STATUS.md`；摘要只展开实际非零状态、进展和问题，没有任务、结果或未决 ID 时用一句明确结论区分已读取的空集合与未知，partial/unavailable 仍显式保留。模型不得直接编辑该视图来改变阶段或任务状态。语义修改进入对应 Markdown 条目，结构化 manifest、快照和缓存只通过本合同定义的入口维护。

`workflow.json` 中 `protected-baseline.json`、`.work-cache/index.json`、`WORK_STATUS.md` 和 `task-table.json` 的管理路径固定；阶段文档路径可按项目正式位置配置。固定管理路径只防止缓存或视图覆盖语义真源、任务合同或结果。

## 快照、索引与诊断

- `init` 只创建 manifest、阶段模板和空任务目录，不填写语义结论。
- `protect` 记录确认者、确认引用、文档指纹和当时 ID；它不能自行证明用户已确认、目标足够或内容正确。确认者或引用缺失、空白或不是 `user` 时仍保存快照并返回诊断，由模型回到文档及真实对话来源裁决。开始新执行周期时使用 `--new-cycle`，旧快照保留在 `history`。
- 快照缺失、确认条目状态不一致、没有最终目标、ID 变化或文档漂移都只返回诊断。查询和索引仍以当前 Markdown 为准，由模型对照用户确认来源决定当前执行周期。
- 索引及其内存查询把同一版 `workflow.json` 的文档映射、确认快照诊断与当前 Markdown 条目组合为一次读取，并在索引中记录 manifest 指纹；若 manifest 或阶段文档在取样、构建或缓存写入期间变化，返回 `WORK-SNAPSHOT-RACE` 并重试，不得把不同 manifest 或文档版本写进同一查询快照。
- `index` 检查 ID、阶段归属、重复和引用；`coverage` 只统计显式关系；`impact` 只遍历已经写入关系字段的图并返回潜在受影响对象及首条路径。模型仍须从实际系统补齐未登记消费者、派生产物和旧关系，三者均不判断语义成立。
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
