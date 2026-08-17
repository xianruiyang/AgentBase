# 交付产物公共合同

本文件只定义各阶段共同使用的工作区、语义真源、稳定 ID 和条目格式。阶段专有语义由 `SKILL.md` 指向的目标、规划或执行合同唯一维护；单阶段动作不预读其他阶段合同。

## 工作区与真源

```text
<work-dir>/
├── workflow.json
├── protected-baseline.json
├── requirements.md
├── user-design.md
├── design.md
├── current-state.md
├── solution.md
├── deferred-changes.md
├── task-table.json
├── tasks/
├── state/
├── results/
├── TASK_TABLE.md
└── .work-cache/index.json
```

`requirements.md` 和 `user-design.md` 持有当前执行周期内由用户确认的目标；`design.md`、`current-state.md` 和 `solution.md` 持有模型可修订的语义。任务与结果只引用这些文档中的稳定 ID。`workflow.json` 只登记位置；快照、缓存和生成视图不定义目标、执行许可或完成状态。

## 模型读取面与修改面

阶段 Markdown 是模型与用户直接读取、由模型按稳定 ID 局部维护的语义真源。每个条目只承担所属阶段职责，修改时把新信息合入正确条目并删除已失效或重复的表述；逐轮对话、原始日志、派生计数和可从其他真源重建的摘要不写入阶段文档。需要更多上下游时按 ID 和实际关系渐进读取，不因工作区存在而全量装入。

`workflow.json` 只维护文档位置，`protected-baseline.json` 只维护确认来源元数据，任务 JSON 由任务合同拥有；它们的完整机器结构不自动成为模型读取面。`.work-cache/index.json`、`WORK_STATUS.md` 和 `TASK_TABLE.md` 是可重建产物，模型不得通过直接编辑它们改变目标、设计、任务或完成状态。程序需要的索引和视图从当前 Markdown 与结构化任务真源生成，不维护反向同步的第二语义源。

## 稳定 ID

| 前缀 | 所属产物 | 含义 |
| --- | --- | --- |
| `REQ-` | requirements | 用户可观察结果 |
| `AC-` | requirements | 原子验收条件 |
| `CON-` | requirements | 约束或明确非目标 |
| `UDES-` | user-design | 用户明确给出的设计 |
| `DEC-` | 可修订阶段 | 仍需裁决或已经裁决的模型选择 |
| `DES-` | design | 模型形成的职责、接口、状态或依赖 |
| `OBS-` | current-state | 有证据边界的当前观察 |
| `GAP-` | current-state | 目标相对现状的差距 |
| `SOL-` | solution | 解决差距的动作与结果 |
| `DCR-` | deferred-changes | 对受保护目标的延后讨论项 |
| `T` | tasks | 可执行工作包 |

ID 创建后保持稳定。内容变化修改正文和状态；只有对象已不是同一个对象时才新建 ID。引用写出精确 ID，不用名称相似或隐含顺序代替关系。

索引只从项目符号形式的 `关联`、`关联需求`、`关联目标`、`满足`、`解决`、`依赖`、`后继证据`、`目标ID` 及其直接英文对应字段提取关系。标题、来源、正文、证据描述和代码示例中的 ID 形文本不进入语义图；需要参与影响查询的关系由下游条目显式引用上游。

## 通用条目

每个语义条目使用二级标题并在正文前声明必要元数据：

```markdown
## REQ-001 用户可以导出当前结果

- 状态: confirmed
- 来源: 用户请求
- 关联: AC-001, CON-002

正文只写本条职责内的内容。
```

可修订条目推荐使用 `confirmed`、`proposed`、`open`、`unknown` 或 `superseded`。`open` 与 `unknown` 保持可见，但不会因工具检查自动阻断其他条目。当前周期经用户确认的条目使用 `confirmed`；需要改变受保护目标时建立 `DCR`，不直接标为 `superseded`。CLI 只报告状态诊断。
