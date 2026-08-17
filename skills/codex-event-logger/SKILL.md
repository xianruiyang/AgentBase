---
name: codex-event-logger
description: 有界读取 Codex 项目级对话记录。用于上下文压缩后恢复当前轮、按用户要求追溯历史，或初次了解项目时查看历史输入输出、活跃 goal 和文件操作；当前上下文充分且用户未要求追溯时不使用。
---

# 用法

- `conversation.json` 与 `file-operations.jsonl` 是 hook 持有的完整机器日志，模型不直接读取或修改；内置脚本对一次有界读取事实提供消费者视图。
- 压缩后恢复：用内置只读脚本查看当前对话最新 turn。默认 model 视图只保留恢复当前动作所需的 prompt、最终回复、活跃 goal、文件净操作路径/行区间和异常恢复信息；工作目录作为一次公共基准、其内路径改用相对表示，同一路径的重复修改合并，本轮创建后删除的临时文件不进入模型面。
- 追溯历史：先有界列出用户指定会话的 turn，再读取选中的一个 turn。
- 初次了解项目：只在用户需要历史脉络时，逐个会话做有界查询；不要递归倾倒整个 `codexRuntimeLogFile`。

## 有界读取

读取当前对话最新 turn：

```powershell
$SkillDir = '<skill_dir>'
python.exe (Join-Path $SkillDir 'scripts\read_codex_turn_log.py') --project-root (Get-Location).Path --thread-id $env:CODEX_THREAD_ID
```

追溯同一会话时，先列出最多 20 个候选，再读取一个明确的目录名：

```powershell
$SkillDir = '<skill_dir>'
python.exe (Join-Path $SkillDir 'scripts\read_codex_turn_log.py') --project-root (Get-Location).Path --thread-id $env:CODEX_THREAD_ID --list-turns 20
python.exe (Join-Path $SkillDir 'scripts\read_codex_turn_log.py') --project-root (Get-Location).Path --thread-id $env:CODEX_THREAD_ID --turn-name "YYYYMMDD_HHMMSS_mmm__turnId"
```

`<skill_dir>` 由当前 skill 目录定位，不假定 Codex home 位于特定用户路径。

默认 model 视图使用紧凑、低标点的模型可读格式和 2,048 Token 预算；预算不足时按语义优先保留 turn 身份、异常、goal、对话摘要和最近文件路径，并返回同一 turn 的恢复方式。确需完整结构的程序、测试或审计显式增加 `--view machine`；该视图保持原有有界 JSON 字段和格式。模型需要更多正文时提高 `--model-token-budget`，不得为了省事直接展开原始日志或让完整机器 JSON 自动进入上下文。

脚本只做一次权威有界读取：先检查文件大小；默认拒绝展开超过 256 KiB 的 `conversation.json`，对 `file-operations.jsonl` 只读取末尾 256 KiB、最多 80 条记录，单行最多 32 KiB，机器事实中的单个字符串最多 12,000 字符。model 与 machine 视图都从这次读取生成；确需调整时仍使用脚本允许的有限参数范围。

运行时默认保留 90 天、最多 200 个会话且每个会话最多 500 个 turn；工作区可在 `.codex\event-logger-settings.json` 中调整，但脚本硬限制为 3650 天、5000 个会话和每会话 10000 个 turn。清理只作用于项目内配置的日志根目录，不跟随符号链接或 Windows reparse point，并始终保留当前会话。

如果 `$env:CODEX_THREAD_ID` 为空，先从当前 hook payload、`/status` 或用户提供的信息取得 thread ID；不要靠无界扫描猜测当前会话。
