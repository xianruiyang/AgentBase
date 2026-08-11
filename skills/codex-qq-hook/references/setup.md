# 安装与迁移

只有用户明确要求安装、迁移到新电脑、迁移到新工作区、或修复 hook 未安装时，才读取本文件。

## 入口选择

- 复制或克隆完整 `AgentBase` 项目时，使用项目的 `development/codex-deployment/manage_agentbase.ps1 -Action Publish -InstallPortableSettings`；它会在同一事务中安装 skill、解析 `global/hooks.template.json`、备份并验证目标文件。不要再运行本 skill 的独立安装脚本形成第二套项目部署入口。
- 只有当前 skill 被独立安装、且没有 `AgentBase` 项目部署入口时，才使用下方 `install_global_qq_hook.ps1`。

## 安装或刷新全局 hook

在目标工作区根目录运行：

```powershell
$SkillDir = '<skill_dir>'
& (Join-Path $SkillDir 'scripts\install_global_qq_hook.ps1') -ProjectRoot (Get-Location)
```

该脚本会创建或刷新：

- `<CodexRoot>\hooks.json`（只合并本 skill 的 QQ Stop handler，保留其他事件和 handler）
- `<CodexRoot>\qq-hook-global-settings.json`
- `<WORKSPACE>\.codex\qq-hook-settings.json`

安装后如 Codex 提示信任 hook，必须信任。修改 `config.toml`、PATH、用户环境变量或 AppSecret 后，建议重启 Codex。

## 新工作区

进入新工作区后运行安装脚本，然后只把需要提醒的对话 ID 加入该工作区白名单：

```powershell
$SkillDir = '<skill_dir>'
& (Join-Path $SkillDir 'scripts\qq_hook_switch.ps1') enable -ProjectRoot (Get-Location) -Id "对话ID"
```

新工作区不需要填写 `bot`。

## 新电脑

复制或安装 `codex-qq-hook` skill 到所选 Codex 根目录：

```text
<CodexRoot>\skills\codex-qq-hook
```

然后运行安装脚本，配置全局 `qq-hook-global-settings.json`，设置 `QQ_BOT_APP_SECRET` 用户环境变量，并重新信任 hook。

不要迁移真实 `QQ_BOT_APP_SECRET` 到文件。

`<skill_dir>` 是本文件所属 skill 目录；`<CodexRoot>` 由它向上两级得到，不假定具体用户名或系统盘。
