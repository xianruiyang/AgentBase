# 安装与迁移

只有用户明确要求安装、迁移到新电脑、迁移到新工作区、或修复 hook 未安装时，才读取本文件。

## 安装或刷新全局 hook

在目标工作区根目录运行：

```powershell
& "$env:USERPROFILE\.codex\skills\codex-qq-hook\scripts\install_global_qq_hook.ps1" -ProjectRoot (Get-Location)
```

该脚本会创建或刷新：

- `~\.codex\hooks.json`
- `~\.codex\qq-hook-global-settings.json`
- `<WORKSPACE>\.codex\qq-hook-settings.json`

安装后如 Codex 提示信任 hook，必须信任。修改 `config.toml`、PATH、用户环境变量或 AppSecret 后，建议重启 Codex。

## 新工作区

进入新工作区后运行安装脚本，然后只把需要提醒的对话 ID 加入该工作区白名单：

```powershell
& "$env:USERPROFILE\.codex\skills\codex-qq-hook\scripts\qq_hook_switch.ps1" enable -ProjectRoot (Get-Location) -Id "对话ID"
```

新工作区不需要填写 `bot`。

## 新电脑

复制或安装 `codex-qq-hook` skill 到：

```text
%USERPROFILE%\.codex\skills\codex-qq-hook
```

然后运行安装脚本，配置全局 `qq-hook-global-settings.json`，设置 `QQ_BOT_APP_SECRET` 用户环境变量，并重新信任 hook。

不要迁移真实 `QQ_BOT_APP_SECRET` 到文件。
