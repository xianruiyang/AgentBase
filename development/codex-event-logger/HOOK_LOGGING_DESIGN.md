# Codex 记录 Hook 组设计方案

## 目标

设计一组 Codex hook，用于记录对话流水、文件操作流水和会话状态变化。

核心要求：

- 不依赖隐藏思考链。
- 不发送额外消息。
- 不触发额外对话。
- 不写入 `AGENTS.md`。
- 不把 transcript 文件格式当成稳定 API。
- 支持 goal 自动续跑时可能没有 `UserPromptSubmit` 的情况。
- 脚本本体放在 skill 中，输出写入各项目根目录。
- 每个 turn 目录名包含创建时间和 `turnId`，便于按时间排序。
- 每个 turn 目录固定包含 `conversation.json` 和 `file-operations.jsonl` 两个文件。

## 官方可依赖边界

Codex command hook 会从 `stdin` 收到事件 JSON。不同事件字段不同。

官方文档：

- https://developers.openai.com/codex/hooks
- https://raw.githubusercontent.com/openai/codex/main/codex-rs/hooks/schema/generated/user-prompt-submit.command.input.schema.json
- https://raw.githubusercontent.com/openai/codex/main/codex-rs/hooks/schema/generated/stop.command.input.schema.json
- https://raw.githubusercontent.com/openai/codex/main/codex-rs/hooks/schema/generated/post-tool-use.command.input.schema.json

可稳定使用的关联字段：

| 字段 | 含义 |
|---|---|
| `session_id` | 当前会话标识 |
| `turn_id` | 当前轮次标识 |
| `cwd` | hook 执行时的工作目录 |
| `hook_event_name` | 事件名 |
| `model` | 当前模型 |
| `permission_mode` | 当前权限模式，部分事件没有 |
| `transcript_path` | transcript 路径，可能为 `null` |

关联一轮对话使用：

```text
key = session_id + ":" + turn_id
```

注意：已有脚本里可能使用 `thread_id` 作为业务对话 ID，但官方 hook schema 的主字段是 `session_id`。

## 推荐 Hook 组

| 事件 | 是否必须 | 作用 |
|---|---:|---|
| `UserPromptSubmit` | 是 | 记录用户主动提交的输入 |
| `Stop` | 是 | 记录每轮结束和最终助手回复 |
| `PreToolUse` | 是 | 对 `apply_patch` 目标文件保存临时前置快照，用于计算行号区间 |
| `PostToolUse` | 是 | 从工具调用中提取明确文件操作，并为 `apply_patch` 生成行号区间 |
| `SessionStart` | 可选 | 记录会话启动、恢复、清空、压缩恢复 |
| `PreCompact` / `PostCompact` | 可选 | 记录上下文压缩 |
| `PermissionRequest` | 可选 | 记录权限请求 |
| `SubagentStart` / `SubagentStop` | 可选 | 记录子代理生命周期 |

最小可用版本只需要：

```text
UserPromptSubmit + Stop + PreToolUse + PostToolUse
```

## 事件记录格式

脚本本体放在 skill 中，输出落到当前项目根目录。每个项目根目录下建立一个 `codexRuntimeLogFile`，先按 `sessionId` 分文件夹，再按“创建时间 + turnId”分文件夹。

输出目录：

```text
<project_root>\codexRuntimeLogFile\<sessionId>\<YYYYMMDD_HHMMSS_mmm__turnId>\
```

每个 `turnId` 文件夹只包含两类核心记录文件：

```text
conversation.json
file-operations.jsonl
```

示例：

```text
D:\program\RealSimpleChat\codexRuntimeLogFile\019f16b6-de21-7ab2-aaa9-afdd8b0fc176\20260704_013012_123__turn_abc\
  conversation.json
  file-operations.jsonl
```

`sessionId` 目录下额外维护一个索引文件，用于保证同一 `turn_id` 的多个 hook 事件写入同一个带时间目录：

