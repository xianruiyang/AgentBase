---
name: task-table-manager
description: 低 Token 管理长期任务合同、依赖、状态、结果摘要与恢复上下文。用于定义任务/结果字段，创建、更新、查询长期记录，以 taskctl 取得最终复核上下文，交付证据、受保护或待议上游调整引发既有任务表合同/可继续范围/依赖/状态/结果重投影，或多人领取、恢复上下游产出；不用于单轮修改、只读消费分析、简单清单、一次性诊断，也不裁决需求、设计、现状或方案。
---

# Task Table Manager

任务表是执行投影，不裁判计划正确性。模型把已形成的方案动作写成任务合同，并按文档、证据和授权决定推进；`taskctl` 只辅助存储、索引、查询、上下文压缩和可重建视图，不签发执行许可。

## 路由与协同

- 多个候选共享未证前提、须先闭合真实消费者、存在昂贵批量验证或反复失效时，由 `$execution-governor` 裁决当前动作；本 skill 只保存已投影的证明、消费和依赖，不按任务深度或数量重定前沿。
- 需要需求分析、目标设计、现状分析或方案设计时使用 `$delivery-workflow`；本 skill 只消费其稳定 ID 和索引。
- 根因、职责、权威入口、共享职责形成、权威变化的跨消费者影响或共享阻断门禁需要专项裁决时使用 `$change-governance`；其结论进入既有方案或合同 owner，不进入 CLI 规则。
- 执行任务时按真实工作选择领域 skill；任务记录不约束运行时路由。
- 任务的推理提示只是非权威输入，不触发查询或改变线程推理深度；仅在用户明确要求时由 `$reasoning-governor` 读写。任务表不保存线程设置。

## 真源与工具

- 创建/修改任务合同或决定增删、调整真实依赖时读 [task-contracts.md](references/task-contracts.md)，待写依赖尚未回写也须读；仅查询 `impact/context` 或用 `note/reopen` 回写状态且不改合同/依赖时不读。
- 调用 `taskctl` 时先读 [tooling.md](references/tooling.md)，再按动作加载：[query-tooling.md](references/query-tooling.md) 管多任务查询；[authoring-tooling.md](references/authoring-tooling.md) 管 `init/draft/add/update`；[execution-tooling.md](references/execution-tooling.md) 管 `context`、状态命令和 `complete`；[completion-tooling.md](references/completion-tooling.md) 管 `completion-context`。仅设计语义不读工具引用；只形成待写依赖而不执行 `add/update` 时只读 query；回写状态、证据前沿或 `next_action` 读 execution；跨族才组合。
- [execution.md](references/execution.md) 仅用于推进、恢复或并行领取；查询上下游、裁决下一动作或形成待写依赖，即使涉及失败/阻塞也不读。
- 工具入口是 PATH 中的 `taskctl`，显式传绝对 `--task-dir`；不可用时按文档合同继续，不从 skill 找脚本。默认 `--view model` 返回稀疏证据；程序、测试或确需完整身份时才用 `--view machine`。两种视图共享任务事实，字段与恢复入口由命令族引用维护。
- `task-table.json` 登记目录；`tasks/<ID>.json` 存任务合同，`state/<ID>.json` 存执行状态和 CLI 维护的 UTC 起止时间，`results/<ID>.r<state-revision>.json` 存可追溯结果摘要，`snapshots/<sha256>.json` 存内容寻址的不可变执行来源映射；状态文件只指向当前结果。
- `TASK_TABLE.md` 与 `.work-cache/index.json` 均非真源；生成语义见 [query-tooling.md](references/query-tooling.md)。
- `add/update` 和全部状态写命令在真源提交后、释放工作区锁前刷新 `TASK_TABLE.md`；生成视图失败不得回滚或掩盖已提交真源，须返回视图陈旧诊断和明确的 `render` 恢复入口。
- 任务合同、状态和结果是程序消费且由模型决定语义的结构化真源；CLI 可用时通过 `draft/add/update` 和带 revision 的状态命令维护，不直接改永久 JSON。`add/update` 注入 schema/revision，`complete` 注入结果 envelope；查询默认用当前动作的 model 视图，完整结构只供显式机器消费者，生成表格和索引不作修改入口。

## 使用方式

1. 模型根据已有交付链的上游 `SOL/GAP/DES/AC/REQ`，或独立任务的明确用户要求与真实工作范围编写合同语义；公共产出与消费者接入拆分时必须声明真实消费依赖，需要模板时可用默认 model `taskctl draft`，其结果保留稳定 ID 和语义字段但不返回 schema/revision。CLI 不自动把文档变成任务。
2. 结构化存储用 `add/update`。模型输入只维护稳定 ID 与任务语义，CLI 注入 schema/revision，并以调用方已读 revision 保护并发写入；语义问题只诊断。
3. 用 `next/deps/dependents/context` 取得有界候选、依赖与结果证据；`context` 还投影执行检查点和关联 DCR。稳定上游的单一候选可直接执行；共享未证前提、昂贵验证或失效关系时交 `$execution-governor` 裁决，不以 CLI 排序、任务深度或完成数量替代。执行前用 `context --capture` 固化最终模型可见来源。
4. 跨轮跟踪用 `claim/start/note/complete/reopen/release`，先读 state revision 并传 `--expected-state-revision`；停用任务标 `retired`。前沿、消费者、case、覆盖、证据、失效来源或下一动作改变时先 `note` 再继续，普通进度不复制。命令只记录判断；写入后刷新展示，仅回执报告陈旧时修因并 `render`。
5. 模型结果文件只写实际结果、验证、未决问题和证据等语义正文；`complete` 从命令目标、调用方实际执行的 task/state revision 和已捕获来源收据形成完整永久结果。后继验证提交自己的收据和直接证据，不改写或隐藏旧结果诊断。
6. 上游改变时按实际依赖逐项判断消费者与结果，必要时用递归 `impact`；有交付链时按 `$delivery-workflow` 回写上游并按需查询影响。依结论更新、重开或退休任务并重新验证；CLI 只返回路径和陈旧诊断，不自动重置状态或宣布结果失效。
7. 有交付链且最终复核范围较大时，可用 `completion-context` 从当前 Markdown 分页取得目标、约束、全部 DCR 和关联结果。CLI 不筛选完成阻断项、不返回整体通过值；任务或文档改变时从第一页重审。独立任务按下述完成标准直接核对。

## 局部门禁与诊断

只对以下机械风险阻断当前命令：路径越界或对象错误、破坏性覆盖、工作区锁、已有记录写入缺少 CAS revision 或冲突、显式完成收据在写入时缺失/不可读/身份不一致、输入输出超限，以及最终复核分页快照改变。精确操作需唯一 ID 时，只拒绝该歧义对象。

依赖环/自依赖、owner 不一致、状态流转、可解析的非标准状态/依赖/来源 ID/路径、重复值、已完成合同后续修订、未完成依赖、上游未决、快照或缓存漂移、任务粒度、scope 重叠、空验证/结果、引用或结果来源不完整/陈旧都只诊断；历史收据资产异常也只诊断并保留历史。诊断不产生执行许可或产品完成结论。

报告进度时分开给出任务状态、上游未决项、影响传播、结果引用数、任务 revision 陈旧、来源快照问题和结果验证摘要，不把任一计数当成整体完成证明。

## 完成标准

有交付链时按 `$delivery-workflow` 当前确认目标复核；独立任务对照明确用户要求、任务合同、适用约束与直接证据，不补建阶段文档。合同不得缩小或替代用户目标，`done` 不证明结果成立。改变长期 owner 或契约时仍须覆盖必要消费者与影响。
