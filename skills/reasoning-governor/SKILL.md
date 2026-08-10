---
name: reasoning-governor
description: 动态读取和切换当前 Codex 线程的 next-turn 推理深度。用于用户明确要求查看或修改当前线程深度，或 active Goal 执行中下一段工作的真实不确定性、后果、可逆性或验证负担发生实质变化，需要在继续前升降 reasoning effort 时；没有 active Goal 时不用于模型自主切换，也不创建 Goal、任务表、hook、持久状态或自动恢复等级。
---

# Reasoning Governor

只管理当前线程的 next-turn 推理深度；把 Goal 作为自主切换后的唯一续跑承载。不要把深度、切换原因或脚本 receipt 写入任务表、完成证据或其他持久状态。

## 权威与边界

- 以脚本从 Codex conversation state 读回的 `currentConfiguredEffort` 作为当前线程 next-turn 配置证据，不从全局 `config.toml`、任务行、模型记忆或旧 receipt 推断。
- 设置只影响下一轮，不能改变或读取已经开始的当前轮；`activeTurnEffortReadable=false` 是明确边界。
- 不使用 `Stop` hook，不发送消息，不创建 turn，不创建或结束 Goal，也不保存 pending、previous effort 或自动恢复状态。
- 用户固定了深度时保持其选择，除非用户随后明确改动。

## 动态判断

1. 当新证据使下一段工作的真实不确定性、后果、可逆性或验证负担发生实质变化时重新判断，不限于任务、计划或工作包的开始边界。
2. 选择下一段工作的最低充分等级，可直接升降，不逐级试探。`max` 可用于最困难且质量优先的工作，不把它设为不可达，也不因可用而默认选择最高等级。
3. 先运行 `-Status`。目标等级与 `currentConfiguredEffort` 相同时继续当前工作，不调用设置。
4. 用户明确要求设置时可直接执行；没有 active Goal 时，新配置等待下一次自然用户消息或后续 Goal 生效，不承诺自动续跑。
5. 模型自主切换时，只在目标等级不同后检查 Goal。没有 active Goal 就保持当前配置继续，不为切换深度创建 Goal，也不把新配置遗留给无关的未来请求。
6. 有 active Goal 时执行设置；读回成功后立即结束当前轮，由 Goal 进入下一轮。下一轮针对新的下一段工作重新判断，不机械恢复旧等级。

## 命令

使用 skill 自带 PowerShell 入口；显式传入 thread id 能避免在非 Codex 子进程环境中解析错误线程：

```powershell
& '<SkillDir>\scripts\reasoning-governor.ps1' -Status -ThreadId $env:CODEX_THREAD_ID
& '<SkillDir>\scripts\reasoning-governor.ps1' -Effort max -ThreadId $env:CODEX_THREAD_ID
```

Node 入口同时支持机器调用和旧设置形式：

```text
node <SkillDir>/scripts/reasoning-governor.mjs status --thread-id <id>
node <SkillDir>/scripts/reasoning-governor.mjs set --effort max --thread-id <id>
node <SkillDir>/scripts/reasoning-governor.mjs --effort max --thread-id <id>
```

支持 `low`、`medium`、`high`、`xhigh`、`max`、`ultra`；具体模型或宿主拒绝某等级时按失败处理，不用其他等级冒充成功。

## 成功与失败

- `status` 只有 `ok=true`、`readbackVerified=true` 才证明读到了 next-turn 配置。
- `set` 只有 `ok=true`、`updateAccepted=true`、`readbackVerified=true`、`matchesRequestedEffort=true` 且 `currentConfiguredEffort` 等于请求值，才证明 next-turn 配置一致。
- 失败时保留原完成判断，不声称已切换；根据错误决定重试一次、保持当前等级继续，或向用户报告宿主能力限制。输入、实现和环境未变化时不重复调用期待不同结果。
