# 模型可见工具输出合同

> 本文件由 taskctl 生成，只是任务合同与状态的可重建视图，不表示允许执行或产品完成。

## 状态统计

| 状态 | 数量 |
| --- | ---: |
| todo | 0 |
| claimed | 0 |
| in_progress | 0 |
| review | 0 |
| blocked | 0 |
| done | 4 |
| retired | 0 |

## 复核与结果

- 需复核任务：0
- 当前状态引用结果：4
- 含验证结果：4
- 含未决结果：0
- 含结果诊断：0
- 任务合同 revision 陈旧结果：0
- 含来源快照问题结果：0
- 结果诊断条目：0

## 上游状态

- 用户确认快照：protected
- 可修订上游未决：0
- 延后讨论项：0

## 任务

| ID | 状态 | Owner | 标题 | 依赖 | 结果 | 合同修订 |
| --- | --- | --- | --- | --- | --- | ---: |
| T001-CONTRACTS-RULES | done | codex-root | 建立输出面正式合同与规则链 | — | results/T001-CONTRACTS-RULES.r2.json | 1 |
| T002-TASKCTL-VIEWS | done | codex-root | 实现 taskctl 消费者输出视图 | T001-CONTRACTS-RULES:hard | results/T002-TASKCTL-VIEWS.r3.json | 2 |
| T003-WORKCTL-VIEWS | done | codex-root | 实现 workctl 消费者输出视图 | T001-CONTRACTS-RULES:hard | results/T003-WORKCTL-VIEWS.r3.json | 2 |
| T004-VERIFY-DELIVER | done | codex-root | 验证消费者迁移并完成交付 | T002-TASKCTL-VIEWS:hard, T003-WORKCTL-VIEWS:hard | results/T004-VERIFY-DELIVER.r6.json | 4 |
