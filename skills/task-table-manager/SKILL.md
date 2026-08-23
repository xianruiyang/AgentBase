---
name: task-table-manager
description: 低 Token 管理长期任务合同、依赖、状态、结果摘要与恢复上下文。用于定义任务/结果字段，创建、更新、查询长期记录，以 taskctl 取得最终复核上下文，交付证据、受保护或待议上游调整引发既有任务表合同/可继续范围/依赖/状态/结果重投影，或多人领取、恢复上下游产出；不用于单轮修改、只读消费分析、简单清单、一次性诊断，也不裁决需求、设计、现状或方案。
---

# Task Table Manager

任务表文档是执行投影，不是计划正确性的裁判。模型负责把已经形成的方案动作写成任务合同，并基于文档、证据和当前授权判断何时推进。`taskctl` 只辅助存储、索引、查询、上下文压缩和可重建视图，不签发执行许可。

## 路由与协同

- 多个候选共享未证前提、需要先闭合一个真实消费者、存在昂贵批量验证或反复失效时使用 `$execution-governor` 裁决当前动作；本 skill 只保存已经投影的证明、消费和依赖关系，不按任务深度或数量重新决定前沿。
- 需要需求分析、目标设计、现状分析或方案设计时使用 `$delivery-workflow`；本 skill 只消费其稳定 ID 和索引。
- 根因、职责、权威入口、共享职责形成、权威变化的跨消费者影响或共享阻断门禁需要专项裁决时使用 `$change-governance`；其结论应进入上游阶段文档，不进入 CLI 规则。
- 执行任务时按真实工作选择领域 skill；任务记录不约束运行时路由。
- 任务的推理提示只是非权威输入；复杂执行由 `$execution-governor` 判断目标档位和状态价值，再按需使用 `$reasoning-governor` 读写线程设置。任务表不保存线程设置，也不限制执行中的动态裁决。

## 真源与工具

- 创建、修改任务或决定待写真实依赖时读 [task-contracts.md](references/task-contracts.md)；执行、恢复或并行领取才读 [execution.md](references/execution.md)，纯查询或不涉及依赖的下一项判断不读。只设计任务语义或尚未决定调用 CLI 时不预读工具引用。决定调用 CLI 且能降低成本时读 [tooling.md](references/tooling.md)，再只增加当前命令族的一项：多任务上下游查询用 [query-tooling.md](references/query-tooling.md)，`init/draft/add/update` 用 [authoring-tooling.md](references/authoring-tooling.md)，判断待写依赖不读；`context`、状态命令和 `complete` 用 [execution-tooling.md](references/execution-tooling.md)，`completion-context` 用 [completion-tooling.md](references/completion-tooling.md)；明确回写任务状态、证据前沿或 `next_action` 即选择状态命令，跨命令族时才组合。
- 工具入口是 `<SkillDir>/scripts/taskctl.py`。只在它能降低编辑、查询或恢复成本时使用，并显式传绝对 `--task-dir`；CLI 不可用时仍按同一文档合同继续。默认 `--view model` 返回当前动作所需的稀疏证据，程序、测试或确需完整身份与字段时显式使用 `--view machine`；两种视图来自同一次任务事实计算，具体字段与恢复入口由当前命令族引用维护。
- `task-table.json` 登记目录；`tasks/<ID>.json` 持有任务合同，`state/<ID>.json` 持有执行状态和 CLI 维护的 UTC 起止时间，`results/<ID>.r<state-revision>.json` 持有可追溯的结果摘要，`snapshots/<sha256>.json` 持有内容寻址的不可变执行来源映射，状态文件只指向当前结果。
- `TASK_TABLE.md` 与 `.work-cache/index.json` 均非真源；生成语义见 [query-tooling.md](references/query-tooling.md)。
- `add/update` 和全部状态写命令在真源提交后、释放同一工作区锁前刷新 `TASK_TABLE.md`；生成视图失败不得回滚或掩盖已经提交的任务、状态或结果，命令必须返回视图陈旧诊断和显式 `render` 恢复入口。
- 任务合同、状态和结果是程序消费且由模型作出语义决定的结构化真源；CLI 可用时，模型通过 `draft/add/update` 的语义输入和带 revision 的状态命令维护，不直接改永久 JSON 绕过路径、原子写入或并发比较。`add/update` 注入任务 schema/revision，`complete` 注入结果 envelope；模型查询默认使用按当前动作投影的视图，完整结构只供显式机器消费者。生成表格和索引不得作为修改入口。

