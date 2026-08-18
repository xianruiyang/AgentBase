# workctl 模型回执投影验证

## 当前结果

- 4 个新增定向场景通过：protect 回执、baseline status/诊断分层、render 稀疏摘要、impact 完整列表去重。
- 真实已闭环工作区证明 impact 截断时总数 31 仍是必要恢复证据。
- 累计完整回归通过：Delivery Workflow 39 项，Task Table Manager 92 项。
- Python 语法检查、76-case 静态 skill 合同、独立 Routing 76、Policy 76、References 19 和部署 `Validate` 全部通过。

## 必须覆盖

- drifted/invalid baseline 在 model 中使用 `status`，不再出现 `aligned`。
- status 不复制 baseline diagnostics；coverage 仍能看到 baseline 问题。
- protect model 不暴露完整快照，永久快照仍完整。
- render model 不展开 prefix 机器统计或正常 available 状态，machine 仍完整。
- impact 未截断时不重复 count，截断时保留总数和恢复标志。

完整列表、截断列表、正常 baseline、异常 baseline、无任务和 partial 场景均有直接覆盖；当前没有已知适用失败。
