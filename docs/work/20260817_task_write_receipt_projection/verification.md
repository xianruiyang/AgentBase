# Task 写入回执投影验证

## 当前结果

- 4 个新增定向场景通过：合同写回执、状态写回执、completion 截断诊断、render 稀疏摘要。
- 累计完整回归通过：Task Table Manager 92 项，Delivery Workflow 39 项。
- Python 语法检查和 76-case 静态 skill 合同通过；独立 Routing 76、Policy 76、References 19 全部通过。
- 正式部署入口 `Validate` 返回 `valid: true`；没有执行 Codex `Publish`。

## 必须覆盖

- model 正常回执不含状态 schema、重复 task ID、零计数或 false 恢复标志。
- machine 输出和永久 `task.record/task.state` 仍保留完整字段。
- 非空警告/诊断仍可见，只有条目截断时保留额外总数。
- `complete` 结果引用只在 model 顶层出现一次。
- `render` 保留输出路径、任务总数和非零摘要。

以上同时覆盖正常回执、非空诊断、截断诊断和显式 machine 对照；当前没有已知适用失败。
