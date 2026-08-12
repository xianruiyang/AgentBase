# AgentBase

本项目集中维护候选全局 `AGENTS.md`、可移植 Codex 关键设置与自定义子代理、关键 skill、对应开发工程以及实际依赖的 MCP/CLI。所有改动先进入本目录真源，通过静态合同、盲测和隔离发布验证后，再由用户明确决定是否发布到 Codex。

## 真源与安装副本

- `global/AGENTS.md` 是全局规则候选真源，不自动覆盖 Codex 用户目录。
- `global/config.toml` 是经过筛选的可移植 Codex 设置真源；`global/hooks.template.json` 是按目标 Codex 根目录解析的 hooks 真源；`global/agents/*.toml` 是自定义子代理真源。它们都不会因文件存在而自动覆盖用户配置。
- `skills/<skill-name>/` 是已迁入 skill 的唯一开发真源。
- `.agents/plugins/marketplace.json` 是仓库级 `agentbase-core` 插件发现入口，只指向可重建的本地打包产物，不复制 skill 真源。
- `mcp/<mcp-name>/` 是 skill 所依赖 MCP 的开发与发布真源。
- `tools/<tool-name>/` 是 skill 捆绑或调用的非 MCP 工具开发真源。
- `development/<name>/` 只承载验证、打包、部署和不随 skill 安装的开发资料。
- 由部署入口显式传入的 `<CodexRoot>` 中，`AGENTS.md`、同名 skill、`config.toml`、`hooks.json` 与 `agents/*.toml` 都是安装目标或宿主状态，不反向定义本项目。
- 原工程目录只作为迁移来源保留，不自动双向同步；缓存、测试输出和构建产物不属于真源。

## 当前全局内核

`global/AGENTS.md` 只保留跨项目都成立的目标、证据、授权、工具路由、修改、验证、记录和交付规则。复杂根因、职责/入口迁移、共享门禁和跨契约审计细节由 `change-governance` 承担；C++、PowerShell、搜索、符号/AST、空间、任务表和动态推理协议由对应 skill 承担。

当前候选受 20 KiB 单文件静态合同约束，`global/config.toml` 显式设置 `project_doc_max_bytes = 65536`。合同还要求本项目的候选全局规则与根项目规则合计不超过 28 KiB，因此即使目标主机尚未安装可移植配置，也会在 Codex 默认 32 KiB 上限下保留至少 4 KiB 余量。全局文件只承担跨项目目标、证据、授权、路由和交付内核，完整交付链与执行协议分别收敛到对应 skill。当前内核收敛为四项核心约束：

- 规范来源用于确定目标契约，有效证据用于判断系统现状与实现结果；两者不得互相替代，用户目标也不得被系统现状静默改写。
- 在用户目标和授权范围内按长期净收益与系统总成本选择方案；长期收益不得用于扩大范围或替用户裁决。
- 不自动把实现收缩成最窄局部补丁；为使用户要求成立并接入唯一正式入口而不可缺少的调整属于本次实现，仅改善整体架构但不影响本次结果的调整需要另行授权。
- 用户未固定深度时，在 active Goal 内按下一段工作的真实不确定性、后果、可逆性和验证负担自由升降 next-turn 推理深度；不绑定任务项边界，不用 hook 或持久状态模拟续跑。

## 已迁入的 skill

| Skill | 迁移来源 | 当前职责 |
| --- | --- | --- |
| `codex-event-logger` | 历史独立 logger 工程 | 只在上下文缺失或用户要求追溯时读取项目级运行记录 |
| `codex-qq-hook` | 历史 QQ bot 工程 | 按用户明确要求配置当前工作区 QQ 完成提醒 |
| `delivery-workflow` | 项目内建立 | 组织受保护需求与用户设计、可修订模型设计、现状、方案、任务和执行反馈；最终只按当前范围用户基线复核 |
| `task-table-manager` | 项目内建立 | 用低 Token 管理任务合同、三类依赖、多人状态、结果摘要、上下文包和最终复核候选证据，不签发执行或产品通过 |
| `reasoning-governor` | 从 `task-table-manager` 的线程深度脚本拆分建源 | 读取和切换当前线程 next-turn 推理深度；模型自主切换只由 active Goal 续跑 |
| `symbol-structure-workflow` | 历史 SymbolStructureWorkflow 工程 | 在文本、AST、LSP 和编辑工具间分层路由，并声明 `vscode-lsp-mcp` 依赖 |
| `ast-grep-token-safe` | 历史 SymbolStructureWorkflow 工程 | 使用内置 `sgy` 做 Token-Safe AST 搜索与改写 |
| `rg-token-safe` | 已审查规则迁入 | 有界、可定位、低重复的正文搜索 |
| `fd-usage` | 已审查规则迁入 | 有界文件/目录发现，区分 pattern、path 和对象类型 |
| `powershell-usage` | 已审查规则迁入 | 以 PowerShell 7 为基线的 Windows 命令、路径、编码与退出码规则 |
| `change-governance` | 全局条件性治理规则拆分建源 | 复杂根因、职责/入口、迁移、共享门禁和跨契约审计 |
| `cpp-engineering-rules` | 已审查规则迁入 | C++ 职责、公开接口、include、PCH 与 unity build |
| `understand-space` | 历史 UE 项目 skill | 只在正确性依赖空间关系、布局或坐标转换时规范化空间意图 |

