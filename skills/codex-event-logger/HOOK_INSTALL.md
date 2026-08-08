# Codex Event Logger Hook 配置说明

## 文件位置

脚本本体位于：

```text
<skill>\scripts\codex_event_logger.ps1
<skill>\scripts\codex_event_logger.py
```

默认配置位于：

```text
<skill>\event-logger-settings.json
```

项目级覆盖配置可选：

```text
<project_root>\.codex\event-logger-settings.json
```

## 输出结构

日志写入触发 hook 的项目根目录：

```text
<project_root>\codexRuntimeLogFile\<sessionId>\<YYYYMMDD_HHMMSS_mmm__turnId>\
  conversation.json
  file-operations.jsonl
```

同一 `sessionId` 下维护索引：

```text
<project_root>\codexRuntimeLogFile\<sessionId>\.turn-index.json
```

如果当前会话存在激活 goal，`conversation.json` 会写入单个 `goal` 对象。默认从以下数据库读取：

```text
C:\Users\gzxt\.codex\goals_1.sqlite
```

如需覆盖数据库路径，在项目级配置中设置 `goal_db_path`。

`conversation.json` 只保留恢复对话所需字段：

```json
{
  "source": "user_prompt | transcript_user_prompt | goal | auto_or_goal_turn | tool_operation",
  "prompt_ts": "...",
  "stop_ts": "...",
  "prompt": "...",
  "last_assistant_message": "...",
  "goal": {}
}
```

字段为空时不写入。`sessionId` 与 `turnId` 已体现在目录路径中，不重复写入文件。

## hooks.json 配置

全局配置文件：

```text
C:\Users\gzxt\.codex\hooks.json
```

将下面四个事件加入 `hooks`。如果已有同名事件，保留原有 hook。`Stop` 事件中建议把本 logger 放在 QQ/通知类 hook 前，避免通知 hook 失败或超时影响记录。

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "commandWindows": "powershell -NoProfile -ExecutionPolicy Bypass -File \"<skill>\\scripts\\codex_event_logger.ps1\"",
            "timeout": 10
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "commandWindows": "powershell -NoProfile -ExecutionPolicy Bypass -File \"<skill>\\scripts\\codex_event_logger.ps1\"",
            "timeout": 10
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "commandWindows": "powershell -NoProfile -ExecutionPolicy Bypass -File \"<skill>\\scripts\\codex_event_logger.ps1\"",
            "timeout": 10
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "commandWindows": "powershell -NoProfile -ExecutionPolicy Bypass -File \"<skill>\\scripts\\codex_event_logger.ps1\"",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

安装后在 Codex 的 `/hooks` 面板信任新增 command hook。

## 验证

发送一条普通消息后检查：

```text
<project_root>\codexRuntimeLogFile\<sessionId>\<YYYYMMDD_HHMMSS_mmm__turnId>\conversation.json
<project_root>\codexRuntimeLogFile\<sessionId>\<YYYYMMDD_HHMMSS_mmm__turnId>\file-operations.jsonl
```

执行一次 `apply_patch` 文件修改后检查 `file-operations.jsonl` 是否追加合法 JSON 行，并包含 `line_ranges`。

如果当前对话存在激活 goal，检查 `conversation.json` 中是否存在单个 `goal` 对象；同一轮多次 hook 不应产生重复 goal 记录。
