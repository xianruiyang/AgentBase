# AgentBase

本项目集中维护候选全局 `AGENTS.md`、可移植 Codex 关键设置与自定义子代理、12 个关键 skill、对应开发工程以及实际依赖的 MCP/CLI。所有改动先进入本目录真源，通过静态合同、盲测和隔离发布验证后，再由用户明确决定是否发布到 Codex。

## 真源与安装副本

- `global/AGENTS.md` 是全局规则候选真源，不自动覆盖 Codex 用户目录。
- `global/config.toml` 是经过筛选的可移植 Codex 设置真源；`global/hooks.template.json` 是按目标 Codex 根目录解析的 hooks 真源；`global/agents/*.toml` 是自定义子代理真源。它们都不会因文件存在而自动覆盖用户配置。
- `skills/<skill-name>/` 是已迁入 skill 的唯一开发真源。
- `mcp/<mcp-name>/` 是 skill 所依赖 MCP 的开发与发布真源。
- `tools/<tool-name>/` 是 skill 捆绑或调用的非 MCP 工具开发真源。
- `development/<name>/` 只承载验证、打包、部署和不随 skill 安装的开发资料。
- `C:\Users\gzxt\.codex` 中的 `AGENTS.md`、同名 skill、`config.toml`、`hooks.json` 与 `agents/*.toml` 都是安装目标或宿主状态，不反向定义本项目。
- 原工程目录只作为迁移来源保留，不自动双向同步；缓存、测试输出和构建产物不属于真源。

## 当前全局内核

`global/AGENTS.md` 只保留跨项目都成立的目标、证据、授权、工具路由、修改、验证、记录和交付规则。复杂根因、职责/入口迁移、共享门禁和跨契约审计细节由 `change-governance` 承担；C++、PowerShell、搜索、符号/AST、空间、任务表和动态推理协议由对应 skill 承担。

当前候选为 18,197 字节、79 条规范规则，静态合同上限为 20 KiB。与上一候选 17,310 字节、78 条规则相比，新增一条 active Goal 内动态升降线程推理深度的全局规则，并把执行协议收敛到独立 skill。当前内核收敛为四项核心约束：

- 规范来源用于确定目标契约，有效证据用于判断系统现状与实现结果；两者不得互相替代，用户目标也不得被系统现状静默改写。
- 在用户目标和授权范围内按长期净收益与系统总成本选择方案；长期收益不得用于扩大范围或替用户裁决。
- 不自动把实现收缩成最窄局部补丁；为使用户要求成立并接入唯一正式入口而不可缺少的调整属于本次实现，仅改善整体架构但不影响本次结果的调整需要另行授权。
- 用户未固定深度时，在 active Goal 内按下一段工作的真实不确定性、后果、可逆性和验证负担自由升降 next-turn 推理深度；不绑定任务项边界，不用 hook 或持久状态模拟续跑。

## 已迁入的 skill

| Skill | 迁移来源 | 当前职责 |
| --- | --- | --- |
| `codex-event-logger` | `D:\program\RealSimpleChat\codex-hook-logging-research\codex-event-logger` | 只在上下文缺失或用户要求追溯时读取项目级运行记录 |
| `codex-qq-hook` | `D:\program\RealSimpleChat\qq-bot-research\skill-content\codex-qq-hook` | 按用户明确要求配置当前工作区 QQ 完成提醒 |
| `task-table-manager` | `D:\program\UE\GptProjectTest\UeAgentInterfacePak\skills\task-table-manager` | 管理跨轮、真实依赖和持久完成审计；CLI 与测试自包含在 skill 内 |
| `reasoning-governor` | 从 `task-table-manager` 的线程深度脚本拆分建源 | 读取和切换当前线程 next-turn 推理深度；模型自主切换只由 active Goal 续跑 |
| `symbol-structure-workflow` | `D:\program\SimpleChat\SymbolStructureWorkflow\skill` | 在文本、AST、LSP 和编辑工具间分层路由，并声明 `vscode-lsp-mcp` 依赖 |
| `ast-grep-token-safe` | `D:\program\SimpleChat\SymbolStructureWorkflow\ast-grep-token-safe` | 使用内置 `sgy` 做 Token-Safe AST 搜索与改写 |
| `rg-token-safe` | 原 Codex 安装副本引导建源 | 有界、可定位、低重复的正文搜索 |
| `fd-usage` | 原 Codex 安装副本引导建源 | 有界文件/目录发现，区分 pattern、path 和对象类型 |
| `powershell-usage` | 原 Codex 安装副本引导建源 | Windows PowerShell 5.1 命令、路径、编码与退出码规则 |
| `change-governance` | 原全局条件性治理规则拆分建源 | 复杂根因、职责/入口、迁移、共享门禁和跨契约审计 |
| `cpp-engineering-rules` | 原 Codex 安装副本审查建源 | C++ 职责、公开接口、include、PCH 与 unity build |
| `understand-space` | `D:\program\UE\GptProjectTest\UeAgentInterfacePak\skills\understand-space` | 只在正确性依赖空间关系、布局或坐标转换时规范化空间意图 |