## 开发工程与依赖边界

| 目录 | 对应 Skill | 职责 |
| --- | --- | --- |
| `mcp/vscode-lsp-mcp` | `symbol-structure-workflow` | MCP server、VS Code companion、共享协议、安全组件、测试与独立发布工程 |
| `tools/sgy` | `ast-grep-token-safe` | 构建 skill 内置 `sgy` 的 Rust workspace、测试、fuzz、安装与发布工程 |
| `development/codex-event-logger` | `codex-event-logger` | hook 设计资料；正式运行脚本仍在 skill 真源 |
| `development/codex-qq-hook` | `codex-qq-hook` | Webhook 辅助程序和开发说明；正式运行脚本仍在 skill 真源 |
| `development/skill-routing` | 全局规则与全部关键 skill | 静态触发合同、盲测输入生成与结果判定 |
| `development/plugin-packaging` | 合同声明的全部 skill | 生成经过滤的 `agentbase-core` 本地插件包及插件内 hooks |
| `development/codex-deployment` | 全局规则、可移植设置、hooks、自定义子代理与全部关键 skill | 校验、可选设置安装、带备份发布和可验证回滚 |

`vscode-lsp-mcp` 保持独立发布真源：它已有 `release:build` 和 `release:verify`，且还包含 VS Code companion 与安装生命周期。插件包不复制 MCP，也不创建第二套安装入口；`symbol-structure-workflow/agents/openai.yaml` 只声明对 `vscode-lsp-mcp` 的工具依赖。旧的 `vscode-mcp` 与 `ast-mcp` 不属于当前权威依赖。

skill 内置的 Windows/Linux `sgy 0.1.0` 由同一个不含 `.git`、`target/` 和 `dist/` 的源码快照生成。`scripts/runtime-manifest.yml` 记录安装二进制 hash，`scripts/provenance/release-record.json` 汇总源码 revision、Cargo.lock、两平台原生 manifest、归档校验和、构建环境和 RustSec 结果；静态合同会把这些记录与实际文件逐项读回，不再只信任手工填写的 hash。

许可按组件独立生效：`mcp/vscode-lsp-mcp` 使用 Apache-2.0，`tools/sgy` 使用 MIT OR Apache-2.0。仓库根目前没有统一 `LICENSE`，因此不能把组件许可证外推为整个 AgentBase 的授权；对外整体分发前仍需由权利人明确选择根级许可证。

## 路由与行为验证

`development/skill-routing/trigger-cases.json` 中全部关键 skill 都至少有一个正向触发和一个相近非触发场景，并额外覆盖事实冲突、只读授权、长期收益、禁止越权替代执行、active Goal 内动态推理切换、显式线程设置、QQ 只读状态与故障排查、受保护用户基线、最终完成边界，以及三类架构边界：职责与入口已知时直接集成、未知时先治理裁决、一次性产物不得升级为架构工程。

静态合同会检查全局文件大小与关键语义、规则标签、重复规则、skill frontmatter、`agents/openai.yaml`、MCP 依赖、Markdown 相对引用、场景集合和正/负覆盖：

```powershell
& '.\development\skill-routing\validate_contract.ps1' -ProjectRoot (Get-Location).Path
```

盲测输入生成器只暴露请求、候选规则和允许的行为标签，不暴露期望技能或禁选技能。候选哈希只覆盖评估器实际读取的全局规则、各 skill 的 `SKILL.md` 与 `agents/openai.yaml`，不会被测试缓存或其他未评估的运行产物扰动：

```powershell
& '.\development\skill-routing\build_behavior_inputs.ps1' -ProjectRoot (Get-Location).Path
```

评估结果必须回传候选 bundle 哈希和输入哈希；候选文件或测试请求变化后，旧结果会自动失效：

