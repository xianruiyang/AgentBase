# AGENTS.md

## 项目职责

must: 本文件只补充 `AgentBase` 项目约定，继承全局 `AGENTS.md`；项目架构、正式入口和当前状态以 `README.md` 为索引，不在本文件重复维护易失效的数量、哈希或发布日期

must: 本项目的权威来源按职责划分：`global/AGENTS.md` 维护候选全局规则，`skills/` 维护 skill，`mcp/` 维护 MCP，`tools/` 维护非 MCP 工具，`development/` 只维护验证、打包、部署和开发资料

must: `C:\Users\gzxt\.codex` 中的同名内容是安装目标，不是项目真源；不得从安装副本反向决定项目内容，也不得绕过项目正式入口形成双向同步

## 维护约定

must: 修改前先读取根 `README.md` 和受影响组件最近的正式说明，只改变当前目标直接涉及的真源、合同和状态说明

must: 不手工创建 `backup`、`copy`、`draft` 等冗余副本；只有正式发布流程生成的可回滚备份或用户明确要求的副本可以保留

must: `.codex/`、`codexRuntimeLogFile/`、`node_modules/`、`dist/`、`target/`、运行日志、覆盖率和部署沙箱是本地状态或可重建产物，不得作为项目真源提交

must: 修改全局规则或 skill 的触发语义时，同步维护 `development/skill-routing/validate_contract.ps1` 和适用的 `trigger-cases.json`；不得为保留旧字符串检查而在正式规则中制造重复表述

must: 文档只更新被本次改动直接影响的事实，删除或改写已经失效的状态，不机械追加新的“当前状态”段落

## 验证与发布

must: 全局规则或 skill 变更至少运行：

```powershell
& 'D:\program\AgentBase\development\skill-routing\validate_contract.ps1' -ProjectRoot 'D:\program\AgentBase'
```

should: 修改 `mcp/vscode-lsp-mcp` 或 `tools/sgy` 时，先运行其 README 或清单定义的受影响模块验证；只有公共契约或发布范围受影响时才运行完整验证

must: 只有用户明确授权加载时，才使用正式部署入口；一次正式发布产生的一份回滚备份是有效部署资产，不再另建手工备份：

```powershell
& 'D:\program\AgentBase\development\codex-deployment\manage_agentbase.ps1' -Action Publish -ProjectRoot 'D:\program\AgentBase' -CodexRoot 'C:\Users\gzxt\.codex'
```

must: 发布只证明文件已安装并通过发布合同；Codex 每次运行启动时构建指令链，因此当前运行不会追溯加载新规则，行为变化需要在新任务或重启会话中验证

## Git 维护授权

must: 用户已持续授权 Codex 全权维护本项目 Git；为完成项目目标，可自主执行暂存、提交、分支、合并、变基、标签、暂存区整理以及已配置远端的同步，不需要逐次请求确认

must: 提交前检查实际差异和忽略范围，保留无关用户改动，并优先形成职责清晰、可独立回退的提交；不得用历史重写、强制覆盖或清理命令掩盖未理解的工作区状态

must: 使用现有 Git 身份和已配置远端，不虚构身份、凭据或远端地址；新增外部仓库、提取凭据或改变项目外部归属需要相应任务授权

must: Git 历史是本项目的版本记录，不为提交另外创建文件备份；未经用户明确要求，不修改 Codex 配置、插件 marketplace 或无关安装内容