## 开发工程与依赖边界

| 目录 | 对应 Skill | 职责 |
| --- | --- | --- |
| `mcp/vscode-lsp-mcp` | `symbol-structure-workflow` | MCP server、VS Code companion、共享协议、安全组件、测试与独立发布工程 |
| `tools/sgy` | `ast-grep-token-safe` | 构建 skill 内置 `sgy` 的 Rust workspace、测试、fuzz、安装与发布工程 |
| `development/codex-event-logger` | `codex-event-logger` | hook 设计资料；正式运行脚本仍在 skill 真源 |
| `development/codex-qq-hook` | `codex-qq-hook` | Webhook 辅助程序和开发说明；正式运行脚本仍在 skill 真源 |
| `development/skill-routing` | 全局规则与 12 个 skill | 静态触发合同、盲测输入生成与结果判定 |
| `development/plugin-packaging` | 12 个 skill | 生成并校验 `agentbase-core` 本地插件包 |
| `development/codex-deployment` | 全局规则、可移植设置、hooks、自定义子代理与 12 个 skill | 校验、可选设置安装、带备份发布和可验证回滚 |

`vscode-lsp-mcp` 保持独立发布真源：它已有 `release:build` 和 `release:verify`，且还包含 VS Code companion 与安装生命周期。插件包不复制 MCP，也不创建第二套安装入口；`symbol-structure-workflow/agents/openai.yaml` 只声明对 `vscode-lsp-mcp` 的工具依赖。旧的 `vscode-mcp` 与 `ast-mcp` 不属于当前权威依赖。

## 路由与行为验证

`development/skill-routing/trigger-cases.json` 当前包含 37 个场景。全部 12 个 skill 都至少有一个正向触发和一个相近非触发场景，并额外覆盖事实冲突、只读授权、长期收益、禁止越权替代执行、active Goal 内动态推理切换、显式线程设置、QQ 只读状态与故障排查、旧任务资产迁移，以及三类架构边界：职责与入口已知时直接集成、未知时先治理裁决、一次性产物不得升级为架构工程。

静态合同会检查全局文件大小与关键语义、规则标签、重复规则、skill frontmatter、`agents/openai.yaml`、MCP 依赖、Markdown 相对引用、场景集合和正/负覆盖：

```powershell
& 'D:\program\AgentBase\development\skill-routing\validate_contract.ps1' -ProjectRoot 'D:\program\AgentBase'
```

盲测输入生成器只暴露请求、候选规则和允许的行为标签，不暴露期望技能或禁选技能。候选哈希只覆盖评估器实际读取的全局规则、各 skill 的 `SKILL.md` 与 `agents/openai.yaml`，不会被测试缓存或其他未评估的运行产物扰动：

```powershell
& 'D:\program\AgentBase\development\skill-routing\build_behavior_inputs.ps1' -ProjectRoot 'D:\program\AgentBase'
```

评估结果必须回传候选 bundle 哈希和输入哈希；候选文件或测试请求变化后，旧结果会自动失效：

```powershell
& 'D:\program\AgentBase\development\skill-routing\validate_behavior_results.ps1' -ProjectRoot 'D:\program\AgentBase' -ResultsPath 'D:\program\AgentBase\development\skill-routing\evidence\2026-08-10-skill-audit-remediation-blind-route.json'
```

2026-08-10 的只读盲测覆盖 37/37 场景并通过必选、禁选、治理参考和行为标签约束，原始结果保存在 `development/skill-routing/evidence/2026-08-10-skill-audit-remediation-blind-route.json`。该证据对应候选 bundle `0463854F738485F9DC22054F9C08AF7F05B8D80BDD6A0389FC38F637F789EAD0` 和输入集合 `4C31F3FE0BA51F9F0481DCC5B8126634392A0362712DD34F8CF4CBA7748A0279`；候选文件或测试请求变化后必须重新生成盲测输入和证据。旧 evidence 文件仅作为历史快照保留。

## 本地插件打包

`development/plugin-packaging/template/agentbase-core` 是由官方插件脚手架生成并审查后的模板。构建脚本从 `skills/` 真源复制 12 个 skill 到忽略的 `dist/agentbase-core`，生成逐文件哈希清单，并调用官方插件校验器：

```powershell
& 'D:\program\AgentBase\development\plugin-packaging\build_plugin.ps1' -ProjectRoot 'D:\program\AgentBase'
```

