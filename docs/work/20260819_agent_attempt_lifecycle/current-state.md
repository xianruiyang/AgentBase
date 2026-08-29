# 现状与差距

## OBS-001 原 Agent 配置

- 状态: confirmed
- 证据: 修改前 `global/agents/` 与 `global/config.toml`
- 关联: GAP-001

修改前仓库管理 Luna、Terra、Sol 三个角色；各角色未显式拥有独立推理档位，默认子代理设置统一决定推理档位。

## GAP-001 角色与用户指定档位不一致

- 状态: confirmed
- 关联: OBS-001, DES-001, AC-001, AC-002, AC-003

三角色清单和共享默认档位无法表达用户指定的 Luna/max、Sol/medium 两级设计，Terra 也仍会作为发布资产安装。

## OBS-002 原尝试登记时点

- 状态: confirmed
- 证据: 修改前 `record_routing_attempt.ps1`、`merge_routing_evidence.ps1`、`evidence/attempts.json`
- 关联: GAP-002, GAP-003

原正式入口只有取得结果后才登记，merge 隐式接收三个结果；evaluator 在结果产生前失败时没有 attempt ID 或失败收据。账本把所有运行追加在单个文件中，没有周期级容量上限。

## GAP-002 执行失败可消失

- 状态: confirmed
- 关联: OBS-002, DES-002, AC-004

结果文件产生前的 evaluator 失败无法由正式门禁证明，后续运行可能掩盖该失败。

## GAP-003 活跃账本可无界增长

- 状态: confirmed
- 关联: OBS-002, DES-003, AC-005

每个不变输入的重试上限不能限制候选持续变化后的总文件增长，长期模型与机器读取成本没有明确边界。

## OBS-003 模型名角色与职责、档位耦合

- 状态: confirmed
- 证据: 修改前 `global/agents/luna.toml`、`sol.toml`、`portable_agents.ps1`、全局规则与部署说明
- 关联: GAP-004, DES-004, DES-005

修改前角色身份直接使用模型后缀，validator 进一步要求文件名、角色名和模型后缀一致，并硬编码 Luna/max、Sol/medium。角色正文只区分窄任务与复杂任务，没有静态证据包、主代理接纳、隔离实验和正式实现边界。更换模型或档位需要同时修改角色、validator、测试和文档，主代理也缺少稳定语义入口。

## GAP-004 两类低成本协作不能形成可靠交接

- 状态: confirmed
- 关联: OBS-003, DES-004, DES-005, AC-006, AC-007, AC-008, AC-009

现有配置既不能保证 Luna 证据完整性，也会让 Sol 直接承接复杂实现与裁决；模型身份变化会改变调用名，子代理结果没有逐项接纳和反例熔断，不能在降低成本的同时维持主代理质量责任。

## OBS-004 Codex 子代理触发要求明确请求

- 状态: confirmed
- 证据: 当前 Codex 运行时指令与 OpenAI Subagents 正式文档；修订前 `global/AGENTS.md` 和 `subagent-orchestration`
- 关联: GAP-005, DES-004, DES-005, AC-010

当前本地 Codex 只在用户直接要求，或适用 `AGENTS.md`/skill 请求委派时创建子代理。修订前全局规则只说“仅委派…”，skill 只在主代理已经实际选择、派发时触发；两者定义了允许边界，却没有向 Codex 发出可执行的默认委派请求。

## GAP-005 低成本子代理设计在用户未指定时不会触发

- 状态: confirmed
- 关联: OBS-004, DES-004, DES-005, AC-009, AC-010

只限制“什么情况才可以委派”无法实现用户要求的默认低成本取证与试路；把同一条件改成绝对 `must` 又会在当前边界或成本证据不足时制造不合理创建。缺少的是一条语义明确、但可由现场证据推翻的 `should` 默认请求。

## OBS-005 Experiment 的运行描述把可选输入写成前置条件

- 状态: confirmed
- 证据: 用户对真实模型选择的观察；修订前 `global/agents/experiment.toml`、`subagent-orchestration/SKILL.md` 与 `references/coordination.md`
- 关联: GAP-006, DES-006, AC-011

模型在有初步实现方向且仍适合用实际操作快速取证时没有选择 `experiment`，只在近似全陌生场景考虑它。修订前代理配置要求“只消费已接纳 evidence ID”，skill 以静态证据无法区分候选路径为首要触发，成本规则又把“正式实现本身才是主要工作”整体排除；三者共同把原本的可逆操作实验误缩成静态分析之后的陌生路径试路。

## GAP-006 Experiment 不能覆盖已知方向下的低成本操作取证

- 状态: confirmed
- 关联: OBS-005, DES-006, AC-007, AC-009, AC-010, AC-011

现有触发语义没有以实际操作的信息增益为准，也没有区分“整个任务需要正式实现”与“其中一个操作性问题可独立实验”。因此模型会错过已有方向下确认路径、暴露错误和收敛连续问题的低成本委派机会。

## OBS-006 固定角色在完整历史 fork 下继承主代理配置

- 状态: confirmed
- 证据: UeAgentInterface14 根会话的 `spawn_agent` 调用与对应子线程 `turn_context`；AgentBase 修复提交 `8085259`
- 关联: GAP-007, DES-007, AC-012

UAI14 在规则修复后仍实际用 `fork_turns="all"` 创建过 `evidence` 与 `experiment`，对应子线程均继承主代理的 Sol/high；使用 `fork_turns="none"` 的最近同类创建则分别保持 Luna/medium 与 Sol/low，`operator` 保持 Luna/max。还出现过一个由子代理创建的二级 `experiment`。这直接证明平台调用参数与代理拓扑会改变固定角色的实际运行身份，规则正文存在不足以保证动作合规。

## GAP-007 固定配置和无后代代理没有成为唯一调用路径

- 状态: confirmed
- 关联: OBS-006, DES-007, AC-008, AC-009, AC-012

编排合同虽已禁止 `fork_turns="all"`，但仍允许正整数继承，且角色配置只用抽象“不得继续委派”表达拓扑边界。旧任务因此仍能绕过固定 profile、改用通用角色或创建后代代理；缺少的是无例外的 `none` 参数、capsule-only 上下文和子代理对具体委派入口的停止合同。
