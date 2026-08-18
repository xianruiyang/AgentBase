---
name: reasoning-governor
description: 读取或切换当前 Codex 线程的 next-turn 推理深度。用于用户明确要求查看、设置或固定当前档位，或用户未固定且下一段实质工作的判断负担使档位错配可能实质影响质量或总体成本时；判断独立于领域 skill、计划和 Goal，无 active Goal 仍可触发。用户未显式要求线程操作时，短小且可在当前轮可靠闭合的任务不使用；只讨论概念或设计而不读取、修改线程时也不使用。
---

# Reasoning Governor

只管理当前线程的 next-turn 推理深度。目标档位判断、状态读回、设置、下一轮生效与自动续轮是不同机制：模型负责目标与成本判断，脚本负责读写和验证，Goal 只在本来需要跨轮执行时承载续轮。不要把推理深度、切换原因或脚本 receipt 写入任务表、完成证据或其他持久状态。

## 权威与边界

- 以脚本从 Codex conversation state 读回的 `currentConfiguredEffort` 作为当前线程 next-turn 配置证据。当前有效上下文中同一线程、此后无设置或已知配置变化的最近验证读回可以继续使用；否则不从全局 `config.toml`、任务行、模型记忆或历史 receipt 推断。
- 设置只影响下一轮，不能改变或读取已经开始的当前轮；`activeTurnEffortReadable=false` 是明确边界。
- 不使用 `Stop` hook，不发送消息，不创建 turn，也不为切换深度创建或结束 Goal；不把临时基线、用户覆盖或自动恢复义务保存到任务表、Goal、hook、文件或脚本状态。
- 用户明确指定等级与适用范围时先按其选择执行；未声明结束条件则持续到用户明确改变或解除。额度原因无需验证，模型不得以自主判断或 Goal 状态覆盖；等级不可用或任务在该约束下无法可靠完成时如实说明。

## 动态判断

1. 先确认用户是否明确要求读取、设置或固定档位及其范围；按用户要求执行并读回，固定范围仍有效时不做自主升降。用户给出期限时在期限结束后恢复动态判断，未给期限时不得自行宣布解除。
2. 没有用户覆盖时，在下一段实质工作开始前先独立判断目标档位；领域 skill、计划、Goal 和当前配置只提供事实或续轮能力，不替代该判断。新证据使不确定性、后果、可逆性或验证负担实质变化时重新判断，不限于任务或阶段边界。
3. 选择下一段工作的最低充分档位，可直接升降，不逐级试探。`max` 可用于最困难且质量优先的工作，不把它设为不可达，也不因可用而默认选择最高档位。
4. 先判断精确状态能否改变动作。短小、可逆、验证明确且能在已经开始的当前轮可靠闭合，或档位错配不会实质影响质量或总体成本时，沿用当前档位且不运行 `-Status`。
5. 状态会改变动作且当前没有仍有效的验证读回时运行 `-Status`；已有有效读回时复用。实际档位与目标相同时继续当前工作，不调用设置；首次自主改变前，把该次验证档位只作为当前对话中的临时基线证据。
6. 实际档位与目标不同时，比较剩余工作的质量或成本收益与设置、结束当前轮、无 Goal 时等待自然续轮及以后恢复的总成本。质量不足时不得为省切换成本继续；质量已充分且剩余工作不能摊销转换时沿用当前档位。只有净收益成立才设置并读回，不要求 active Goal，也不另行请求用户授权。
7. 设置成功后立即结束当前轮：已有 Goal 时由它进入下一轮，没有 Goal 时等待下一次自然用户消息。Goal 不是设置前提，也不保存档位或恢复状态；不要为了让设置生效而创建临时 Goal。
8. 自主档位只服务触发切换的当前工作。该工作闭合时恢复已验证临时基线；若紧邻下一段工作已知且判断负担不同，可直接判断其目标与转换收益。基线证据已经丢失或含糊时不得猜测或声称已恢复，应在下一段已知工作上重新判断。

## 命令

使用 skill 自带 PowerShell 入口；显式传入 thread id 能避免在非 Codex 子进程环境中解析错误线程：

```powershell
& '<SkillDir>\scripts\reasoning-governor.ps1' -Status -ThreadId $env:CODEX_THREAD_ID
& '<SkillDir>\scripts\reasoning-governor.ps1' -Effort max -ThreadId $env:CODEX_THREAD_ID
& '<SkillDir>\scripts\reasoning-governor.ps1' -Status -View machine -ThreadId $env:CODEX_THREAD_ID
```

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
