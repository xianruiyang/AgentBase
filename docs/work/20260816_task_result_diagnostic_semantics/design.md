# 任务结果诊断与证据时效语义：目标设计

## DES-001 task-table-manager 拥有结果时效与查询投影

- 状态: confirmed
- 满足: REQ-001, REQ-002, REQ-003, AC-005, AC-006
- 关联: UDES-002

`task-table-manager` 的任务结果合同定义结果声明、证据映射和执行来源快照，tooling 合同定义 `completion-context`、`status` 与 `render` 的派生表示；`delivery-workflow` 继续拥有最终目标集合和完成裁决。实现不得把结果时效规则复制到全局规则、交付工具或消费者特例。

## DES-002 结果诊断是唯一共享事实源

- 状态: confirmed
- 满足: AC-001, AC-002, AC-003, AC-006
- 依赖: DES-001

每个当前结果对当前任务合同与语义索引只计算一次完整 `result_diagnostics`。页级候选对象保存完整诊断；聚合器从这些已计算列表派生结果级数量、诊断条目总数和 kind 计数。`status` 与 `render` 使用同一聚合函数，不另行实现来源快照时效判断。

## DES-003 分层字段显式表达计数对象与范围

- 状态: confirmed
- 满足: AC-001, AC-002, AC-003
- 依赖: DES-002

`completion-context` 把查询诊断和候选结果诊断分开命名，并提供当前返回页的总汇总；`status` 和 `render` 把结果引用、任务 revision 陈旧、来源快照问题和诊断条目分开。字段名本身足以确定统计对象，不依赖阅读实现或从零值猜测作用域。

## DES-004 后继验证形成新的目标证据而不改变历史结果

- 状态: confirmed
- 满足: REQ-002, AC-004, AC-005, CON-002
- 依赖: DES-001

重新执行或验证后提交的新结果通过明确 `evidence_for`、执行时 `source_snapshot` 和直接验证引用独立支持相应目标。旧结果仍携带自己的不可覆盖来源快照与诊断；辅助视图并列提供两者，模型按最终完成合同选择当前适用证据。依赖与消费关系只表达输入关系，不推导重新验证。

## DES-005 当前消费者一次迁移到唯一新合同

- 状态: confirmed
- 满足: REQ-003, AC-006, AC-007
- 依赖: DES-003, DES-004

仓库当前消费者包括 `taskctl` 的 completion、status、render 输出，`TASK_TABLE.md` 生成文本、单元测试和 task-table-manager 文档。它们直接迁移到新字段；真实旧格式消费者没有证据时不保留歧义别名。变更后的 skill 内容由模块回归、quick validation、项目路由合同和 detached 证据共同验证。
