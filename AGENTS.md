# AGENTS.md

## 项目职责

must: 本文件只补充 `AgentBase` 项目约定，继承全局 `AGENTS.md`；项目架构、正式入口和状态以 `README.md` 为索引，不重复维护易失效的数量、哈希或发布日期

must: 权威 owner：`docs/requirements.md`（目标合同）、`docs/plan.md`（方向/决策/子计划/实践/重开）、`global/AGENTS.md`（候选全局规则）、`global/config.toml`/`global/hooks.template.json`/`global/agents/`（可移植设置）；`skills/`、`.agents/plugins/marketplace.json`、`mcp/`、`tools/`、`development/agent-evaluation/` 依次管 skill/插件发现/MCP/非 MCP 工具/最终评测，其他 `development/` 只放开发/验证/打包/部署资料

must: 由部署入口显式传入的 Codex 根目录中的同名内容是安装目标，不是项目真源；不得从安装副本反向决定项目内容，也不得绕过项目正式入口形成双向同步

must: 本项目只维护 Windows 宿主；项目自有规则、skill、工具、MCP、构建、测试、部署和发布不得新增或保留非 Windows 平台的正式入口、运行时、兼容承诺、测试矩阵或延期路线，外部协议与文件格式中的平台术语不因此改写

must: 本项目不维护 GitHub Actions 或其他远程 CI workflow、runner、required check 和计费自动化；远端仓库只承担源码与历史同步，项目验证通过 Windows 主机上的正式本地入口按影响范围执行，不得把缺少远程 CI 当作待修缺口；重新引入前必须取得用户对外部执行与资源成本的明确裁决

## 维护约定

must: 修改前先读取根 `README.md` 和受影响组件最近的正式说明，只改变当前目标直接涉及的真源、合同和状态说明；纯只读源码定位只读取回答所缺的正式来源，不因本条加载 `README.md`

must: 任务需要选择、新建、替代或重开子计划，改变跨组件方向，或裁决多个正式 owner 时读取 `docs/plan.md`；普通组件内任务不因本条加载总计划

must: 不手工创建 `backup`、`copy`、`draft` 等冗余副本；只有正式发布流程生成的可回滚备份或用户明确要求的副本可以保留

must: `.codex/`、`codexRuntimeLogFile/`、`node_modules/`、`dist/`、`target/`、运行日志、覆盖率和部署沙箱是本地状态或可重建产物，不得作为项目真源提交

must: 测试、fixture、benchmark 语料、runner、原始结果与审计仅属开发资产，不进 Codex payload；`Plugin`/`DirectCompatibility` 同受 payload 合同且须移除受管旧测试。有消费者的 doctor/自检按运行职责裁决，不得把项目测试当运行能力

must: 新增、退役或移交由正式 Codex 部署入口管理的路径或配置键时，在 `development/codex-deployment/managed_asset_lifecycle.json` 中维护稳定身份和显式生命周期转换；不得把当前来源不再枚举直接解释为安装目标应删除，也不得在对应旧版本直接升级边界仍受支持时删除历史身份

must: 可移植 Codex 设置、hooks 模板和自定义子代理不得包含认证、凭据、项目绝对路径、信任哈希、历史、缓存或宿主自动生成状态；机器相关 MCP 和插件安装只记录正式安装入口与前置条件，不伪装成可直接复制的配置

must: 修改全局规则或 skill 触发语义时同步 `trigger-cases.json`；`validate_contract.ps1` 只查结构、引用、身份和集合关系，不复制正文语义或阻断改写

must: 新增或修改模型直接读取、生成或维护的工具返回、文件、文档、日志、快照、索引或生成视图时，在正式 owner 中声明权威事实、实际消费者、读取或修改责任、生命周期、派生关系和恢复方式；模型读取面按当前动作投影最小充分证据，模型修改面保持职责局部且可验证，机器面保持稳定完整，现有消费者必须显式迁移，不得以统一格式、事后截断、直接编辑生成物或双向同步副本代替裁决

must: 文档只更新被本次改动直接影响的事实，删除或改写已经失效的状态，不机械追加新的“当前状态”段落

## 验证与发布

must: 用户授权准备/复现/部署 AgentBase Windows 主机时，以下入口安装/升级并读回 PowerShell 7、fd、scc、hyperfine、Python 3、Node.js LTS、ast-grep、用户级 Codex CLI，再按 `tools/srcq/docs/installation.md` 安装/升级 `srcq` 并读回 Status、`srcq doctor`、`srcq query scc doctor`；PATH 变化后重启 Codex 桌面宿主，再开新任务发布：

