# Legacy：执行与继续任务表

> 仅用于没有 `plan.json` 的既有 Markdown 计划，以保证进行中的任务不被静默迁移。v1 执行只使用 `SKILL.md` 的 `resume → begin → close/audit` 热路径。

只在执行、继续、验收、回退或恢复任务项时读取。不要同时加载 `writing.md`，除非当前问题确实要求重构任务表。

## 目录

- [开始顺序](#开始顺序)
- [标准执行](#标准执行)
- [Handoff](#handoff)
- [思考深度调节](#思考深度调节)
- [修改方案或任务表](#修改方案或任务表)
- [子任务表同步](#子任务表同步)
- [回退](#回退)
- [结束本轮](#结束本轮)
- [推理深度入口](#推理深度入口)
- [禁止](#禁止)

## 开始顺序

1. 读取主任务表“当前状态”和“子任务表索引”。
2. `active_child_table` 不是 `none` 时，沿 Markdown 链接读取活动子表状态；不要靠目录搜索猜路径。
3. 选择当前允许执行的一项；除非用户明确要求合并，本轮只完成一项。
4. 只加载：
   - 读取条件适用的任务表级依赖。
   - 当前任务组依赖和组 memo。
   - 当前任务行、`handoff.md` 和专属 `deps_for`。
5. 不加载其他组、未来任务或上游 raw 产物全文。

## 标准执行

1. 确认依赖、目标产出、验收标准和当前思考深度。
2. 将当前项标为 `in_progress`。
3. 实现并执行最小充分验收。
4. raw 响应、脚本、截图和日志写入 `<artifact_root>/<任务ID>/`。
5. 同组后续任务会复用的重要结论更新到 `<artifact_root>/<组ID>/memo.md`，只写路径、用途、范围和简短结论。
6. 为每个明确消费者分别生成 `deps_for/<consumer_task_id>.md`。
7. 更新唯一人工交接入口 `handoff.md`。
8. 只把进度、产物路径和必要依赖链接回写任务表。

## Handoff

```md
# <ID> <任务名称>

## 输入依赖
- 任务表级：
- 任务组级：
- 任务项级：

## 执行摘要
- 做了什么：
- 关键判断：

## 验收结果
- 方法：
- 结果：

## 产物
- `path/to/artifact`

## 未完成/风险
- 无：

## 后续依赖补充
- 已生成 `deps_for/<consumer>.md`：
```

Token 摘要仅在用户要求统计时加入。handoff 不粘贴 raw JSON、长日志或完整执行流水。

## 思考深度调节

遵守全局动态推理规则并使用 `$reasoning-governor`。任务行中的深度只作为开始当前项时的初始建议；执行中只要下一段工作的真实不确定性、后果、可逆性或验证负担发生实质变化，就重新判断最低充分等级，不限于任务项边界。有 active Goal 且目标等级不同的，读回 next-turn 设置成功后立即结束当前轮，由 Goal 继续；没有 active Goal 时不自主切换。

## 修改方案或任务表

任务表未覆盖新问题、关键假设失效、范围显著扩大或任务粒度无法安全推进时，允许修改方案和任务表。

- 修改前记录触发原因、受影响任务和仍有效结论。
- 不静默改写已完成任务的验收事实。
- 小范围变化更新原任务项或新增诊断项。
- 独立复杂范围拆为子方案和子任务表。
- 重构后检查三层依赖、消费者、`deps_for`、memo、下一动作复杂度和回退边界。

## 子任务表同步

创建子表的同一轮必须：

1. 在主表“子任务表索引”登记稳定子表 ID、父任务、可点击链接、完成进度、当前子任务、进入条件和回写位置。
2. 主表 `active_child_table` 指向该链接。
3. 父任务行“依赖”字段登记同一链接。
4. 子表状态写入 `parent_table`、`parent_task`、`parent_child_index_id`、`parent_writeback` 和独立 `artifact_root`。

每次子任务推进、暂停、阻塞或完成时，同步主表索引的 `完成进度` 和 `当前子任务`。子表完成后：

- 索引更新为 `done 100%`。
- 清空主表 `active_child_table`。
- 按 `parent_writeback` 更新父任务。
- 父任务从子表 handoff/专属依赖继续，不读取全部子表 raw 产物。

默认一个父任务只有一个 active 子表；并行必须由用户明确要求。

## 回退

`回退目标` 只有根因明确来自上游时才填写，不是备注或 `git revert`。

- 清除回退目标及其直接/间接下游产物，重置进度后从目标重做。
- 按回退后的下一动作重新判断思考深度；不自动提高一级，也不只为切换深度结束本轮。
- 证据冲突、设计假设失效或回退影响跨模块时，先重梳理影响和任务边界；必要时修改或拆分方案与任务表。
- 根因不明时不机械回退上一项。

## 结束本轮

- 当前项完成：更新任务行、handoff、消费者依赖和组 memo；下一动作需要不同深度时按 `$reasoning-governor` 协议设置并读回 next-turn。
- 当前项未完成：下一段工作需要不同深度时，先保存恢复所必需的现场，再按 `$reasoning-governor` 协议设置并结束。
- 有活动子表：同步主表索引后再结束。
- 不得把未解决任务标为 `done`。

## 推理深度入口

正式入口由 `$reasoning-governor` 持有。先读取当前 thread 的 next-turn settings，只有目标等级不同才设置：

```powershell
$env:CODEX_THREAD_ID
$ReasoningGovernorSkillDir = '<reasoning-governor-skill-dir>'
pwsh.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $ReasoningGovernorSkillDir 'scripts\reasoning-governor.ps1') -Status
pwsh.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $ReasoningGovernorSkillDir 'scripts\reasoning-governor.ps1') -Effort high
```

支持 `low`、`medium`、`high`、`xhigh`、`max`、`ultra`。设置成功口径和当前轮不可读边界以 `$reasoning-governor` 为准；旧任务表脚本只服务于发布前已经开始且仍引用旧路径的任务，不再定义行为。确认这些任务完成或已改用正式入口后删除兼容转发，任何新文档不得继续引用旧路径。

## 禁止

- 不在一轮执行多个任务项，除非用户明确要求。
- 不把完整日志、raw JSON、截图清单或产物正文写入任务表。
- 不读取无关任务组和未来任务资料。
- 不让当前项自行整理缺失的上游大型依赖；回到上游补专属 `deps_for`。
- 不在未知根因时继续堆后续任务。
- 不把子任务表只记录在 handoff、memo 或对话中。
