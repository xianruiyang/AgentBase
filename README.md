# AgentBase

**一套面向 Windows 的 Codex 基础配置。**

AgentBase 将日常使用 Codex 时积累的全局规则、skills、自定义子代理和配套工具集中维护，方便持续调整、迁移到其他电脑，以及按需参考和复用。

这套配置偏向长期维护代码项目：让 Codex 先理解目标和现有实现，按需查证、修改和验证；复杂任务能保留必要的进度与依据，简单任务则直接处理。默认采用中文沟通、简洁输出，并对操作授权和修改范围作出明确约定。

[开始使用](#开始使用) · [配置内容](#配置内容) · [下载发行包](https://github.com/xianruiyang/AgentBase/releases) · [安装与恢复](development/codex-deployment/README.md) · [MIT License](LICENSE)

## 设计目标

- **减少重复交代。** 把跨项目通用的协作习惯放进全局规则，项目自己的架构、风格和命令仍由各项目说明。
- **让判断有依据。** 区分用户要求、文档约定和源码现状，遇到不确定性时先取得能影响下一步的证据。
- **让复杂工作可以继续。** 用交付文档和任务工具组织需求、依赖、结果与恢复上下文，避免长任务只依赖对话记忆。
- **按需使用工具和子代理。** 按任务选择搜索、语义查询、实验或执行角色，主代理负责审核与最终交付。
- **控制上下文和验证成本。** 工具优先返回当前动作需要的信息，完整数据保留供后续读取；验证按改动影响范围进行。

这些是配置的设计取向。实际效果仍取决于模型、Codex 版本、项目内容和具体任务。

## 配置内容

### 全局规则与可移植设置

[`global/`](global/README.md) 包含全局 `AGENTS.md`、可移植的 `config.toml`、hooks 模板和自定义子代理配置。

全局规则约定如何理解目标、读取证据、控制修改范围、使用工具和交付结果。可移植设置只管理选定的配置项，主线程模型、默认推理深度、认证、项目信任、MCP 和插件安装状态等由目标电脑保留或单独配置。

### 按任务加载的 skills

[`skills/`](skills/) 将具体方法拆成可按需读取的说明，主要覆盖：

| 用途 | 相关 skills |
| --- | --- |
| 复杂变更与执行 | `change-governance`、`execution-governor` |
| 交付文档与长期任务 | `delivery-workflow`、`task-table-manager` |
| 源码查询与编辑器操作 | `source-query`、`symbol-structure-workflow` |
| 工程与空间问题 | `powershell-usage`、`cpp-engineering-rules`、`understand-space` |
| 子代理协作 | `subagent-orchestration` |
| 对话记录、通知与线程设置 | `codex-event-logger`、`codex-qq-hook`、`reasoning-governor` |

QQ 通知默认关闭，按工作区或任务启用；线程推理深度的查询与调整由用户明确提出。各 skill 的具体适用范围见其 `SKILL.md`。

### 四个自定义子代理

| 角色 | 用途 |
| --- | --- |
| `evidence` | 只读查找源码、文档与当前状态，提供可核查的证据 |
| `experiment` | 通过修改和运行完成范围明确的实现实验 |
| `advanced-experiment` | 处理普通实验难以可靠完成的问题，或需要截图、渲染等视觉反馈的实验 |
| `operator` | 执行步骤与结果判定已经明确的操作 |

具体模型和参数在 [`global/agents/`](global/agents/) 中维护。主代理负责规划、审核和验收；子代理的进一步委派受本次任务说明约束。

### 配套工具

| 工具 | 用途 | 安装说明 |
| --- | --- | --- |
| [`srcq`](tools/srcq/README.md) | 统一文本、文件、源码统计和 AST 查询，提供源码位置、符号关系及分页结果 | [srcq 安装](tools/srcq/docs/installation.md) |
| [`workctl` / `taskctl`](tools/workflow-cli/README.md) | 查询和维护交付文档、任务依赖、状态、结果及来源快照 | [workflow-cli 安装](tools/workflow-cli/docs/installation.md) |
| [`vscode-lsp-mcp`](mcp/vscode-lsp-mcp/README.md) | 通过 VS Code 语言服务获取语义信息，并支持相应编辑器操作 | [MCP 安装](mcp/vscode-lsp-mcp/docs/installation.md) |

CLI 和 MCP 各自构建、安装与发行。`agentbase-core` 插件负责分发 skills 与相关 hooks，主机上的工具和 MCP 按对应说明单独准备。

## 开始使用

项目目前只维护 **Windows**，脚本以 **PowerShell 7** 为基线。完整使用需要可用的 Codex 环境，以及部署说明列出的 Python、Node.js、源码查询等前置工具；具体版本和检查方法见[主机准备](development/codex-deployment/README.md#prepare-a-windows-host)。

1. **取得仓库或发行包。** 从 [Releases](https://github.com/xianruiyang/AgentBase/releases) 下载 AgentBase 主包，或克隆源码。主包包含源码、部署入口、预构建插件和恢复工具；srcq、workflow-cli 另有独立发行资产。
2. **先阅读并调整配置。** 从 [`global/AGENTS.md`](global/AGENTS.md) 和 [`global/config.toml`](global/config.toml) 开始，确认其中的工作习惯适合自己。当前可移植设置包含 `approval_policy = "never"` 和 `sandbox_mode = "danger-full-access"`，使用前尤其需要确认这两个权限选项。
3. **准备主机工具。** 按[部署说明](development/codex-deployment/README.md)准备依赖，并分别安装 srcq 与 workflow-cli；需要 VS Code 语义能力时再按 MCP 的说明接入。
4. **选择安装方式并部署。** 新安装使用 Plugin 模式，按说明安装并启用 `agentbase-core`，再部署全局规则与所选设置。已有直接安装使用 `DirectCompatibility`，完成迁移前保持该模式；同名 skills 和 hooks 不能同时从两种方式加载。
5. **检查是否生效。** 用部署入口的 `Status` 检查文件状态，并在新任务中确认规则和角色。PATH 或 MCP 发生变更后，需要完整退出并重启 Codex 桌面宿主；若新任务仍显示旧的自定义角色，也应重启宿主后再检查。

完整命令统一放在[部署指南](development/codex-deployment/README.md#deploy-on-another-windows-machine)，插件构建细节见[插件说明](development/plugin-packaging/README.md)。如果让 Codex 代为操作，每次向真实配置目录执行 Deploy 都需要你对当次操作明确同意。

也可以先只阅读、参考其中的规则或 skill。复用单个 skill 时，请一并检查它引用的文件和工具依赖。

## 更新与恢复

部署脚本只更新 AgentBase 管理的内容，并为变更生成回滚记录。新用户首次部署还会默认保存修改前的原配置，后续升级保留最早的原件。

- **回退一次部署：** 使用该次部署返回的备份路径执行 `Rollback`。
- **恢复首次部署前的配置：** 先用 `PreviewRestore` 查看差异与冲突，再执行 `RestoreOriginal`。有冲突时会拒绝写入，需要先处理冲突。
- **独立恢复：** 发行包提供 PowerShell 恢复工具，无需启动 Codex 或安装配套 CLI；原始备份仍须保存在本机。使用过插件模式时，先通过插件入口停用或卸载 `agentbase-core`。

已有安装不会补造过去的原配置，继续使用既有回滚记录。恢复覆盖 AgentBase 管理的配置，软件安装、PATH、账号与整个宿主环境的恢复另行处理。具体边界见[原配置恢复说明](development/codex-deployment/README.md#original-configuration-recovery)。

## 仓库结构与维护

| 目录 | 内容 |
| --- | --- |
| [`global/`](global/README.md) | 全局规则、可移植设置、hooks 与子代理 |
| [`skills/`](skills/) | 各项 skill 的说明与运行资源 |
| [`tools/`](tools/) | srcq、workflow-cli 源码与安装器 |
| [`mcp/`](mcp/) | VS Code LSP MCP 及相关组件 |
| [`development/`](development/) | 本地验证、插件打包、部署、发行与评测框架 |
| [`docs/`](docs/) | 项目需求、计划、设计与维护记录 |
| [`.agents/plugins/marketplace.json`](.agents/plugins/marketplace.json) | 仓库级插件发现配置 |

修改从仓库源码开始，安装到 Codex 的文件由部署入口管理。配置变更后的验证入口见[部署验证](development/codex-deployment/README.md#validate)，skills 的结构与触发检查见[路由说明](development/skill-routing/README.md)，CLI 和 MCP 则按各组件文档验证。项目采用 Windows 本地验证，不维护远程 CI。

评测部分只分发框架、schema 和合成测试；真实题目、答案、实际作答与逐题记录保留本机，基础框架验证不依赖私有题库。详细边界见[评测说明](development/agent-evaluation/README.md)和[数据约定](docs/requirements.md#con-008-真实评测数据仅保留在本机)。

进一步了解项目的维护思路，可以阅读[根本需求](docs/requirements.md)、[总计划](docs/plan.md)和[项目约定](AGENTS.md)；主包与组件的分发关系见[发行说明](development/release/README.md)。

## 许可证

除另有声明的组件与第三方内容外，AgentBase 使用 [MIT License](LICENSE)。[`mcp/vscode-lsp-mcp`](mcp/vscode-lsp-mcp/LICENSE) 使用 Apache-2.0，[`tools/srcq`](tools/srcq/LICENSE) 使用 MIT OR Apache-2.0；第三方内容保留各自的版权声明和许可证。
