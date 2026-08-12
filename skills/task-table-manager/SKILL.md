---
name: task-table-manager
description: 用低 Token 管理长期执行的任务合同、依赖图、状态、结果摘要和恢复上下文。用于工作必须跨轮持续、存在真实任务依赖、需要多人领取或需要快速查询当前任务及上下游产出时；不用于单轮修改、简单清单、一次性诊断，也不负责需求、设计、现状或方案的语义裁决。
---

# Task Table Manager

任务表是执行投影，不是计划正确性的裁判。模型负责把已经形成的方案动作写成任务合同并判断何时推进；CLI 负责确定性的存储、查询、上下文压缩和可重建视图。

## 路由与协同

- 需要需求分析、目标设计、现状分析或方案设计时使用 `$delivery-workflow`；本 skill 只消费其稳定 ID 和索引。
- 根因、职责、权威入口或共享阻断门禁需要专项裁决时使用 `$change-governance`；其结论应进入上游阶段文档，不进入 CLI 规则。
- 执行任务时继续按真实工作触发 C++、符号、搜索、PowerShell、空间等领域 skill。任务可记录建议 skill，但不能强制或替代运行时路由。
- 推理深度使用 `$reasoning-governor`；任务可提供非权威初始建议，但不保存线程设置或限制执行中自由升降。

## 真源与工具

- 完整读取 [task-contracts.md](references/task-contracts.md) 创建或修改任务；执行、恢复和并行领取时读取 [execution.md](references/execution.md)；使用 CLI 时读取 [tooling.md](references/tooling.md)。
- 工具入口是 `<SkillDir>/scripts/taskctl.py`。每次显式传绝对 `--task-dir`；状态和结果只写入该工作区。
- `task-table.json` 登记目录；`tasks/<ID>.json` 持有任务合同，`state/<ID>.json` 持有执行状态，`results/<ID>.r<state-revision>.json` 持有可追溯的结果摘要，状态文件只指向当前结果。
- `TASK_TABLE.md` 是生成视图，`.work-cache/index.json` 是上游索引；两者都不是任务或语义真源。

## 使用方式

1. 用 `taskctl draft` 生成候选合同，模型根据上游 `SOL/GAP/DES/AC/REQ` 和真实工作范围完成内容；CLI 不自动把文档变成任务。
2. 用 `add` 或 `update` 保存任务。活动任务的合同只能由当前 owner 携带 task/state 两个期望 revision 更新；结构、ID、路径和 revision 冲突会拒绝写入。依赖未完成、上游未决、缺验证建议等只作为诊断。
3. 用 `next`、`deps`、`dependents` 和 `context` 以有界输出选择工作。`hard` 依赖未完成时默认降低推荐度，但模型可用 `--include-blocked` 查看并继续分析或准备工作。
4. 用 `claim/start/note/complete/reopen/release` 维护每项独立状态。可以并行领取不同任务；mutation scope 重叠只提示风险。
5. `complete` 保存实际结果、验证与未决问题。后继任务读取前置结果摘要，不读取完整对话或原始日志。
6. 上游改变时用 `$delivery-workflow` 的 `impact` 和本工具的 `dependents` 判断影响；CLI 不自动重置状态或宣布结果失效。
7. 需要最终复核时用 `completion-context` 从受保护基线精确取得每个 `REQ/AC/UDES`，再汇总当前索引中的关联结果；模型逐项判断直接证据。CLI 会复算索引派生内容且不返回整体通过值；分页必须沿用同一个 snapshot ID，状态改变时从第一页重审。

## 硬错误与诊断

只对以下情况拒绝操作：无法解析或越界的文件、重复或不匹配的 ID、依赖环、同一任务的领取冲突、revision 并发覆盖、非法状态变换和破坏性覆盖。

以下只报告诊断：未完成依赖、上游未决或缓存缺失、任务粒度可疑、mutation scope 重叠、验证或结果为空、引用覆盖不完整。诊断不会产生执行许可或产品完成结论。

报告进度时分开给出任务状态、上游未决项和结果验证摘要，不把任一计数当成整体完成证明。最终完成标准只来自 `$delivery-workflow` 的受保护需求与用户设计。