```text
<project_root>\codexRuntimeLogFile\<sessionId>\.turn-index.json
```

示例：

```json
{
  "turn_abc": "20260704_013012_123__turn_abc"
}
```

### UserPromptSubmit

用于记录用户主动输入，写入或更新本轮的 `conversation.json`。

```json
{
  "session_id": "...",
  "turn_id": "...",
  "cwd": "D:\\program\\RealSimpleChat",
  "model": "...",
  "permission_mode": "...",
  "transcript_path": "...",
  "turn_source": "user_prompt",
  "prompt_ts": "2026-07-04T01:20:00+08:00",
  "stop_ts": null,
  "prompt": "用户本轮输入",
  "last_assistant_message": null
}
```

### Stop

用于记录一轮结束，写入或更新本轮的 `conversation.json`。

```json
{
  "session_id": "...",
  "turn_id": "...",
  "cwd": "D:\\program\\RealSimpleChat",
  "model": "...",
  "permission_mode": "...",
  "transcript_path": "...",
  "turn_source": "user_prompt | auto_or_goal_turn | unknown",
  "prompt_ts": "2026-07-04T01:20:00+08:00",
  "stop_ts": "2026-07-04T01:21:00+08:00",
  "prompt": "用户本轮输入，可能为 null",
  "stop_hook_active": false,
  "last_assistant_message": "Codex 本轮最终回复"
}
```

### PostToolUse

用于从工具事件中提取明确文件操作，追加到本轮的 `file-operations.jsonl`。不能确定文件被创建、修改、删除或移动时不记录。

对 `apply_patch`，脚本应结合 `PreToolUse` 保存的修改前快照和 `PostToolUse` 后的当前文件内容，计算新增/删除的行号区间。新增区间使用修改后文件的行号，删除区间使用修改前文件的行号。

```json
{
  "ts": "2026-07-04T01:20:30+08:00",
  "source": "apply_patch",
  "operation": "modify",
  "path": "D:\\program\\RealSimpleChat\\src\\a.py",
  "line_ranges": {
    "added": [
      {
        "start": 12,
        "end": 18
      }
    ],
    "deleted": [
      {
        "start": 7,
        "end": 9
      }
    ]
  }
}
```

移动操作额外记录 `old_path`：

```json
{
  "ts": "2026-07-04T01:20:30+08:00",
  "source": "apply_patch",
  "operation": "move",
  "path": "D:\\program\\RealSimpleChat\\src\\new.py",
  "old_path": "D:\\program\\RealSimpleChat\\src\\old.py"
}
```

## 目录与写入逻辑

脚本通过 hook payload 中的 `cwd` 解析项目根目录，然后写入：

```text
project_root = 从 payload.cwd 向上查找项目根
session_dir = project_root\codexRuntimeLogFile\<safe_session_id>
turn_index_file = session_dir\.turn-index.json
turn_folder_name = 从 .turn-index.json 查询；不存在则生成 YYYYMMDD_HHMMSS_mmm__<safe_turn_id>
turn_dir = session_dir\<turn_folder_name>
conversation_file = turn_dir\conversation.json
file_operations_file = turn_dir\file-operations.jsonl
snapshot_dir = project_root\codexRuntimeLogFile\.internal\pretool-snapshots\<safe_session_id>\<safe_turn_id>\<tool_use_id>
```

项目根目录识别规则：

1. 优先从 `cwd` 向上查找 `.git`。
2. 其次查找 `.codex`、`AGENTS.md`、`package.json`、`pyproject.toml`、`*.uproject`。
3. 找不到项目标识时，退回 `cwd`。

`session_id` 和 `turn_id` 用于目录名时要做路径安全化：

```text
只保留 A-Z a-z 0-9 . _ -
其它字符替换为 _
空值写为 unknown_session 或 unknown_turn
```

### turn 目录索引

