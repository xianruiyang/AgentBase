---
name: codex-event-logger
description: 读取 Codex 项目级对话运行记录；用于上下文压缩后恢复当前轮状态、按用户需求追溯历史对话，或初次了解项目时查看历史输入输出、活跃 goal 与文件操作记录；当前上下文充分且用户未要求追溯时不使用。
---

# 用法

- 压缩后恢复：查看当前对话最新 turn 的 `conversation.json` 和 `file-operations.jsonl`，确认当前轮输入、输出、goal 和文件操作。
- 追溯历史：按用户指定的时间、会话或任务，在 `codexRuntimeLogFile` 中查找旧 turn 记录。
- 初次了解项目：浏览项目根目录下的 `codexRuntimeLogFile`，快速了解历史对话、活跃 goal 和文件变更脉络。

## 压缩后快速定位

直接获取当前对话最新 turn 路径：

```powershell
$turnPath = (Get-ChildItem -LiteralPath (Join-Path (Get-Location).Path "codexRuntimeLogFile\$env:CODEX_THREAD_ID") -Directory | Where-Object { $_.Name -match '^\d{8}_\d{6}_\d{3}__' } | Sort-Object Name -Descending | Select-Object -First 1).FullName; $turnPath
```

读取记录：

```powershell
Get-Content -LiteralPath (Join-Path $turnPath 'conversation.json') -Raw
Get-Content -LiteralPath (Join-Path $turnPath 'file-operations.jsonl') -Raw
```

如果 `$env:CODEX_THREAD_ID` 为空，先读取当前 hook payload、`/status` 显示的 thread ID，或从 `codexRuntimeLogFile` 下按最近修改时间定位。
