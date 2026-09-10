---
name: codex-event-logger
description: 有界读取 Codex 对话记录。用于压缩后恢复当前轮、按用户要求追溯历史或审查子代理创建、复用与等待行为；初次了解项目且确需历史脉络时查看输入输出、活跃 goal 和文件操作。当前上下文充分且用户未要求追溯或审计时不使用。
---

# 用法

- `conversation.json` 与 `file-operations.jsonl` 是 Hook 持有的项目恢复记录，模型不直接读写；前者保留选定输入、最终回复和 goal，后者只含已识别的文件操作，均非完整行为审计。内置脚本提供一次有界读取的消费者视图。
- 压缩后恢复：用内置只读脚本查看当前对话最新 turn。默认 model 视图仅保留当前动作所需的 prompt、最终回复、活跃 goal、文件净操作路径/行区间和异常恢复信息；工作目录只显示一次，其内路径用相对形式，同路径重复修改合并，本轮创建后删除的临时文件不显示。
- 追溯历史：先有界列出用户指定会话的 turn，再读取选中的一个 turn。
- 初次了解项目：仅在用户需要历史脉络时逐个会话有界查询，不递归倾倒整个 `codexRuntimeLogFile`。
- 需要统计子代理或审查等待、复用、重复动作时，读取 [session-audit.md](references/session-audit.md)，按指定原生会话文件取证；普通恢复不附带审计。原生记录已有的事件不重复写入项目日志，也不为审计创建或唤醒代理。

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

默认 model 视图采用紧凑、低标点格式和 2,048 Token 预算；不足时按语义优先保留 turn 身份、异常、goal、对话摘要和最近文件路径，并返回同一 turn 的恢复方式。程序、测试或审计确需完整结构时显式加 `--view machine`，保留原有有界 JSON 字段和格式。模型需要更多正文时提高 `--model-token-budget`，不得直接展开原始日志或让完整机器 JSON 自动进入上下文。

脚本先检查文件大小，再做一次权威有界读取：默认拒绝展开超过 256 KiB 的 `conversation.json`；`file-operations.jsonl` 只读末尾 256 KiB、最多 80 条，单行最多 32 KiB，机器事实的单个字符串最多 12,000 字符。model 与 machine 视图共享这次读取；调整时仍限于脚本允许的参数范围。

运行时默认保留 90 天、最多 200 个会话且每个会话最多 500 个 turn；工作区可在 `.codex\event-logger-settings.json` 中调整，但脚本硬限制为 3650 天、5000 个会话和每会话 10000 个 turn。清理只作用于项目内配置的日志根目录，不跟随符号链接或 Windows reparse point，并始终保留当前会话。

如果 `$env:CODEX_THREAD_ID` 为空，先从当前 hook payload、`/status` 或用户提供的信息取得 thread ID；不要靠无界扫描猜测当前会话。

## 记录边界

Hook 记录由脚本维护，用于恢复本轮目标和修改位置；模型只消费投影，不得把派生摘要当成任务或验收真源。既有记录无需迁移；清理后依靠仍存的原生会话和项目正式文档恢复，不能重建的部分报告缺失。

文本默认最多保留 12,000 字符，历史记录不保证带完整性元数据；不存在、截断或未被工具识别的操作不等于未发生。PowerShell 文件操作来自指定命令形式的识别，不是文件系统审计。读取端的 `missing`、`too_large`、局部尾读和输出预算提示均须保留在结论边界内。

`tool_operation`、`auto_or_goal_turn` 等临时来源标签不能反证用户输入；补读找到用户或 goal 输入后，以已确认来源替换临时标签并保留已记录的明确输入。Stop 时来源暂不可读，可在下一次工具补读再试一次；仍缺失则报告边界，不随工具次数重复扫描。

正常用户提交不提前扫描最终回复；工具事件只在首次缺少输入时补读，随后复用已有恢复字段，Stop 再按缺口补入最终回复。原生 transcript 只有明确 `phase=final` 的消息能补入最终回复；旧记录无法仅凭字段名补证该消息的阶段。首次工具补读尚未得到输入时，其后工具不反复扫描，Stop 仍可补读；运行中需要更完整事实时用原生会话审计入口。