带时间的目录名能解决人工排序问题，但同一轮会有多个 hook 事件，例如：

```text
UserPromptSubmit -> PostToolUse -> Stop
```

这些事件必须写入同一个 turn 目录，所以需要 `.turn-index.json`。

创建或查询流程：

```text
1. 读取 session_dir\.turn-index.json。
2. 用原始 turn_id 查找目录名。
3. 如果已存在，复用该目录名。
4. 如果不存在，用当前本地时间生成时间前缀。
5. 写入映射：turn_id -> YYYYMMDD_HHMMSS_mmm__<safe_turn_id>。
6. 创建 turn 目录和两个核心文件。
```

时间前缀在第一次创建该 turn 目录时产生，后续同一 `turn_id` 事件不再更新时间前缀。

时间格式：

```text
YYYYMMDD_HHMMSS_mmm
```

示例：

```text
20260704_013012_123__turn_abc
```

### conversation.json 写入

`conversation.json` 是本轮对话记录，负责保存输入 prompt 和最终输出。

字段结构：

```json
{
  "session_id": "...",
  "turn_id": "...",
  "cwd": "D:\\program\\RealSimpleChat",
  "model": "...",
  "permission_mode": "...",
  "turn_source": "user_prompt | auto_or_goal_turn | unknown",
  "prompt_ts": "...",
  "stop_ts": "...",
  "prompt": "...",
  "last_assistant_message": "...",
  "goal": {
    "goal_id": "...",
    "objective": "...",
    "status": "active",
    "token_budget": null,
    "tokens_used": 0,
    "time_used_seconds": 0,
    "created_at_ms": 0,
    "updated_at_ms": 0
  }
}
```

重要规则：

- 有 `UserPromptSubmit` 的轮次，说明用户主动提交了输入。
- 没有 `UserPromptSubmit` 但有 `Stop` 的轮次，`prompt` 为 `null`，`turn_source` 标记为 `auto_or_goal_turn`。
- `Stop` 是每轮结束的锚点，不能把 `UserPromptSubmit` 当成每轮必有事件。
- goal 自动续跑、resume、内部继续等场景都可能没有新的用户输入事件。
- 如果当前会话存在激活 goal，在 `conversation.json.goal` 写入单个 goal 对象。
- `goal` 不做数组追加；同一 turn 内多次 hook 触发只覆盖同一个字段，避免重复。
- 如果没有激活 goal，不写 `goal` 字段；如果本 turn 早先已写入 goal，后续事件不删除它。

### file-operations.jsonl 写入

`file-operations.jsonl` 是本轮文件操作记录。每个 `PostToolUse` 事件只在能明确判断文件操作时追加一行或多行。

每行结构：

```json
{
  "ts": "...",
  "source": "apply_patch | shell_command",
  "operation": "create | modify | delete | move",
  "path": "...",
  "line_ranges": {
    "added": [
      {
        "start": 1,
        "end": 10
      }
    ],
    "deleted": []
  }
}
```

`old_path` 只在 `operation = "move"` 时出现；其它操作不写该字段。

`line_ranges` 只在能可靠计算行号区间时出现；当前只要求对 `apply_patch` 生成。`shell_command` 只记录文件操作类型和路径，不强行记录行号区间。

字段含义：

| 字段 | 含义 |
|---|---|
| `ts` | 文件操作被 hook 记录的时间 |
| `source` | 操作来源，取值为 `apply_patch` 或 `shell_command` |
| `operation` | 文件操作类型，取值为 `create`、`modify`、`delete`、`move` |
| `path` | 目标文件路径；移动时为新路径 |
| `old_path` | 移动前路径，仅 `move` 时出现 |
| `line_ranges.added` | 新增内容在修改后文件中的连续行号区间 |
| `line_ranges.deleted` | 删除内容在修改前文件中的连续行号区间 |

行号区间规则：

