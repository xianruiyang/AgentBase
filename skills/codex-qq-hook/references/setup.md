# 安装与迁移

只有用户明确要求安装、迁移到新电脑、迁移到新工作区、或修复 hook 未安装时，才读取本文件。

## 入口选择

- 复制或克隆完整 `AgentBase` 项目时，优先构建并安装自带 `${PLUGIN_ROOT}` hooks 的 `agentbase-core` 插件。全局规则与可移植设置使用项目部署入口的 `Plugin` 模式，不重复安装同名 skill 或全局 hooks。
- 已有 `<CodexRoot>\skills` 安装尚未迁移时，可继续使用项目部署入口的 `DirectCompatibility` 模式；该模式是兼容路径，不与插件同时启用。
- 只有当前 skill 被独立安装、且没有 `AgentBase` 项目部署入口时，才使用下方 `install_global_qq_hook.ps1`。

## 安装或刷新全局 hook

在目标工作区根目录运行：

```powershell
$SkillDir = '<skill_dir>'
& (Join-Path $SkillDir 'scripts\install_global_qq_hook.ps1') -ProjectRoot (Get-Location) -CodexRoot (Join-Path $env:USERPROFILE '.codex')
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

独立安装 skill 时使用 Codex 当前支持的本地 skill 位置，例如：

```text
<USERPROFILE>\.agents\skills\codex-qq-hook
```

然后向安装脚本显式传入 `<CodexRoot>`，配置全局 `qq-hook-global-settings.json`，设置 `QQ_BOT_APP_SECRET` 用户环境变量并重新信任 hook。旧版 `<CodexRoot>\skills\codex-qq-hook` 可作迁移期来源，但不能用目录层级反推 Codex 根目录。

不要迁移真实 `QQ_BOT_APP_SECRET` 到文件。

`<skill_dir>` 是本文件所属 skill 目录；`<CodexRoot>` 由显式参数、`CODEX_HOME` 或默认用户 Codex 目录确定，与 skill 的插件缓存或本地加载位置无关。
