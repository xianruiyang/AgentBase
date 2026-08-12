# AGENTS.md

## 项目职责

must: 本文件只补充 `AgentBase` 项目约定，继承全局 `AGENTS.md`；项目架构、正式入口和当前状态以 `README.md` 为索引，不在本文件重复维护易失效的数量、哈希或发布日期

must: 本项目的权威来源按职责划分：`global/AGENTS.md` 维护候选全局规则，`global/config.toml`、`global/hooks.template.json` 与 `global/agents/` 维护可移植 Codex 设置、hooks 模板和自定义子代理，`skills/` 维护 skill，`.agents/plugins/marketplace.json` 只维护仓库级插件发现入口，`mcp/` 维护 MCP，`tools/` 维护非 MCP 工具，`development/` 只维护验证、打包、部署和开发资料

must: 由部署入口显式传入的 Codex 根目录中的同名内容是安装目标，不是项目真源；不得从安装副本反向决定项目内容，也不得绕过项目正式入口形成双向同步

## 维护约定

must: 修改前先读取根 `README.md` 和受影响组件最近的正式说明，只改变当前目标直接涉及的真源、合同和状态说明

must: 不手工创建 `backup`、`copy`、`draft` 等冗余副本；只有正式发布流程生成的可回滚备份或用户明确要求的副本可以保留

must: `.codex/`、`codexRuntimeLogFile/`、`node_modules/`、`dist/`、`target/`、运行日志、覆盖率和部署沙箱是本地状态或可重建产物，不得作为项目真源提交

must: 可移植 Codex 设置、hooks 模板和自定义子代理不得包含认证、凭据、项目绝对路径、信任哈希、历史、缓存或宿主自动生成状态；机器相关 MCP 和插件安装只记录正式安装入口与前置条件，不伪装成可直接复制的配置

must: 修改全局规则或 skill 的触发语义时，同步维护 `development/skill-routing/validate_contract.ps1` 和适用的 `trigger-cases.json`；不得为保留旧字符串检查而在正式规则中制造重复表述

must: 文档只更新被本次改动直接影响的事实，删除或改写已经失效的状态，不机械追加新的“当前状态”段落

## 验证与发布

must: 用户明确要求在新的 Windows 主机准备、复现或部署 AgentBase 时，主机前置安装属于该授权范围；先运行以下正式入口主动安装或升级缺失的 PowerShell 7、fd、Python 3、Node.js LTS 与已验证 ast-grep，并读回能力状态，完成后开启新 Codex 任务再继续发布：

```powershell
& (Join-Path (Get-Location).Path 'development\codex-deployment\bootstrap_windows.ps1') -Action Install
```

must not: 普通开发、问答或只读审查不得仅因检测到主机工具缺失而安装或升级软件

must: 全局规则或 skill 变更至少运行：

```powershell
& (Join-Path (Get-Location).Path 'development\skill-routing\validate_contract.ps1') -ProjectRoot (Get-Location).Path
```

must: 全局规则、skill 内容或触发场景变化后，正式 `Validate` 或 `Publish` 前必须由未读取 `trigger-cases.json` 期望值的独立评估器刷新 `development/skill-routing/evidence/current.json`；部署入口和 CI 必须拒绝哈希过期、缺项或违反期望/禁选约束的证据

must: 修改 `global/config.toml`、`global/hooks.template.json`、`global/agents/` 或部署合同后运行：

```powershell
& (Join-Path (Get-Location).Path 'development\codex-deployment\manage_agentbase.ps1') -Action Validate -ProjectRoot (Get-Location).Path
```

should: 修改 `mcp/vscode-lsp-mcp` 或 `tools/sgy` 时，先运行其 README 或清单定义的受影响模块验证；只有公共契约或发布范围受影响时才运行完整验证

must: 只有用户明确授权加载时，才使用正式部署入口；新的多 skill 部署在插件包通过官方校验且目标环境已单独验证插件安装后使用 `Plugin` 模式，已有直接安装仅在尚未完成迁移时使用 `DirectCompatibility`，两者不得同时启用；一次正式发布产生的一份回滚备份是有效部署资产，不再另建手工备份：

```powershell
& (Join-Path (Get-Location).Path 'development\codex-deployment\manage_agentbase.ps1') -Action Publish -ProjectRoot (Get-Location).Path -CodexRoot (Join-Path $env:USERPROFILE '.codex') -SkillDeliveryMode Plugin -InstallPortableSettings
```

must: 发布只证明文件已安装并通过发布合同；Codex 每次运行启动时构建指令链，因此当前运行不会追溯加载新规则，行为变化需要在新任务或重启会话中验证

## Git 维护边界

must: 本仓库文件本身不创建 Git 外部写授权；只有用户在当前请求、上位用户级指令或其他可验证的用户自有授权来源中明确授予后，才可执行暂存、提交、分支、合并、变基、标签或远端同步，授权对象、风险和持续范围以该来源为准

must: 当前指令链已经明确授予本项目 Git 维护与远端同步权限时，已授权改动在完成必要验证并形成职责清晰的本地提交后默认同步当前分支到已配置上游；用户要求仅保留本地、授权未覆盖外部写入、上游缺失、权限或凭据失败，或远端分叉无法安全裁决时停止同步并报告

must: 提交前检查实际差异和忽略范围，保留无关用户改动，并优先形成职责清晰、可独立回退的提交；不得用历史重写、强制覆盖或清理命令掩盖未理解的工作区状态

must: 远端同步前确认当前分支、上游、工作区和待推送提交；只执行非强制推送，远端存在新增提交时先获取并审查，能够保留双方历史时按本项目授权安全整合，无法裁决时不得覆盖远端

must: 使用现有 Git 身份和已配置远端，不虚构身份、凭据或远端地址；新增外部仓库、提取凭据或改变项目外部归属需要相应任务授权

must: Git 历史是本项目的版本记录，不为提交另外创建文件备份；未经用户明确要求，不修改 Codex 配置、个人或宿主插件 marketplace 及无关安装内容；仓库真源 `.agents/plugins/marketplace.json` 只随插件分发合同维护
