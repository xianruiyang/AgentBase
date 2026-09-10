---
name: execution-governor
description: 在共享未证前提、多维组合扩量、同责新增与退出可能脱节、昂贵验证、反复失败、测试迁移/评审横向扩张或执行成本质疑时控制下一动作。适用于只读裁决这些执行问题；不用于稳定前提的普通实现、等价与验收已确认的有界批次、普通局部验证、用户已延后验证而仅继续实现、单个职责裁决或概念讨论。
---

# Execution Governor

在既定目标和设计内控制实现与验证顺序。没有共享未知时不制造前置流程；单次昂贵操作不虚构平级消费者。目标、记录与完成状态仍由原 owner 维护。

## 按需引用

- 共享前提、首个消费者、多维组合、批量依赖或任务投影：读 [decision-frontier.md](references/decision-frontier.md)。
- 失败、重试、遮蔽、成本分析、昂贵验证、成批 fixture/示例/测试、旧检查迁移或评审扩张：读 [failure-and-cost.md](references/failure-and-cost.md)。
- 只读裁决组合覆盖而不设计、生成或运行昂贵动作时，只读 decision-frontier。首次昂贵 preflight 还需定义反证、首个消费者或遮蔽范围时两者都读；其余按实际缺口组合。

## 执行边界

- 共享前提按 decision-frontier 选择首个消费者、等价范围和扩量条件；受阻换例只用其中的受控转移条件。
- 昂贵运行与失败处理按 failure-and-cost 核查实际入口、前置和判别信息；成本质疑影响下一动作时，先暂停新的昂贵运行。
- 授权、反例后的停止范围、按影响验证及持久记录继承全局规则；本 skill 不另建控制账本或固定汇报表。

长期 owner、入口、迁移或争议 oracle 需重裁时使用 change-governance；实际修订交付文档或任务合同才使用 delivery-workflow/task-table-manager。单纯读取稳定上游或引用其他 skill 不触发加载。