```powershell
& '.\development\skill-routing\validate_behavior_results.ps1' -ProjectRoot (Get-Location).Path -ResultsPath '.\development\skill-routing\evidence\<result>.json'
```

`development/skill-routing/evidence/` 中已有结果只作为对应候选哈希的历史快照。修改候选规则、skill 内容或请求集合后必须重新生成输入并取得独立评估结果；验证器会拒绝把旧结果当成当前候选证据。

`development/skill-routing/evidence/current.json` 是正式发布门禁使用的唯一当前证据入口。评估器不得读取 `trigger-cases.json` 中的隐藏期望；`manage_agentbase.ps1 -Action Validate`、`Publish` 与 CI 都会重新核对候选哈希、输入哈希、用例完整性、期望项和禁选项。候选与输入指纹先把文本换行规范化为 LF，因此同一 Git 内容在 CRLF/LF 工作树中保持同一证据身份。额外选择保持非阻断告警，因为当前合同只把明确期望和明确禁止定义为发布 oracle。

## 本地插件打包

`development/plugin-packaging/template/agentbase-core` 是由官方插件脚手架生成并审查后的模板。构建脚本与部署入口共用 `development/common/payload_contract.ps1`，只复制合同声明的 skill，排除缓存、日志、依赖树、构建目录和临时文件；产物还包含以 `${PLUGIN_ROOT}` 定位的事件记录与 QQ hooks、无宿主绝对路径的逐文件哈希清单，并默认调用官方插件校验器：

```powershell
& '.\development\plugin-packaging\build_plugin.ps1' -ProjectRoot (Get-Location).Path
```

仓库级 marketplace 位于 `.agents/plugins/marketplace.json`，指向忽略的 `development/plugin-packaging/dist/agentbase-core`。构建后可从 `agentbase-local` 安装 `agentbase-core`；项目不会改写个人 marketplace。构建清单显式记录 `official_plugin_validation`。CI 使用 `-SkipOfficialValidation` 和显式隔离的 `-OutputRoot` 只验证可移植的复制、清理、结构和清单合同；该开关不得写入 marketplace 指向的默认 `dist`，正式交付前仍必须在具备系统 `plugin-creator` 的环境运行默认命令通过官方校验。

插件是多 skill 复用分发的推荐入口。它不包含 `global/AGENTS.md`，因为全局规则不属于插件 skill 目录；构建产物是可重建输出，不得反向编辑为真源。同一 Codex 环境不得同时启用插件 skill 与 `DirectCompatibility` 安装的同名 skill，否则选择器和 hooks 都可能重复。

## 可移植 Codex 工作流

`global/config.toml` 保存当前工作流中可跨机器复用的模型、人格、服务层级、sandbox、多代理、hooks、项目指令预算和桌面偏好。主线程以 `medium` 作为普通任务的平衡起点，active Goal 可按全局治理规则升降到包括 `max` 在内的支持等级；子代理只设置默认模型，不统一钉死推理深度。该文件明确排除认证、项目 trust 路径、插件/marketplace 缓存、MCP 绝对路径、hook 信任哈希、宿主生成的 `notify`/`node_repl`、历史、日志和秘密。

`global/hooks.template.json` 保存全局事件记录与按工作区显式开启的 QQ 完成提醒 hook；部署时只把 `{{CODEX_ROOT}}` 解析为用户明确指定的 Codex 根目录。新机器必须通过 `/hooks` 审查并信任实际命令，项目不复制旧机器的信任哈希。

`global/agents/` 保存 `luna`、`sol`、`terra` 三个当前自定义子代理角色。每个文件独立声明角色名、用途、模型和开发者指令；推理深度不在全局子代理默认值中固定，由模型默认或显式调度参数决定。部署只管理这三个同名文件，不替换目标机器的整个 `agents/` 目录。

复制仓库到另一台 Windows 机器后的完整准备、独立插件/MCP 前置条件和恢复边界见 [`development/codex-deployment/README.md`](development/codex-deployment/README.md)。

PowerShell 7、支持 `--max-results` 的 `fd`、Python 3.11+、Node.js `>=22.9 <27` 与已精确验证的 ast-grep 0.44.1 是主机前置条件，不随 Codex 或本项目 payload 复制。用户要求在新 Windows 主机复现或部署本项目时，Codex 会先调用 `development/codex-deployment/bootstrap_windows.ps1 -Action Install` 主动补齐并读回验证，再在新任务中继续发布；普通开发和只读审查不会触发主机软件安装。

## 校验、发布与回滚

