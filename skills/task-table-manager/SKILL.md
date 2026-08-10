---
name: task-table-manager
description: 管理有证据支撑的规划链和长期执行。用于工作必须跨轮持续、存在真实依赖、需要持久完成审计，或需要建立与修复需求—设计—分析—方案—任务追踪时；不用于单轮修改、简单清单、一次性诊断，也不因任务较复杂而自动创建任务表。
---

# Task Table Manager

质量优先；质量等价时减少含返工在内的总 Token；前两者等价时再提速。

## 路由

- 只用于跨轮、存在真实依赖或需要持久完成审计的工作。普通修改、一次性分析和简单清单不用。
- 新计划放在 `docs/plan/<YYYYMMDD>_<NAME>/`；同计划文件以该目录为根。只有用户要求才移入 `old/`。
- 有 `plan.json` 时走 v1；创建或修改读 `references/create-plan.md`。只有 Markdown 的旧计划按需读 `references/writing.md` 或 `references/execution.md`，不得静默迁移。
- 工具入口是 `<SkillDir>/scripts/taskctl.py`。每次显式传绝对 `--task-dir`；源码范围另传 `--project-root`，状态和临时输出不得写入 skill 目录。

## 质量边界

- CLI 只判断它能确定的结构、依赖、revision、来源指纹和证据新鲜度；不得把这些结果解释为需求正确、方案无偏移、测试 oracle 正确或业务已经可用。`audit-plan` 只是结构审计。
- 计划前直接以用户要求、正式设计、完整实现差距和方案为真源，先正向检查上游是否全部覆盖，再反向检查每个动作是否有来源，并主动寻找反例。发现问题回到最早失效层；不得由任务、旧测试或现有代码反推上游，也不得用自动生成的追踪表自证。
- 任务只表达未交付的用户结果、真实依赖和最小充分验收。大量 command/资产的逐项分配由任务目录内的定向脚本或清单检查，不把领域 inventory 逻辑塞入通用 CLI。
- 测试先确认 requirement、oracle、baseline、negative path、真实 subject 和 readback；不为旧断言修改目标设计。outcome 只到证据实际穿过的最高入口，mock、recording、注册、编译或内部 runtime 不能冒充公开可用。

## v1 热路径

- 执行、继续或完成计划前必须有对应 active goal；用户发出这类请求即授权创建。Goal 只保存交付结果、绝对任务目录、范围边界和最终条件。
- Agent 层正常路径是 `resume → begin → close`。`resume` 是唯一恢复入口，不全文读取计划、状态或生成表；`begin` 只组合职责、生命周期、持久化、构建和回退边界已经确认相同的工作；`close` 导入机器证据并返回完成卡和剩余缺口。
- `resume` 的 `ready_count` 与 `needs_review_count` 只统计依赖检查后可执行的任务，依赖阻断项单列在 `dependency_blocked_ids`；`render.status_counts` 与 `TASK_TABLE.md` totals 统计全部任务并固定包含零值，二者不得混作同一口径。
- `evidence-context`、`seal-red`、`impact` 等只在当前 runner 或异常恢复确实需要时同轮调用，不创建任务、handoff 或额外对话轮次。依赖任务必须整体 `done`；依赖边 claims 只表示下游消费的证据与 freshness，不是提前开工许可。
- 只有真实中断、阻塞或下一动作无法恢复时 `checkpoint`。合同变化先释放活动包、更新最早上游、审计候选并 `amend`；禁止直接改活动 `plan.json/state.json`。
- 最终运行 `audit --all`。只有计划来源仍有效、必要任务和 flow 都有直接证据并返回 completion receipt，才可报告完成或结束 goal。

## Token 与推理深度

- 成功证据只读摘要，失败才展开 raw artifact。普通 v1 不写 handoff、memo、`deps_for`、逐轮 Token 报告或重复 changelog；`TASK_TABLE.md` 仅按需生成，且只是只读投影，不代表执行校验通过。
- 推理深度不属于计划状态或完成证据。执行 active Goal 时遵守全局动态判断并使用 `$reasoning-governor`；任务行深度仅是开始当前项时的非权威建议，不限制后续根据真实工作变化升降。