插件不包含 `global/AGENTS.md`，因为全局规则不属于插件 skill 目录；也不修改个人 marketplace。构建产物是可重建输出，不得反向编辑为真源。

## 可移植 Codex 工作流

`global/config.toml` 保存当前工作流中可跨机器复用的模型、推理强度、人格、服务层级、sandbox、多代理、hooks 和桌面偏好。它明确排除认证、项目 trust 路径、插件/marketplace 缓存、MCP 绝对路径、hook 信任哈希、宿主生成的 `notify`/`node_repl`、历史、日志和秘密。

`global/hooks.template.json` 保存全局事件记录与按工作区显式开启的 QQ 完成提醒 hook；部署时只把 `{{CODEX_ROOT}}` 解析为用户明确指定的 Codex 根目录。新机器必须通过 `/hooks` 审查并信任实际命令，项目不复制旧机器的信任哈希。

`global/agents/` 保存 `luna`、`sol`、`terra` 三个当前自定义子代理角色。每个文件独立声明角色名、用途、模型和开发者指令；未重复声明的推理强度继续继承 `global/config.toml` 的 `[agents]` 默认值。部署只管理这三个同名文件，不替换目标机器的整个 `agents/` 目录。

复制仓库到另一台 Windows 机器后的完整准备、独立插件/MCP 前置条件和恢复边界见 [`development/codex-deployment/README.md`](development/codex-deployment/README.md)。

## 校验、发布与回滚

部署入口默认校验全局规则、12 个 skill、可移植设置、hooks 模板、自定义子代理和 MCP 独立发布入口：

```powershell
& 'D:\program\AgentBase\development\codex-deployment\manage_agentbase.ps1' -Action Validate -ProjectRoot 'D:\program\AgentBase'
```

只有用户明确决定加载时，才对精确指定的 Codex 根目录执行发布。默认发布会先在目标目录内分阶段复制和校验，再把原 `AGENTS.md` 与 12 个同名 skill 移入带清单的备份；不会修改其他 skill、`config.toml`、`hooks.json`、`agents/`、插件 marketplace 或 MCP：

```powershell
& 'D:\program\AgentBase\development\codex-deployment\manage_agentbase.ps1' -Action Publish -ProjectRoot 'D:\program\AgentBase' -CodexRoot 'C:\Users\gzxt\.codex'
```

在新机器上显式选择 `-InstallPortableSettings` 时，同一发布事务还会备份并替换 `config.toml`、`hooks.json` 与三个同名自定义子代理文件；目标机器的其他 agent 保持不变，省略该开关继续保持默认边界：

```powershell
& 'D:\program\AgentBase\development\codex-deployment\manage_agentbase.ps1' -Action Publish -ProjectRoot 'D:\program\AgentBase' -CodexRoot 'C:\Users\gzxt\.codex' -InstallPortableSettings
```

回滚要求精确备份路径，并默认拒绝覆盖发布后又被修改的安装文件；确需接受漂移时必须显式传入 `-AllowInstalledDrift`。当前版本会把被撤回的发布内容保存在备份目录的 `retired-*\` 下：

```powershell
& 'D:\program\AgentBase\development\codex-deployment\manage_agentbase.ps1' -Action Rollback -ProjectRoot 'D:\program\AgentBase' -CodexRoot 'C:\Users\gzxt\.codex' -BackupPath '<exact-backup-path>'
```

发布和回滚已在 `development/codex-deployment/sandbox/` 的假 Codex 根目录完成往返验证：原全局文件和旧 skill 被恢复，发布时新增的 skill 被移除，无关用户 skill 保持不变；发布后漂移会默认阻断回滚，显式接受漂移时被撤回内容仍保存在 `retired-*\`。沙箱不代表真实 Codex 已加载。

## 当前发布状态

- 最近一次已安装到 `C:\Users\gzxt\.codex` 的版本，其 `source_bundle_sha256` 为 `95FB7BA6A0AF0D812E0E10E8A5E1694D9AA8977FCE269E4E4F1C2EDC0725FA2C`；对应回滚备份位于 `C:\Users\gzxt\.codex\backups\AgentBase-20260810-134007-79dd2f52\`。该版本安装了当时的候选全局规则与 12 个同名 skill，但未使用 `-InstallPortableSettings`，因此没有替换 `config.toml`、`hooks.json` 或 `agents/*.toml`。
- 项目真源中的当前候选已在本地通过验证，但尚未发布或装载到 Codex。安装副本不是项目真源；只有用户明确决定加载后才运行正式发布入口。Codex 当前运行也不会追溯重建启动时的指令链，新任务或重启后的会话才会发现已发布的新规则与 skill。