- 行号从 1 开始。
- `start` 和 `end` 都是闭区间。
- 新增区间用修改后文件行号。
- 删除区间用修改前文件行号。
- 区间只记录行号，不记录具体内容。
- 多段不连续改动写成多个区间对象。

如果同一轮没有明确文件操作，也创建空的 `file-operations.jsonl`，保证每个 turn 目录固定包含两个文件。

记录规则：

- `apply_patch`：解析 patch 头，记录 `Add File`、`Delete File`、`Update File`、`Move to`，并通过前后文件 diff 生成行号区间。
- `shell_command`：只对明显文件写入命令做保守记录，例如 `New-Item`、`Remove-Item`、`Move-Item`、`Copy-Item`、`Set-Content`、`Add-Content`、`Out-File`。
- 只读命令不记录，例如 `Get-Content`、`Select-String`、`rg`、`Get-ChildItem`。
- 不能明确判断具体文件路径或操作类型时不记录，避免误报。

### PreToolUse 临时快照

要记录新增/删除的行号区间，必须知道修改前文件内容。因此对 `apply_patch` 需要启用 `PreToolUse`。

流程：

```text
PreToolUse:
1. 解析 apply_patch 即将影响的文件路径。
2. 对存在的目标文件读取修改前文本。
3. 写入临时快照目录。

PostToolUse:
1. 读取临时快照。
2. 读取修改后的当前文件。
3. 使用文本 diff 生成 added/deleted 行号区间。
4. 写入 file-operations.jsonl。
5. 删除本次 tool_use_id 的临时快照。
```

临时快照目录：

```text
<project_root>\codexRuntimeLogFile\.internal\pretool-snapshots\<sessionId>\<turnId>\<tool_use_id>\
```

临时快照只用于跨 hook 进程传递修改前内容，不属于最终记录。`PostToolUse` 成功处理后应删除对应 `tool_use_id` 快照；异常残留可由后续清理逻辑按时间删除。

## Goal 场景处理

goal 相关记录不应假设固定链路。

推荐判断：

| 情况 | 记录判断 |
|---|---|
| 创建 goal 时用户发送 `/goal ...` | 可能有 `UserPromptSubmit.prompt` |
| goal 运行中用户追加指令 | 有 `UserPromptSubmit.prompt` |
| goal 自动续跑下一轮 | 不依赖 `UserPromptSubmit` |
| goal 活跃时每轮结束 | 依赖 `Stop` |

因此状态字段建议为：

```json
{
  "turn_source": "user_prompt | auto_or_goal_turn | unknown"
}
```

判断逻辑：

```text
如果同一 session_id + turn_id 存在 UserPromptSubmit -> user_prompt
否则如果存在 Stop -> auto_or_goal_turn
否则 -> unknown
```

## 脚本结构

建议文件：

```text
C:\Users\gzxt\.codex\skills\codex-event-logger\SKILL.md
C:\Users\gzxt\.codex\skills\codex-event-logger\scripts\codex_event_logger.ps1
C:\Users\gzxt\.codex\skills\codex-event-logger\scripts\codex_event_logger.py
C:\Users\gzxt\.codex\skills\codex-event-logger\event-logger-settings.json
```

PowerShell 入口只负责：

1. 从 `stdin` 读取 JSON。
2. 调用 Python 脚本。
3. 返回成功，不阻塞 Codex 正常流程。

Python 脚本负责：

1. 解析事件 JSON。
2. 根据 `cwd` 解析项目根目录。
3. 根据配置判断是否记录。
4. 读取或更新 `codexRuntimeLogFile\<sessionId>\.turn-index.json`。
5. 创建 `codexRuntimeLogFile\<sessionId>\<YYYYMMDD_HHMMSS_mmm__turnId>`。
6. 脱敏。
7. 截断超长字段。
8. 写入 `conversation.json` 或追加 `file-operations.jsonl`。

## 配置设计

默认配置文件放在 skill 内：

