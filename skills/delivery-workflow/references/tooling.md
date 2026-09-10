# workctl 辅助合同

工具入口：

```text
workctl <command> --work-dir <AbsoluteWorkDir>
```

## 输出面

- `--view model` 默认面向 Codex 上下文，以分行紧凑 HJSON 风格只保留当前判断、动作、影响或恢复字段，省略成功 envelope、空集合、默认零值和正常机器身份；不承诺机器解析，程序必须用 machine 视图。
- model 与 machine stdout/stderr 均由 CLI 固定为 UTF-8，不依赖 Windows 当前控制台代码页。
- `--view machine` 只供程序、测试和完整字段检查，保持紧凑 JSON；缩进时加 `--pretty`，它不适用于 model。模型预算不足时按返回的文档与行号缩小查询或提高 `--model-token-budget`，不得切换 machine。
- 两种视图来自同一次工作区索引或命令事实计算；renderer 不重新裁决需求、状态、关系、目标保护或完成语义。模型预算由 `--model-token-budget` 控制并在选择 section 前生效；machine `context` 的既有 `--budget` 仍表示 JSON 字符预算。
- 依赖原默认 JSON 的调用方迁移为显式 `--view machine`；没有已证实消费者时不增加永久兼容分支。

## 常用命令

```text
init      创建阶段文档、task-table.json、固定任务目录和最小 manifest
protect   记录 requirements 与 user-design 的用户确认快照元数据
outline   返回某阶段的条目类型、当前 manifest 文档路径和建议字段
index     从当前 Markdown 重建 .work-cache/index.json
status    摘要报告语义条目和可读取的任务状态
coverage  报告各类 ID、未决项和引用分布
context   model 按 Token 预算、machine 按字符预算返回某个 ID 及邻接条目
impact    递归返回显式引用指定 ID 的下游条目及首条依赖路径
render    生成 WORK_STATUS.md 只读视图
```

命令均为可选辅助；文件少或 CLI 不可用时直接读写阶段 Markdown 真源。`outline` 从当前 `workflow.json` 返回阶段实际登记路径，不以模板文件名替代正式位置；索引和查询的 `document` 也保留完整工作区相对路径，确保不同目录的同名文档可定位。默认输出有界 model 视图；程序显式用 machine。`context` 的 model 视图按语义 section 选择当前 ID、直接关系和必要正文，预算不足仍保留目标身份、位置和精确恢复；machine 继续以 `--budget` 限制字符，更多内容按返回 ID 精确读取。

`init` 同时初始化 Delivery Workflow 和任务表，同一工作区不要再运行 `taskctl init`。随后按合同维护阶段文档，需要保护确认来源时运行 `protect`。`index` 只显式持久化缓存；`protect/status/coverage/context/impact/render` 从当前文档取得索引事实，不要求先运行 `index`。

`protect` 的 model 回执只保留当前保护 status、cycle、确认来源、保护 ID 数和当前目标数，详细诊断只返回一次；确认引用、完整快照结构与历史只在永久资产或 machine 视图中出现。`status` 的 baseline 异常使用 canonical `status` 字段并在顶层诊断中给出细节；`coverage` 没有独立诊断列表，因此在 baseline 节点保留同一细节。`render` 的 model 回执复用 status 的稀疏 semantic/task 摘要并附加输出路径，正常 `tasks.status=available` 省略，非正常状态保留。`impact` 只在 affected 列表被 `--max-items` 截断时额外返回总数和截断标志。

`render` 只重建 `WORK_STATUS.md`；摘要只展开实际非零状态、进展和问题，没有任务、结果或未决 ID 时用一句明确结论区分已读取的空集合与未知，partial/unavailable 仍显式保留。模型不得直接编辑该视图来改变阶段或任务状态。语义修改进入对应 Markdown 条目，结构化 manifest、快照和缓存只通过本合同定义的入口维护。

`workflow.json` 中 `protected-baseline.json`、`.work-cache/index.json`、`WORK_STATUS.md` 和 `task-table.json` 的管理路径固定；阶段文档路径可按项目正式位置配置。固定管理路径只防止缓存或视图覆盖语义真源、任务合同或结果。

## 快照、索引与诊断

- `init` 只创建 manifest、阶段模板、空任务表及固定任务目录，不填写语义结论。
- `protect` 记录确认者、确认引用、文档指纹和当时 ID；它不能自行证明用户已确认、目标足够或内容正确。确认者或引用缺失、空白或不是 `user` 时仍保存快照并返回诊断，由模型回到文档及真实对话来源裁决。开始新执行周期时使用 `--new-cycle`，旧快照保留在 `history`。
- 快照缺失、确认条目状态不一致、没有最终目标、ID 变化或文档漂移都只返回诊断。查询和索引仍以当前 Markdown 为准，由模型对照用户确认来源决定当前执行周期。
- 索引及内存查询一次读取同版 `workflow.json` 文档映射、确认快照诊断和当前 Markdown，并记录 manifest 指纹；若 manifest 或阶段文档在取样、构建或缓存写入时变化，返回 `WORK-SNAPSHOT-RACE` 并重试，不得将不同版本混入同一查询快照。
- `index` 检查 ID、阶段归属、重复和引用；`coverage` 只统计显式关系；`impact` 只遍历已经写入关系字段的图并返回潜在受影响对象及首条路径。模型仍须从实际系统补齐未登记消费者、派生产物和旧关系，三者均不判断语义成立。
- `status` 和 `render` 尽力读取 `$task-table-manager` 摘要；任务存储中某个记录无法读取时返回局部诊断，不让任务域故障阻断交付文档查询。
- 重复 ID 是诊断；只有 `context/impact` 确实需要一个唯一对象时，才就该次精确查询拒绝歧义输入。

## 允许的局部门禁

`workctl` 只能用下列类型阻断当前命令：

- `WORK-PATH` / `WORK-OVERWRITE`：路径越界、生成物覆盖真源，或初始化/快照覆盖已有数据。
- `WORK-LOCK` / `WORK-SNAPSHOT-RACE`：工作区正在写入，或快照取得期间来源发生变化。
- `WORK-LIMIT` / `WORK-INPUT-UNREADABLE`：当前命令无法有界、可确定地读写必需输入。
- `WORK-AMBIGUOUS-TARGET`：精确命令需要唯一 ID，但当前匹配不唯一。

门禁错误须返回 `gate.id`、`gate.risk`、`gate.scope`、`gate.recovery`、`gate.retryable`。清单外的缺失、空白、非标准值、漂移、状态、覆盖度或内容问题须保留可读结果并附诊断，不得伪装成通用输入错误。

`$task-table-manager` 的 `taskctl context` 可消费当前 Markdown 重建的上游索引。缓存缺失或陈旧时，工具尝试在内存中重建并返回诊断；不改写任务状态。
