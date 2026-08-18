---
name: task-table-manager
description: 用低 Token 管理长期任务合同、依赖图、状态、结果摘要和恢复上下文。用于必须创建、更新或查询长期任务记录，或多人领取与恢复上下游产出时；不用于单轮修改、只读消费关系分析、简单清单、一次性诊断，也不裁决需求、设计、现状或方案。
---

# Task Table Manager

任务表文档是执行投影，不是计划正确性的裁判。模型负责把已经形成的方案动作写成任务合同，并基于文档、证据和当前授权判断何时推进。`taskctl` 只辅助存储、索引、查询、上下文压缩和可重建视图，不签发执行许可。

## 路由与协同

- 需要需求分析、目标设计、现状分析或方案设计时使用 `$delivery-workflow`；本 skill 只消费其稳定 ID 和索引。
- 根因、职责、权威入口、共享职责形成、权威变化的跨消费者影响或共享阻断门禁需要专项裁决时使用 `$change-governance`；其结论应进入上游阶段文档，不进入 CLI 规则。
- 执行任务时继续按真实工作触发 C++、符号、搜索、PowerShell、空间等领域 skill。任务可记录建议 skill，但不能强制或替代运行时路由。
- 推理深度使用 `$reasoning-governor`；任务可提供非权威初始建议，但不保存线程设置，也不在用户明确覆盖之外限制执行中的动态升降。

## 真源与工具

- 完整读取 [task-contracts.md](references/task-contracts.md) 创建或修改任务；执行、恢复和并行领取时读取 [execution.md](references/execution.md)；使用 CLI 时读取 [tooling.md](references/tooling.md)。
- 工具入口是 `<SkillDir>/scripts/taskctl.py`。只在它能降低编辑、查询或恢复成本时使用，并显式传绝对 `--task-dir`；CLI 不可用时仍按同一文档合同继续。默认 `--view model` 只返回当前命令所需的稀疏证据：写入回执保留目标、写后 revision/语义状态、结果引用和实际问题；单项查询不复制永久 schema 或重复身份；列表和关系只有在截断时返回额外总数与续点，但明确保留“无候选/无依赖”等会改变动作的零结论。程序、测试或确需完整身份与字段时显式使用 `--view machine`；两种视图来自同一次任务事实计算。
- `task-table.json` 登记目录；`tasks/<ID>.json` 持有任务合同，`state/<ID>.json` 持有执行状态，`results/<ID>.r<state-revision>.json` 持有可追溯的结果摘要，`snapshots/<sha256>.json` 持有内容寻址的不可变执行来源映射，状态文件只指向当前结果。
- `TASK_TABLE.md` 是生成视图，`.work-cache/index.json` 是上游索引；两者都不是任务或语义真源。
- 任务合同、状态和结果是程序消费且由模型作出语义决定的结构化真源；CLI 可用时，模型通过 `draft/add/update` 的语义输入和带 revision 的状态命令维护，不直接改永久 JSON 绕过路径、原子写入或并发比较。`add/update` 注入任务 schema/revision，`complete` 注入结果 envelope；模型查询默认使用按当前动作投影的视图，完整结构只供显式机器消费者。生成表格和索引不得作为修改入口。

## 使用方式

