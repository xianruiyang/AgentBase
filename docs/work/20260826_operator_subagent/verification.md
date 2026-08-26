# 第三语义执行子代理验证

## 当前候选证据

- `subagent-orchestration` skill 结构检查通过。
- portable-agent 合同接受 `evidence`、`experiment`、`operator` 三个独立角色，并继续拒绝身份、模型、档位、额外字段、敏感内容和重复语义反例。
- 路由用例与 managed lifecycle JSON 可解析，`global/AGENTS.md` 和 skill 主文件仍在项目字节预算内。
- 首次路由合同检查只发现本子计划的 `verification.md`、`completion-audit.md` 尚未建立；这两个正式链接现已补齐，完整结果以候选稳定后的集中复核为准。
- 首次正式 References 尝试发现既有 `dimension-bounded-validation-plan` 同时允许“直接维护任务语义”和“调用 taskctl update”两种引用路径：结果按后者选了 `tooling.md`/`authoring-tooling.md`，却被只允许前者的旧 oracle 拒绝。按当前 skill 真源把案例输入明确为 taskctl update，并移除只在阶段推进、新证据影响或证据回流时适用的 `iteration.md`；这属于可判别输入与 oracle 修正，不以相同输入重采样。
- 新输入的 Routing 通过；Policy 结果只漏了三个与各案例核心判断非必然绑定的附加标签：可脚本化批处理不必须同时宣告局部快速路径，已满足稳定前提的构建不必重复宣告候选时点，维度合同也不重复承担已有专门案例覆盖的纵向闭环。删除这三项隐藏 oracle 过约束，不改变模型可见输入，并由正式 evidence 入口重验已有结果。
- 当前 References 随后只漏选 Delivery 的 `execution-contracts.md`。该引用确实唯一维护任务投影语义，不能因同时选择 `task-table-manager` 而省略；根因是 Delivery 主文件的“只增加一项”表述没有说明一次动作横跨方案与任务时应同时加载两类引用。现已明确单阶段渐进读取与跨方案/任务组合读取的边界，属于候选规则修正，不以旧输入重跑。
- 相邻 `delivery-task-contract` 反例又证明“跨方案与任务”仍会把仅消费已确认方案的任务投影误判为双重修改。规则进一步收敛为：按实际修改类型选择；只有同次修改方案语义和任务/结果合同才双读，单向消费已确认方案只读 execution。该反例推翻上一版宽条件，旧 References 结果不再复用。

## 发布前待验收

- 全局规则、skill 内容/引用/触发边界与三角色配置一致。
- 新增路由案例形成当前 Routing、Policy、References evidence，无相同输入盲目重采样。
- 部署 Validate 覆盖新资产安装、回滚和生命周期，Windows SWE evaluator 保持禁用。
- 正式 Publish 后同范围 Status 为 published，实际安装中三个配置与源码指纹一致。

规则文件和路由 evidence 只能证明候选结构与选择合同，不证明新任务中的真实模型行为；后者出现反例时按完成审计中的重开条件处理。
