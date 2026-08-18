# Agent 与 Skill 指令面收敛：现状与证据

## OBS-001 Custom agent 的模型指令面仍是英文通用语义

- 状态: confirmed
- 来源: `global/agents/luna.toml`、`global/agents/terra.toml`、`global/agents/sol.toml`
- 证据上限: 证明当前候选文本、语种和角色差异，不证明真实宿主中的运行行为

三个 agent 的 `description` 与 `developer_instructions` 均使用英文自然语言，且主要重复“保持范围、基于证据、验证、简洁”等全局不变量。Luna、Terra、Sol 只按任务难度粗略分层，没有明确遇到歧义、跨模块职责或深度验证时的升级边界。

## OBS-002 部署 validator 复制了 agent 的完整语义正文

- 状态: confirmed
- 来源: `development/codex-deployment/manage_agentbase.ps1` 的 `Get-ValidatedPortableAgentSources`
- 证据上限: 证明当前源码存在两个必须同步修改的决定位置

`global/agents/*.toml` 名义上是 custom agent 唯一真源，但部署 validator 又硬编码三份完整 description、model 与 developer instructions，并按整行相等拒绝差异。正常修改角色语义必须同步修改部署脚本，形成第二语义 owner。

## OBS-003 任意 taskctl 调用都会加载完整工具协议

- 状态: confirmed
- 来源: `skills/task-table-manager/SKILL.md` 与 `references/tooling.md`
- 证据上限: 证明当前条件引用边界和协议覆盖范围，不单独量化每次真实任务的端到端 Token

当前 SKILL 规定“使用 CLI 时读取 tooling.md”。该引用同时维护 authoring、查询、执行状态、结果提交、来源快照、最终复核、分页、模型投影和全部机械门禁；简单 `show/list/next` 也必须取得与完成写入和最终审计无关的协议。

## OBS-004 taskctl 顶层帮助缺少子命令用途

- 状态: confirmed
- 来源: `skills/task-table-manager/scripts/taskctl.py` 的 argparse 注册
- 证据上限: 证明当前 `--help` 发现面，不证明 skill 正文或具体子命令行为缺失

`taskctl` 注册的子命令没有 `help` 摘要，顶层帮助只显示命令名；同仓库 `workctl` 已为每个子命令提供一句用途说明。

## OBS-005 默认 Luna/max 组合尚无角色质量与成本证据

- 状态: unknown
- 来源: `global/config.toml`、当前部署与路由验证范围
- 证据上限: 证明默认设置存在且当前验证不覆盖 custom agent 运行行为

当前默认子代理为 Luna/max，但现有静态部署检查只证明配置与文件身份，skill 路由评估也不执行 custom agent。没有直接证据支持立即改为其他模型或档位，本轮不改变默认值。

## GAP-001 Custom agent 违反中文模型语义并存在第二 owner

- 状态: confirmed
- 关联: AC-006, CON-002, OBS-001, OBS-002

角色指令未使用项目默认中文语义，部署脚本又复制正文；角色升级边界不清晰且同一事实需要同步维护。

## GAP-002 Task Table Manager 的条件引用没有按当前动作投影

- 状态: confirmed
- 关联: AC-007, AC-041, OBS-003

工具协议已经按命令形成不同消费者，但读取入口仍是单一完整引用，导致未触发细节进入模型上下文。

## GAP-003 taskctl 的最小发现面不足

- 状态: confirmed
- 关联: AC-041, OBS-004

用户或模型在只需确认命令职责时，顶层帮助不能直接区分 authoring、查询、执行和最终复核入口。

## GAP-004 Custom agent 默认策略仍需真实行为证据

- 状态: unknown
- 关联: CON-001, OBS-005

缺少运行时角色选择、结果质量和完整任务成本证据，当前不能可靠判断 Luna/max 是否应调整。