```powershell
& (Join-Path (Get-Location).Path 'development\codex-deployment\bootstrap_windows.ps1') -Action Install
```

must not: 普通开发、问答或只读审查不得仅因检测到主机工具缺失而安装或升级软件

must: 全局规则或 skill 变更至少运行：

```powershell
& (Join-Path (Get-Location).Path 'development\skill-routing\validate_contract.ps1') -ProjectRoot (Get-Location).Path
```

must: 路由基础设施变化后运行 `test_routing_infrastructure.ps1`；规则、skill 或触发合同变化后，`Validate`/`Publish` 前按 `get_routing_evaluation_plan.ps1` 刷新 evidence：只执行 `evaluate`，`reuse` 经 oracle 与来源链证明，`pending-routing` 待 Routing 后重算；同输入 oracle 失败不重采样，身份或来源异常须阻断。部署只验证 payload、evidence 与可恢复写入；组件回归仅在受影响且稳定后运行一次

must: 最终评测合同变更后运行 `development/agent-evaluation/test_agent_evaluation_infrastructure.ps1`；门禁禁用 evaluator，外部 clone 仅由显式 `prepare`/单题 `oracle`，依赖与 Verifier 仅由单题 `oracle`/`run`，qualification 仅由 `oracle`、模型仅由 `run` 触发

must: 修改 `global/config.toml`、`global/hooks.template.json`、`global/agents/` 或部署合同后运行：

```powershell
& (Join-Path (Get-Location).Path 'development\codex-deployment\manage_agentbase.ps1') -Action Validate -ProjectRoot (Get-Location).Path
```

should: 修改 `mcp/vscode-lsp-mcp` 或 `tools/srcq` 时，先运行其 README 或清单定义的受影响模块验证；只有公共契约或发布范围受影响时才运行完整验证

must: 修改模型交互面合同后，分别验证模型读取面的决策充分性与渐进恢复、模型修改面的唯一真源与局部可验证性、机器面的结构稳定性、派生产物可重建性和实际消费者接入；Token 收益使用真实 tokenizer 或项目已验证的保守估算衡量，字节数、字段删减和文件变短只作为局部证据

must: 每次使用正式部署入口向实际 Codex 根目录执行 `Publish` 前，必须取得用户针对该次发布的明确同意；Git 维护或远端同步授权、此前的发布授权、验证完成、状态查询以及用户未反对都不得继承或替代该次同意。新的多 skill 部署在插件包通过官方校验且目标环境已单独验证插件安装后使用 `Plugin` 模式，已有直接安装仅在尚未完成迁移时使用 `DirectCompatibility`，两者不得同时启用；一次正式发布产生的一份回滚备份是有效部署资产，不再另建手工备份：

```powershell
& (Join-Path (Get-Location).Path 'development\codex-deployment\manage_agentbase.ps1') -Action Publish -ProjectRoot (Get-Location).Path -CodexRoot (Join-Path $env:USERPROFILE '.codex') -SkillDeliveryMode Plugin -InstallPortableSettings
```

must: 发布只证明文件已安装并通过发布合同；Codex 每次运行启动时构建指令链，因此当前运行不会追溯加载新规则，行为变化需要在新任务或重启会话中验证

## Git 维护边界

must: 本仓库文件本身不创建 Git 外部写授权；用户已于 2026-08-19 明确授予 AgentBase 项目的持续 Git 维护与已配置私有远端同步权限，本条持久记录该用户自有授权；完成已授权项目改动和必要验证后，默认自行检查、暂存、形成职责清晰的提交并非强制推送当前分支到已配置上游，无需逐次确认

must not: 上述持续授权不得解释为历史重写、强制推送、删除远端分支或标签、替换或新增远端、改变仓库归属、提取凭据或覆盖无法安全整合的远端提交授权；这些操作仍须用户针对具体对象与风险明确同意

must: 提交前检查实际差异和忽略范围，保留无关用户改动，并优先形成职责清晰、可独立回退的提交；不得用历史重写、强制覆盖或清理命令掩盖未理解的工作区状态

must: 远端同步前确认当前分支、上游、工作区和待推送提交；只执行非强制推送，远端存在新增提交时先获取并审查，能够保留双方历史时按本项目授权安全整合，无法裁决时不得覆盖远端

must: 使用现有 Git 身份和已配置远端，不虚构身份、凭据或远端地址；新增外部仓库、提取凭据或改变项目外部归属需要相应任务授权

must: Git 历史是本项目的版本记录，不为提交另外创建文件备份；未经用户明确要求，不修改 Codex 配置、个人或宿主插件 marketplace 及无关安装内容；仓库真源 `.agents/plugins/marketplace.json` 只随插件分发合同维护
