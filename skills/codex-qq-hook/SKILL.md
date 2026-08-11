---
name: codex-qq-hook
description: 配置和排查 Codex QQ 完成提醒。用于用户明确要求开启、关闭或只读查看当前工作区/当前对话的提醒开关，安装或迁移 QQ hook，设置机器人与目标账号，或排查未发送链路时；状态查询不得创建或改写配置，提醒默认关闭，只有显式开启的对话才加入 enabled_thread_ids。
---

# Codex QQ Hook

用中文回复，结果先行。开关操作只处理当前工作区的 `.codex\qq-hook-settings.json`；安装、全局机器人配置和排障仅在用户明确要求对应动作时进入各自参考。

## 路由

- 开启、关闭或查看工作区/对话开关：直接按本文件执行；`status` 始终只读。
- 安装、刷新或迁移 hook：完整读取 [setup.md](references/setup.md)。
- 设置或更换机器人、目标 QQ 用户、OpenID、AppID 或 AppSecret：完整读取 [global-bot.md](references/global-bot.md)。
- 排查未收到提醒、hook 链路或日志：完整读取 [troubleshooting.md](references/troubleshooting.md)。

## 配置文件

当前工作区配置文件：

```text
<WORKSPACE>\.codex\qq-hook-settings.json
```

执行 `enable` 或 `disable` 时，如果文件不存在就创建，不要让用户先手动创建。执行 `status` 时不得创建目录、文件或补写默认字段，只在内存中使用默认配置生成状态。

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
$SkillDir = '<skill_dir>'
& (Join-Path $SkillDir 'scripts\qq_hook_switch.ps1') enable -ProjectRoot (Get-Location) -Id "对话ID"
```

回复用户：已为当前工作区开启这个对话的 QQ 完成提醒。

## 关闭当前对话

把当前对话 ID 加入 `disabled_thread_ids`，同时从 `enabled_thread_ids` 移除。

```powershell
$SkillDir = '<skill_dir>'
& (Join-Path $SkillDir 'scripts\qq_hook_switch.ps1') disable -ProjectRoot (Get-Location) -Id "对话ID"
```

回复用户：已关闭当前工作区这个对话的 QQ 完成提醒。

## 查看状态

```powershell
$SkillDir = '<skill_dir>'
& (Join-Path $SkillDir 'scripts\qq_hook_switch.ps1') status -ProjectRoot (Get-Location) -Id $env:CODEX_THREAD_ID
```

`<skill_dir>` 由当前 skill 目录定位，不假定 Codex home 位于特定用户路径。

只告诉用户：

- 当前工作区配置文件是否存在。
- 当前对话 ID 是否在 `enabled_thread_ids`。
- 当前对话 ID 是否在 `disabled_thread_ids`。
- `default_enabled` 当前是 `true` 还是 `false`。

如果当前上下文没有对话 ID，不要编造。请用户提供对话 ID，或只说明工作区配置文件当前内容。