```text
C:\Users\gzxt\.codex\skills\codex-event-logger\event-logger-settings.json
```

项目级覆盖配置可选：

```text
<project_root>\.codex\event-logger-settings.json
```

读取顺序：

```text
skill 默认配置 -> 项目级覆盖配置
```

建议内容：

```json
{
  "enabled": true,
  "mode": "allowlist",
  "workspace_roots": [
    "D:\\program\\RealSimpleChat",
    "D:\\program\\UE\\GptProjectTest"
  ],
  "events": [
    "UserPromptSubmit",
    "Stop",
    "PreToolUse",
    "PostToolUse",
    "SessionStart",
    "PreCompact",
    "PostCompact"
  ],
  "output_dir_name": "codexRuntimeLogFile",
  "conversation_file_name": "conversation.json",
  "file_operations_file_name": "file-operations.jsonl",
  "record_shell_file_operations": true,
  "record_active_goal": true,
  "goal_db_path": null,
  "max_text_chars": 12000
}
```

推荐默认：

- 不记录全量工具输入输出
- 只记录明确文件创建、修改、删除、移动
- 激活 goal 写入 `conversation.json.goal`，不重复追加
- 只记录 allowlist 工作区
- 输出目录固定为项目根目录下的 `codexRuntimeLogFile`

## hooks.json 示例

全局 hook 配置路径：

```text
C:\Users\gzxt\.codex\hooks.json
```

示例：

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "commandWindows": "powershell -NoProfile -ExecutionPolicy Bypass -File \"C:\\Users\\gzxt\\.codex\\skills\\codex-event-logger\\scripts\\codex_event_logger.ps1\"",
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
            "commandWindows": "powershell -NoProfile -ExecutionPolicy Bypass -File \"C:\\Users\\gzxt\\.codex\\skills\\codex-event-logger\\scripts\\codex_event_logger.ps1\"",
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
            "commandWindows": "powershell -NoProfile -ExecutionPolicy Bypass -File \"C:\\Users\\gzxt\\.codex\\skills\\codex-event-logger\\scripts\\codex_event_logger.ps1\"",
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
            "commandWindows": "powershell -NoProfile -ExecutionPolicy Bypass -File \"C:\\Users\\gzxt\\.codex\\skills\\codex-event-logger\\scripts\\codex_event_logger.ps1\"",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

多个 hook 可以并存。已有 QQ hook 不需要删除，记录 hook 作为同事件下的另一个 command hook。

## 并发与可靠性

hook 可能并发执行，因此写 `.turn-index.json`、`conversation.json`、`file-operations.jsonl` 时都要避免并发覆盖或半写入。

可靠写法：

- 每个 turn 独立目录，降低跨轮写入冲突。
- `.turn-index.json` 使用 session 级文件锁更新，防止同一 `turn_id` 被创建成多个目录。
- `conversation.json` 使用文件锁加原子替换写入。
- `file-operations.jsonl` 使用文件锁追加，每行一个完整 JSON 对象。
- `UserPromptSubmit` 和 `Stop` 都只更新同一个 `conversation.json` 的对应字段。
- 写入失败时写最小错误日志，不阻塞主流程。

`.turn-index.json` 推荐流程：

```text
锁定 session_dir\.turn-index.lock
读取 .turn-index.json
如果 turn_id 已存在，返回已有目录名
如果 turn_id 不存在，生成 YYYYMMDD_HHMMSS_mmm__<safe_turn_id> 并写入索引
释放锁
```

`conversation.json` 推荐流程：

```text
读取现有 conversation.json
合并当前事件字段
写入 conversation.json.tmp.<pid>
原子替换 conversation.json
```

`file-operations.jsonl` 推荐流程：

```text
打开 file-operations.jsonl
获取文件锁
追加一行或多行文件操作 JSON
释放文件锁
```