## 使用方式

1. 模型根据上游 `SOL/GAP/DES/AC/REQ` 和真实工作范围编写任务合同语义；公共产出与消费者接入拆分时必须声明真实消费依赖，需要模板时可用默认 model `taskctl draft`，其结果保留稳定 ID 和语义字段但不返回 schema/revision。CLI 不自动把文档变成任务。
2. 需要结构化存储时用 `add` 或 `update`。模型输入只维护稳定 ID 与任务语义，CLI 注入机器 schema/revision，并用调用方已读 revision 保护并发写入；语义问题只诊断，不把工具变成任务裁判。
3. 用 `next`、`deps`、`dependents` 和 `context` 取得有界候选、依赖与结果证据；`context` 还投影执行检查点和关联 DCR。稳定上游的单一候选可直接执行；候选共享未证前提、昂贵验证或失效关系时，把证据交给 `$execution-governor` 裁决，不能由 CLI 排序、任务深度或完成数量替代。实际执行前用 `context --capture` 固化最终模型可见来源。
4. 跨轮跟踪用 `claim/start/note/complete/reopen/release`，先读 state revision 并传 `--expected-state-revision`；停用任务标 `retired`。前沿、消费者、验证 case、已证覆盖、未覆盖维度、证据、失效来源或下一动作改变时，先用 `note` 写回再继续；普通进度不复制。命令只记录模型判断，不决定其许可；成功写入会刷新展示，仅回执报告陈旧时修因后显式 `render`。
5. 模型结果文件只写实际结果、验证、未决问题和证据等语义正文；`complete` 从命令目标、调用方实际执行的 task/state revision 和已捕获来源收据形成完整永久结果。后继验证提交自己的收据和直接证据，不改写或隐藏旧结果诊断。
6. 上游改变时用 `$delivery-workflow` 的 `impact`、本工具的递归 `impact` 和实际系统依赖逐项判断消费者与结果，按结论更新、重开或退休任务并重新验证；CLI 只返回路径和陈旧诊断，不自动重置状态或宣布结果失效。
7. 需要最终复核且范围较大时可用 `completion-context` 从当前 Markdown 分页取得目标、约束、全部 DCR 和关联结果。CLI 不筛选完成阻断项、不返回整体通过值；任务或文档改变时从第一页重审。

## 局部门禁与诊断

只对以下机械风险阻断当前命令：路径越界或写错对象、破坏性覆盖、工作区锁、已有记录写入缺少 CAS revision 或 revision 冲突、显式完成收据在写入时缺失/不可读/身份不一致、输入/输出资源超限，以及最终复核分页中快照改变。精确操作需唯一 ID 时，只就该对象的歧义拒绝操作。

依赖环或自依赖、owner 不一致、状态流转、可解析但非标准的状态/依赖/来源 ID/描述性路径、重复值、已完成合同的后续修订、未完成依赖、上游未决、快照/缓存漂移、任务粒度、mutation scope 重叠、验证或结果为空、引用覆盖不完整，以及未提供结果来源、来源覆盖不完整或陈旧都只报告诊断。已经落盘的历史结果后来出现收据资产异常时同样只诊断并保留历史。诊断不会产生执行许可或产品完成结论。

报告进度时分开给出任务状态、上游未决项、影响传播、结果引用数、任务 revision 陈旧、来源快照问题和结果验证摘要，不把任一计数当成整体完成证明。最终完成标准只来自 `$delivery-workflow` 当前执行周期经用户确认的需求与用户设计；本次方案改变长期 owner 或契约时，其必要影响闭环仍是所选实现成立的证据。
