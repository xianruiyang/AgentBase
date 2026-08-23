---
name: reasoning-governor
description: 读取或切换当前 Codex 线程的 next-turn 推理深度。用于用户当次明确要求查看、设置、固定、改变、重评或解除档位，或当前工作已按全局规则确认一个可预期长期阶段的目标档位且配置证据会改变后续动作时；只负责线程状态与设置机制，不重新裁决任务复杂度。用户已经固定并确认设置、当前只要求保持该档位继续任务时不使用；已有有效读回且与目标档位一致、只遇到孤立难题或进入短机械收尾时也不使用；只讨论概念或设计而不读取、修改线程时不使用。
---

# Reasoning Governor

只管理当前线程的 next-turn 推理深度。用户明确要求重评时在此完成目标判断；其他目标档位在调用前按全局规则形成，复杂执行由 `$execution-governor` 裁决。本 skill 只负责状态读回、设置和生命周期边界，不重复规划当前工作。脚本负责读写和验证，Goal 只在本来需要跨轮执行时承载续轮。不要把推理深度、切换原因或脚本 receipt 写入任务表、完成证据或其他持久状态。

## 权威与边界

- 以脚本从 Codex conversation state 读回的 `currentConfiguredEffort` 作为当前线程 next-turn 配置证据。当前有效上下文中同一线程、此后无设置或已知配置变化的最近验证读回可以继续使用；否则不从全局 `config.toml`、任务行、模型记忆或历史 receipt 推断。
- 设置只影响下一轮，不能改变或读取已经开始的当前轮；`activeTurnEffortReadable=false` 是明确边界。
- 显式状态与设置入口不使用 `Stop` hook，不发送消息，不创建 turn，也不为切换深度创建或结束 Goal。`SessionStart` hook 只把同一权威读回投影为额外 developer context，不选择或设置档位。
- 不把临时基线、用户覆盖或自动恢复义务保存到任务表、Goal、hook、文件或脚本状态。Hook 的有限本地缓存只记录按线程哈希的最近已投影 `(model, effort)`，用于抑制相同 `resume`；它可丢弃、不可反向推断档位，也不影响 `startup`、`clear` 或 `compact` 的必发读回。
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

1. 用户明确要求读取、设置、固定、改变或解除档位时，按其等级与范围执行并读回；固定范围仍有效时不做自主升降。用户给出期限时在期限结束后才恢复动态控制，未给期限时不得自行宣布解除。
2. 没有用户覆盖时，只接受调用前已形成的目标档位、阶段持续边界和“当前配置会改变后续动作”判断；复杂执行由 `$execution-governor` 裁决，稳定工作由模型按全局规则直接裁决。领域 skill、计划、任务提示、Goal 或本 skill 不重新推断任务复杂度；目标或持续边界仍未裁决时返回调用方，不为使用工具自行猜测。
3. 目标档位使用当前宿主支持的最低充分等级，可直接升降，不逐级试探。`max` 可以被执行控制选择，不因成本默认排除，也不因可用默认采用。
4. 当前没有仍有效的验证读回时运行 `-Status`；已有同一线程且此后无变化的读回时复用。实际档位与目标相同时继续当前工作，不调用设置；首次自主改变前，只在当前对话保留该次验证档位作为临时基线证据。
5. 用户明确设置时直接执行；其他设置必须由调用方已经证明后继阶段可预期长期保持不同判断负担，且质量或总体成本收益足以覆盖结束当前轮、无 Goal 时等待自然续轮及以后恢复的成本。孤立难题和短机械收尾不承担转换；复杂执行由 `$execution-governor` 作出该判断，稳定工作由模型按全局内核作出；本 skill 不用更低档位或延迟设置改写它。
6. 设置成功后立即结束当前轮：已有 Goal 时由它进入下一轮，没有 Goal 时等待下一次自然用户消息。Goal 不是设置前提，也不保存档位或恢复状态；不要为了让设置生效而创建临时 Goal。next-turn 设置不能改变已经开始的当前轮，也不能被表述成当前动作已提高档位。
7. 自主档位只服务触发切换的当前工作；工作闭合后由原调用方决定是否恢复已验证临时基线，或为紧邻下一段工作重新形成目标档位。基线证据丢失或含糊时不得猜测、声称已恢复或写入持久状态。

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