如果文件锁实现不稳定，优先在脚本内重试或跳过本次文件操作记录，不额外创建第三类文件，保证 turn 目录仍只依赖 `conversation.json` 和 `file-operations.jsonl` 两个核心文件。

## 脱敏与截断

必须脱敏的键名片段：

```text
api_key
apikey
authorization
bearer
cookie
password
passwd
secret
token
access_token
refresh_token
private_key
```

处理规则：

- 字典 key 命中敏感片段，value 写为 `<redacted>`。
- 字符串中出现典型 token 形态时替换为 `<redacted>`.
- `prompt` 和 `last_assistant_message` 按 `max_text_chars` 截断。
- 文件路径按 `max_text_chars` 截断。

## 不记录的内容

不记录：

- 隐藏思考链。
- 未暴露的内部推理过程。
- 未经脱敏的密钥。
- transcript 完整文件副本。
- UI 截图或窗口状态。

`transcript_path` 可以记录路径，但不复制 transcript 内容。

## 查询脚本输出

后续可补一个查询脚本：

```text
C:\Users\gzxt\.codex\skills\codex-event-logger\scripts\query_codex_turn_log.py
```

常用查询：

```text
按项目根目录查询最近 N 轮
按 session_id 查询轮次列表
按 turn_id 展开 conversation.json 和 file-operations.jsonl
查找 prompt 为 null 但存在 last_assistant_message 的轮次
统计每轮工具数量和耗时
```

推荐输出：

```text
[2026-07-04 01:20:00] user_prompt
session_id: ...
turn_id: ...
cwd: D:\program\RealSimpleChat
prompt: ...
file_operations: 3
assistant_final: ...
```

## 验收方法

实现后按以下顺序验收：

1. 配置 hook 后在 `/hooks` 中信任新增 command hook。
2. 发送一条普通消息，确认项目根目录出现 `codexRuntimeLogFile\<sessionId>\<YYYYMMDD_HHMMSS_mmm__turnId>\conversation.json`。
3. 确认 `conversation.json` 同时记录 `prompt` 和 `last_assistant_message`。
4. 触发一次文件修改，确认同一 turn 目录下出现 `file-operations.jsonl`。
5. 检查 `file-operations.jsonl` 每行都是合法 JSON，且只记录明确文件操作。
6. 创建或继续 goal，确认 goal 活跃时 `conversation.json.goal` 写入单个 goal 对象。
7. 检查没有 `UserPromptSubmit` 的轮次被标记为 `auto_or_goal_turn`。
8. 检查同一 `turn_id` 的 `UserPromptSubmit`、`PreToolUse`、`PostToolUse`、`Stop` 都写入或使用同一个带时间目录。
9. 检查 `sessionId` 目录下的 turn 文件夹按名称可自然时间排序。
10. 检查 `file-operations.jsonl` 不写入 `session_id`、`turn_id`、`tool_use_id`、`summary` 等冗余字段。
11. 检查 `apply_patch` 的新增行区间使用修改后文件行号，删除行区间使用修改前文件行号。
12. 检查 `file-operations.jsonl` 不记录具体改动内容。
13. 检查超长输出已截断。

## 当前结论

最合理实现是：

```text
UserPromptSubmit 记录用户输入
Stop 记录每轮结束
PreToolUse 保存 apply_patch 修改前临时快照
PostToolUse 提取明确文件操作
apply_patch 通过前后 diff 记录新增/删除行号区间
conversation.json 在存在激活 goal 时写入单个 goal 对象
session_id + turn_id 负责关联
脚本本体放在 skill
输出写入项目根目录 codexRuntimeLogFile
turn 目录名使用创建时间 + turnId，靠 .turn-index.json 保证同轮复用
每轮目录包含 conversation.json 和 file-operations.jsonl
```

这个方案能覆盖普通对话、工具执行和 goal 自动续跑；日志跟随项目保存，脚本通过 skill 全局复用，同时不依赖不稳定的 transcript 内部格式。