仓库级持续验证入口是 [`.github/workflows/validate.yml`](.github/workflows/validate.yml)：Windows 项目合同 job 覆盖部署与 skill 回归测试，`vscode-lsp-mcp` job 执行完整 Windows 发布门禁，`sgy-windows` job 执行 Windows 原生构建、已签署运行时完整性检查、真实 ast-grep smoke 和 RustSec。CI 是持续门禁，不替代本地发布前对当前工作区执行的最小充分验证。

部署入口默认校验全局规则、合同声明的全部 skill、当前盲测证据、可移植设置、hooks 模板、自定义子代理和 MCP 独立发布入口：

```powershell
& '.\development\codex-deployment\manage_agentbase.ps1' -Action Validate -ProjectRoot (Get-Location).Path
```

只有用户明确决定加载时，才对精确指定的 Codex 根目录执行发布。推荐的插件模式只管理全局 `AGENTS.md`；显式选择可移植设置时再管理 `config.toml` 与三个自定义子代理，skill 与 hooks 由已安装的 `agentbase-core` 插件承担：

```powershell
& '.\development\plugin-packaging\build_plugin.ps1' -ProjectRoot (Get-Location).Path
codex plugin add agentbase-core@agentbase-local
& '.\development\codex-deployment\manage_agentbase.ps1' -Action Publish -ProjectRoot (Get-Location).Path -CodexRoot (Join-Path $env:USERPROFILE '.codex') -SkillDeliveryMode Plugin -InstallPortableSettings
```

部署入口不安装、启用或检查插件；插件安装状态必须通过插件目录或 `codex plugin list` 单独验证。启用插件 hooks 前仍需审查并信任。`Plugin` 模式不会写入 `hooks.json`，避免与插件内 hooks 形成双入口。

现有主机尚未迁移插件时，可以显式使用兼容模式。它会把 skill 安装到旧版仍支持的 `<CodexRoot>/skills`，选择可移植设置时同时安装全局 `hooks.json`：

```powershell
& '.\development\codex-deployment\manage_agentbase.ps1' -Action Publish -ProjectRoot (Get-Location).Path -CodexRoot (Join-Path $env:USERPROFILE '.codex') -SkillDeliveryMode DirectCompatibility -InstallPortableSettings
```

`DirectCompatibility` 只服务已存在的直接安装；当目标主机完成插件安装、启停、hook 信任、卸载/回滚验证后应迁移到 `Plugin`，且迁移前先移除或回滚直接安装的同名 skill 与 AgentBase 全局 hooks。`Plugin` 发布会在写入前检查这些遗留入口并拒绝双轨状态。兼容模式不是新的 skill 真源，也不允许与插件并行决定同一行为。

回滚要求精确备份路径，并默认拒绝覆盖发布后又被修改的安装文件；确需接受漂移时必须显式传入 `-AllowInstalledDrift`。当前版本会把被撤回的发布内容保存在备份目录的 `retired-*\` 下：

```powershell
& '.\development\codex-deployment\manage_agentbase.ps1' -Action Rollback -ProjectRoot (Get-Location).Path -CodexRoot (Join-Path $env:USERPROFILE '.codex') -BackupPath '<exact-backup-path>'
```

发布和回滚已在 `development/codex-deployment/sandbox/` 的假 Codex 根目录完成往返验证：原全局文件和旧 skill 被恢复，发布时新增的 skill 被移除，无关用户 skill 保持不变；发布后漂移会默认阻断回滚，显式接受漂移时被撤回内容仍保存在 `retired-*\`。沙箱不代表真实 Codex 已加载。

## 当前发布状态

发布状态不再手工写在 README。使用只读 `Status` 按所选分发范围比较当前项目指纹、已安装指纹、最近处于 `published` 状态的清单和清单记录的盲测证据：

```powershell
& '.\development\codex-deployment\manage_agentbase.ps1' -Action Status -ProjectRoot (Get-Location).Path -CodexRoot (Join-Path $env:USERPROFILE '.codex') -SkillDeliveryMode DirectCompatibility -InstallPortableSettings
```

只有 `managed_payload_formally_published=true` 才表示该范围内的受管文件与当前候选、正式发布清单和当前盲测证据一致。`Plugin` 模式还会返回 `plugin_mode_ready` 与 `direct_compatibility_conflicts`；存在旧直装 skill 或 AgentBase 全局 hooks 时不会报告正式发布成立。该状态只覆盖部署脚本管理的全局文件与可选设置，明确不证明插件本身已经安装或启用。任何项目修改只有在用户明确要求加载、对应 `Publish` 成功并开启新任务后才会进入 Codex 指令链；项目验证和 Git 同步不会隐式改写安装副本。
