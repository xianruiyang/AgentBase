# 模型交互面合同

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
| T001-CONTRACTS-KERNEL | done | codex | 建立模型交互面根合同与全局内核 | — | results/T001-CONTRACTS-KERNEL.r6.json | 1 |
| T002-ASSET-OWNERS | done | codex | 接入交付与任务资产的读取和修改合同 | T001-CONTRACTS-KERNEL:hard | results/T002-ASSET-OWNERS.r3.json | 2 |
| T003-EVENT-LOG-VIEWS | done | codex | 为事件日志建立模型恢复与机器读取面 | T001-CONTRACTS-KERNEL:hard | results/T003-EVENT-LOG-VIEWS.r3.json | 1 |
| T004-VERIFY-DELIVER | done | codex | 扩展策略评估并闭合模型交互面版本 | T001-CONTRACTS-KERNEL:hard, T002-ASSET-OWNERS:hard, T003-EVENT-LOG-VIEWS:hard | results/T004-VERIFY-DELIVER.r3.json | 2 |
