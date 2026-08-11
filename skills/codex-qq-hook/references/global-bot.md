# 全局 QQ 机器人配置

只有用户明确要求设置或更换 QQ 机器人、目标 QQ 用户、OpenID、AppID、AppSecret 时，才读取本文件。

## 配置文件

全局配置文件：

```text
<CodexRoot>\qq-hook-global-settings.json
```

示例结构：

```json
{
  "bot": {
    "app_id": "你的 QQ 机器人 AppID",
    "target_type": "user",
    "openid": "目标用户 OpenID",
    "group_openid": "",
    "channel_id": "",
    "is_wakeup": false
  }
}
```

不要把 AppSecret 写入这个文件。

## AppSecret

AppSecret 写入用户环境变量：

```powershell
[Environment]::SetEnvironmentVariable("QQ_BOT_APP_SECRET", "你的 AppSecret", "User")
```

修改用户环境变量后，重启 Codex。

## 获取单聊 OpenID

```powershell
$env:QQ_BOT_APP_ID = "你的 AppID"
$env:QQ_BOT_APP_SECRET = "你的 AppSecret"
$SkillDir = '<skill_dir>'
& (Join-Path $SkillDir 'scripts\qq_ws_openid_capture.ps1')
```

`<skill_dir>` 是当前 skill 目录；`<CodexRoot>` 由它向上两级得到。

看到 `Identify sent` 后，让目标 QQ 用户扫码聊天并给机器人发一句私聊，读取输出中的 `QQ_BOT_OPENID=...`。

## 输出要求

回复用户时默认只说字段是否已设置、是否仍是模板值。不要展示真实 AppSecret；除非用户明确要求，也不要直接展示真实 AppID 或 OpenID。