1. 模型根据上游 `SOL/GAP/DES/AC/REQ` 和真实工作范围编写任务合同语义；公共产出与消费者接入拆分时必须声明真实消费依赖，需要模板时可用默认 model `taskctl draft`，其结果保留稳定 ID 和语义字段但不返回 schema/revision。CLI 不自动把文档变成任务。
2. 需要结构化存储时用 `add` 或 `update`。模型输入保留任务 `id` 及语义正文，不写 schema/revision；`add` 注入初始 revision，`update` 必须先读当前合同并传 `--expected-task-revision`，再由工具写入下一 revision。上一版完整 task envelope 由相同入口单向规范化。写入只对 ID/路径、破坏性覆盖、工作区锁和 CAS revision 冲突设置门禁；owner、依赖环、状态流转、上游未决和验证缺失只作为诊断。
3. 用 `next`、`deps`、`dependents` 和 `context` 以有界模型视图选择工作。先考虑用户优先级、硬依赖、关键风险、共享前置、冲突和当前能力；条件相当时，优先继续当前目标链并缩短到最近可验证闭环的距离，避免打开更多未闭合的平级分支。任务深度只作线索，CLI 排序只是建议。开始实际执行时用 `context --capture`；模型视图保留必要上游正文和 `{ref,count,complete}` 收据，完整指纹映射由工具按最终 Token 预算投影后写入机器快照。`hard` 依赖未完成时可用 `--include-blocked` 查看并继续分析或准备工作。
4. 需要跨轮跟踪时用 `claim/start/note/complete/reopen/release`，每次先读取当前 state revision 并传 `--expected-state-revision`；不再执行的任务可标记 `retired`。命令记录模型已作出的判断，不决定该判断是否被允许。
5. 模型结果文件只写实际结果、验证、未决问题和证据等语义正文；`complete --expected-task-revision <REV> --source-snapshot-ref <REF>` 从命令目标、调用方实际执行的任务 revision 和捕获收据形成完整永久结果。任务与状态 revision 分别进行 CAS，完成时当前版本不能替代实际输入。显式收据在写入前必须可解引用且身份一致；覆盖不足和陈旧只诊断。旧内联快照结果继续可读，上一版完整结果输入由同一入口规范化并外部化引用；后继验证提交自己的收据、明确 `evidence_for` 和直接证据，不改写或隐藏旧结果诊断。
6. 上游改变时用 `$delivery-workflow` 的 `impact`、本工具的递归 `impact` 和实际系统依赖逐项判断消费者与结果，按结论更新、重开或退休任务并重新验证；CLI 只返回路径和陈旧诊断，不自动重置状态或宣布结果失效。
7. 需要最终复核且范围较大时可用 `completion-context` 的模型视图从当前 Markdown 取得每个 `REQ/AC/UDES`、`CON` 和全部 `DCR`，再汇总关联结果；模型视图保留目标正文、候选结果摘要、诊断、证据引用和分页恢复，但不复制候选结果的完整 `source_snapshot`。查询诊断与当前页候选结果诊断分层计数，完整机器结果仍可由 `--view machine` 取得。DCR 原始状态只供模型复核，不由 CLI 筛选完成阻断项。CLI 不返回整体通过值；分页必须沿用同一 snapshot ID，任务或文档改变时从第一页重审。

## 局部门禁与诊断

只对以下机械风险阻断当前命令：路径越界或写错对象、破坏性覆盖、工作区锁、已有记录写入缺少 CAS revision 或 revision 冲突、显式完成收据在写入时缺失/不可读/身份不一致、输入/输出资源超限，以及最终复核分页中快照改变。精确操作需唯一 ID 时，只就该对象的歧义拒绝操作。

依赖环或自依赖、owner 不一致、状态流转、可解析但非标准的状态/依赖/来源 ID/描述性路径、重复值、已完成合同的后续修订、未完成依赖、上游未决、快照/缓存漂移、任务粒度、mutation scope 重叠、验证或结果为空、引用覆盖不完整，以及未提供结果来源、来源覆盖不完整或陈旧都只报告诊断。已经落盘的历史结果后来出现收据资产异常时同样只诊断并保留历史。诊断不会产生执行许可或产品完成结论。

报告进度时分开给出任务状态、上游未决项、影响传播、结果引用数、任务 revision 陈旧、来源快照问题和结果验证摘要，不把任一计数当成整体完成证明。最终完成标准只来自 `$delivery-workflow` 当前执行周期经用户确认的需求与用户设计；本次方案改变长期 owner 或契约时，其必要影响闭环仍是所选实现成立的证据。
