---
name: codex-qq-hook
description: 配置当前工作区的 Codex QQ 完成提醒开关。用于用户要求开启、关闭或查看当前工作区/当前对话是否允许发送 QQ 完成提醒时，只修改工作区 .codex\\qq-hook-settings.json；默认不发送，主动开启后才把对话 ID 加入 enabled_thread_ids。
---

# Codex QQ Hook

用中文回复，结果先行。这个 skill 只处理当前工作区的 `.codex\qq-hook-settings.json`。

## 配置文件

当前工作区配置文件：

```text
<WORKSPACE>\.codex\qq-hook-settings.json
```

如果文件不存在，直接创建。不要让用户先手动创建。

最小配置：

```json
{
  "default_enabled": false,
  "enabled_thread_ids": [],
  "disabled_thread_ids": [],
  "enabled_thread_names": [],
  "disabled_thread_names": [],
  "message": {
    "stop_template": "work_complete",
    "prefix": " ",
    "max_chars": 1200,
    "completion_max_chars": 700
  },
  "goal": {
    "aware": true
  }
}
```

## 字段含义

- `default_enabled`: 默认是否允许本工作区所有对话发送提醒。保持 `false`。
- `enabled_thread_ids`: 已开启提醒的对话 ID 列表。
- `disabled_thread_ids`: 已关闭提醒的对话 ID 列表。
- `enabled_thread_names`: 保留字段，不用它开启提醒。
- `disabled_thread_names`: 保留字段，不用它关闭提醒。
- `message.stop_template`: 完成提醒使用的消息模板，默认 `work_complete`。
- `message.prefix`: 消息前缀，默认一个空格。
- `message.max_chars`: 整条 QQ 消息最大长度。
- `message.completion_max_chars`: 完成摘要最大长度。
- `goal.aware`: 是否在当前对话仍有活跃 goal 时暂缓完成提醒，保持 `true`。

除上述字段外，不添加其他字段。

## 开启当前对话

把当前对话 ID 加入 `enabled_thread_ids`，同时从 `disabled_thread_ids` 移除。

可用脚本修改，脚本会自动创建配置文件：

```powershell
& "$env:USERPROFILE\.codex\skills\codex-qq-hook\scripts\qq_hook_switch.ps1" enable -ProjectRoot (Get-Location) -Id "对话ID"
```

回复用户：已为当前工作区开启这个对话的 QQ 完成提醒。

## 关闭当前对话

把当前对话 ID 加入 `disabled_thread_ids`，同时从 `enabled_thread_ids` 移除。

```powershell
& "$env:USERPROFILE\.codex\skills\codex-qq-hook\scripts\qq_hook_switch.ps1" disable -ProjectRoot (Get-Location) -Id "对话ID"
```

回复用户：已关闭当前工作区这个对话的 QQ 完成提醒。

## 查看状态

```powershell
& "$env:USERPROFILE\.codex\skills\codex-qq-hook\scripts\qq_hook_switch.ps1" status -ProjectRoot (Get-Location)
```

只告诉用户：

- 当前工作区配置文件是否存在。
- 当前对话 ID 是否在 `enabled_thread_ids`。
- 当前对话 ID 是否在 `disabled_thread_ids`。
- `default_enabled` 当前是 `true` 还是 `false`。

如果当前上下文没有对话 ID，不要编造。请用户提供对话 ID，或只说明工作区配置文件当前内容。
