---
name: reasoning-governor
description: 按用户当次明确要求读取、设置、固定、改变、重评或解除当前 Codex 线程的 next-turn 推理深度，并读回结果。用户未明确要求操作线程设置、已经固定并只要求继续、或只讨论推理深度概念与设计时不使用；不得自主查询、选择或改变档位。
---

# Reasoning Governor

只按用户明确请求管理当前线程的 next-turn 推理深度；不根据任务复杂度、成本、Goal、计划或其他 skill 自主查询、选择、升降或恢复档位。本 skill 只负责状态读回、设置和生命周期边界，不重复规划当前工作。脚本负责读写和验证。不要把推理深度或脚本 receipt 写入任务表、完成证据或其他持久状态。

## 权威与边界

- 以脚本从 Codex conversation state 读回的 `currentConfiguredEffort` 作为当前线程 next-turn 配置证据。当前有效上下文中同一线程、此后无设置或已知配置变化的最近验证读回可以继续使用；否则不从全局 `config.toml`、任务行、模型记忆或历史 receipt 推断。
- 设置只影响下一轮，不能改变或读取已经开始的当前轮；`activeTurnEffortReadable=false` 是明确边界。
- 显式状态与设置入口不使用 `Stop` hook，不发送消息，不创建 turn，也不为切换深度创建或结束 Goal。`SessionStart` hook 只把同一权威读回投影为额外 developer context，不选择或设置档位。
- 不把用户选择或恢复义务保存到任务表、Goal、hook、文件或脚本状态。Hook 的有限本地缓存只记录按线程哈希的最近已投影 `(model, effort)`，用于抑制相同 `resume`；它可丢弃、不可反向推断档位，也不影响 `startup`、`clear` 或 `compact` 的必发读回。
- 用户明确指定等级与适用范围时先按其选择执行；未声明结束条件则持续到用户明确改变或解除。额度原因无需验证，模型不得以自主判断或 Goal 状态覆盖；等级不可用或任务在该约束下无法可靠完成时如实说明。

## SessionStart 状态投影

可移植 Hook 在 `startup`、`resume`、`clear` 和 `compact` 调用同目录脚本。每次先读真实线程状态；新上下文和压缩后始终注入，相同线程的未变化 `resume` 静默。缺少缓存表示未见过，不使用真实等级 `none` 充当初值；读回失败不覆盖最近成功记录、不猜默认值、不重试。

成功与失败只向模型输出一行，不显示用户警告：

```text
reasoning_effort=medium; observed, not target/user-lock.
reasoning_effort=?; do not infer.
```

第一行只证明当前 next-turn 配置，不是目标档位或用户固定要求；第二行只证明当前无法读回。Hook 缓存删除或损坏最多造成一次重复投影，不影响真实配置。

## 调用与生命周期

1. 用户明确要求读取当前档位时运行 `-Status`；明确要求设置、固定、改变、重评或解除时，按其指定等级与范围执行并读回。重评但未指定等级时，根据用户当次要求给出的目标与约束选择，不把选择扩大为以后可自主调整的权限。
2. 用户给出适用期限时按期限保持；未声明结束条件则持续到用户明确改变或解除。用户未明确要求时不调用状态或设置入口，不因任务难度、成本、Goal 状态或后继工作自行升降或恢复。
3. 设置只影响下一轮。设置成功后如实说明生效边界并结束当前轮，不创建临时 Goal、消息或其他机制强制进入下一轮，也不表述成当前轮已经改变。

## 命令

使用 skill 自带 PowerShell 入口；显式传入 thread id 能避免在非 Codex 子进程环境中解析错误线程：

```powershell
& '<SkillDir>\scripts\reasoning-governor.ps1' -Status -ThreadId $env:CODEX_THREAD_ID
& '<SkillDir>\scripts\reasoning-governor.ps1' -Effort max -ThreadId $env:CODEX_THREAD_ID
& '<SkillDir>\scripts\reasoning-governor.ps1' -Status -View machine -ThreadId $env:CODEX_THREAD_ID
```

`-Hook` 只供已安装的 `SessionStart` 生命周期入口使用，直接消费 Codex 传入的 stdin JSON；模型不手工调用它。

Node 入口同时支持机器调用和旧设置形式：

```text
node <SkillDir>/scripts/reasoning-governor.mjs status --thread-id <id>
node <SkillDir>/scripts/reasoning-governor.mjs set --effort max --thread-id <id>
node <SkillDir>/scripts/reasoning-governor.mjs status --view machine --thread-id <id>
```

支持 `low`、`medium`、`high`、`xhigh`、`max`、`ultra`；具体模型或宿主拒绝某等级时按失败处理，不用其他等级冒充成功。

默认模型视图是单行紧凑回执，例如 `{ok:true op:status effort:max}`；`--view machine` 返回完整 JSON 诊断。旧的 `node ... --effort max` 设置形式继续可用，但不作为新调用入口。

## 成功与失败

- 默认视图只有 `ok:true` 和实际 `effort` 才表示 canonical 读回已满足对应操作的完整成功条件；不能从命令退出码或请求值单独推断成功。
- machine `status` 只有 `ok=true`、`readbackVerified=true` 才证明读到了 next-turn 配置。
- machine `set` 只有 `ok=true`、`updateAccepted=true`、`readbackVerified=true`、`matchesRequestedEffort=true` 且 `currentConfiguredEffort` 等于请求值，才证明 next-turn 配置一致。
- 失败时保留原完成判断，不声称已切换；根据错误决定重试一次、保持当前等级继续，或向用户报告宿主能力限制。输入、实现和环境未变化时不重复调用期待不同结果。
