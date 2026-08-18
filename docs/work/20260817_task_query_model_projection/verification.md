# Task 查询模型投影验证

## 当前结果

- 4 个新增定向场景通过：show envelope 去重、list 非零摘要、语义零保留、impact 默认与续页入口。
- 真实已闭环工作区复测：list 仅显示 `done:2` 与两项；deps/dependents/impact 完整列表不再重复 count/false；next 明确返回 `candidate_count:0`；impact 不再崩溃。
- 累计完整回归通过：Task Table Manager 92 项，Delivery Workflow 39 项。
- Python 语法检查、76-case 静态 skill 合同、独立 Routing 76、Policy 76、References 19 和部署 `Validate` 全部通过。

## 边界

show 仍保留完整任务与结果语义，因此在真实复杂结果上可能较长；这些正文是 show 当前动作本身的对象，不以追求统一压缩比例删除。完整来源映射仍只在 machine 视图展开。

分页空集、完整非空页、截断续页、`recommended:false` 和 `current_for_task_revision:false` 等相近非触发语义均保留；当前没有已知适用失败。
