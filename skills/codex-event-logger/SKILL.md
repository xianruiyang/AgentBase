---
name: codex-event-logger
description: 有界读取 Codex 项目级对话运行记录；用于上下文压缩后恢复当前轮状态、按用户需求追溯历史对话，或初次了解项目时查看历史输入输出、活跃 goal 与文件操作记录；当前上下文充分且用户未要求追溯时不使用。
---

# 用法

- 压缩后恢复：用内置只读脚本查看当前对话最新 turn 的对话、goal 和文件操作摘要。
- 追溯历史：先有界列出用户指定会话的 turn，再读取选中的一个 turn。
- 初次了解项目：只在用户需要历史脉络时，逐个会话做有界查询；不要递归倾倒整个 `codexRuntimeLogFile`。

## 有界读取

读取当前对话最新 turn：

```powershell
python.exe "$env:USERPROFILE\.codex\skills\codex-event-logger\scripts\read_codex_turn_log.py" --project-root (Get-Location).Path --thread-id $env:CODEX_THREAD_ID
```

追溯同一会话时，先列出最多 20 个候选，再读取一个明确的目录名：

```powershell
python.exe "$env:USERPROFILE\.codex\skills\codex-event-logger\scripts\read_codex_turn_log.py" --project-root (Get-Location).Path --thread-id $env:CODEX_THREAD_ID --list-turns 20
python.exe "$env:USERPROFILE\.codex\skills\codex-event-logger\scripts\read_codex_turn_log.py" --project-root (Get-Location).Path --thread-id $env:CODEX_THREAD_ID --turn-name "YYYYMMDD_HHMMSS_mmm__turnId"
```

脚本先读取文件大小；默认拒绝展开超过 256 KiB 的 `conversation.json`，对 `file-operations.jsonl` 只读取末尾 256 KiB、最多 80 条记录，单行最多 32 KiB，所有字符串最多输出 12,000 字符。不要绕过这些上限直接完整读取日志原文；确需调整时仍使用脚本允许的有限参数范围。

如果 `$env:CODEX_THREAD_ID` 为空，先从当前 hook payload、`/status` 或用户提供的信息取得 thread ID；不要靠无界扫描猜测当前会话。
