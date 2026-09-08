# AgentBase Evo 现状与源码研究

本文件供方案维护者复核选型与适配依据；只记录会改变方案的事实，不保存真实题目、原始对话或逐题答案。研究日期为 2026-09-09。第三方版本与恢复方式由 [sources.json](../../../development/references/sources.json) 和[参考目录说明](../../../development/references/README.md)维护。第三方部分为静态源码审查；Evo 实施证据单独声明观察范围。

## OBS-001 AgentBase 已有逐题执行与独立验证底座

- 状态: confirmed
- 来源: [评测 README](../../../development/agent-evaluation/README.md)、`agent_eval.py` 的 `command_run` / `command_recover`

Windows SWE 入口已有固定 corpus/task/base/依赖身份、独立 candidate/verifier 工作区、受限 patch、逐题资格、attempt 和不可变收据、锁与恢复。`recover` 复用候选产物，只恢复 Verifier，不重跑模型；真实题库和评测结果留本机。模型成本包括候选及其后代，分别报告 reward、覆盖、成本与基础设施健康。

这些机制适合复用为优化循环的单次执行后端。现有资格与 DeepSWE grader 只适用于原逐题合同，不能要求任意 hook 或主观输出也采用 no-op=0/reference=1 的资格方式。

## OBS-002 旧 SWE 默认投影不能表达任意指定组合

- 状态: confirmed
- 来源: [agentbase_codex.py](../../../development/agent-evaluation/agentbase_codex.py) 的 `candidate_capability_contract`、`stage_candidate_skill_projection`、`stage_candidate_codex_projection`、`candidate_runtime_tools`；[evaluation_core.py](../../../development/agent-evaluation/evaluation_core.py) 的 `candidate_surface_identity`

当前来源身份固定包含 `global/AGENTS.md`、`global/config.toml`、`global/agents`、`skills`；skill 投影复制完整来源目录，角色和 multi-agent 被要求启用。配置投影将全局 AGENTS 内容写入 `developer_instructions`，强制关闭 hooks/web search。工具运行身份从当前宿主解析，并非从每个候选构建工具后切换到对应产物。

源码明确把 hooks、host MCP、宿主插件、安装和发布列在 SWE 覆盖之外。因此“改了工具源码后 SWE 得分改善”不能自行证明候选工具被实际使用；必须增加组合解析、构建产物绑定及实际运行观察。

## OBS-003 路由、hooks 和 MCP 已各有专项职责

- 状态: confirmed
- 来源: [路由 README](../../../development/skill-routing/README.md)、[global README](../../../global/README.md)、[hooks 模板](../../../global/hooks.template.json)、[MCP README](../../../mcp/vscode-lsp-mcp/README.md)、[MCP 验证说明](../../../mcp/vscode-lsp-mcp/docs/development.md)

路由研究已经维护三阶段可见输入、隐藏期望、增量身份和尝试复用，但只证明选择与粗粒度行为，不证明 skill 执行。当前同输入失败不能换一个周期标识就反复采样。

hooks 模板包含 SessionStart、UserPromptSubmit、Stop、PreToolUse、PostToolUse，脚本归相关 skill。部分 hook 依赖桌面线程状态或外部通知。MCP 通过 stdio server 和 VS Code companion 消费真实语言 Provider；单元测试、Extension Host 验证与发布验证是不同入口。CLI 配置、脚本单测和 MCP schema 都不能单独证明真实宿主加载并调用了相应能力。

## OBS-004 Anthropic Skill Creator 适合借鉴局部评估与人工反馈

- 状态: confirmed
- 来源: 固定检出 `anthropic-skills`；[描述循环](https://github.com/anthropics/skills/blob/41bbe19d1a1a/skills/skill-creator/scripts/run_loop.py#L67)、[触发执行](https://github.com/anthropics/skills/blob/41bbe19d1a1a/skills/skill-creator/scripts/run_eval.py#L45)、[人工反馈协议](https://github.com/anthropics/skills/blob/41bbe19d1a1a/skills/skill-creator/SKILL.md#L221)

`run_loop.py` 执行描述生成和触发评估；优化模型只收到 train 历史，但每轮都评估 train/test，最终按 test 选最佳描述。因此该 test 实际承担选优验证集职责，不是最终独立测试。`run_eval.py` 创建临时 Claude command，通过 `claude -p` 的 Skill/Read 事件判定触发，不验证 skill 任务结果；实现使用 `select.select` 读取子进程管道，不能未经 Windows 验证直接移植。

正文执行、grader、A/B comparator 与 analyzer 主要通过 skill 文档组织。viewer 支持保存反馈，但没有与 AgentBase attempt 身份绑定的人工裁决协议。文档把空反馈解释为满意，这不适合必需人工验收。描述循环有轮数/单次超时限制，缺少 AgentBase 所需的全链路 Token 预算和持久执行恢复。

可借鉴：有/无 skill 对照、逐项证据评分、盲比、输出审阅和针对失败的泛化改写。不能直接当作 Evo 多组件组合的现成运行时。

## OBS-005 EvoSkill 提供实际候选搜索与版本选择

- 状态: confirmed
- 来源: 固定检出 `EvoSkill`；[主循环](https://github.com/sentient-agi/EvoSkill/blob/36f6f0495229/src/loop/runner.py#L220)、[数据划分](https://github.com/sentient-agi/EvoSkill/blob/36f6f0495229/src/api/data_utils.py#L32)、[Codex 成本字段](https://github.com/sentient-agi/EvoSkill/blob/36f6f0495229/src/harness/codex/executor.py#L186)、[技能发现](https://github.com/sentient-agi/EvoSkill/blob/36f6f0495229/src/harness/codex/skill_discovery.py#L17)

实际循环按类别采样训练失败，提出并生成修改，在固定验证集上评分，以 Git 版本维护有限 frontier；有最大轮数、连续无改进停止及采样 checkpoint。checkpoint 保存迭代号与采样偏移，不是完整尝试、用量与进程恢复。主循环的候选可保留为父代，不必每次从原始版本开始。

现有 skill/prompt mutation 范围比 Evo 多组件及其构建、宿主生命周期窄。Codex adapter 将 `duration_ms`、`total_cost_usd` 设为 0、`usage` 设为空；这些占位不能用于 AgentBase 的成本比较。其技能发现使用 `.agents/skills` 指向 `.claude/skills` 的符号链接，不等价于项目现有 Windows 受控投影。当前划分函数返回 train 与 validation，主循环反复用 validation 选优；独立最终验收需要另行设计。

可借鉴：失败驱动提案、候选谱系、有限版本保留、恢复采样状态。评分函数、成本字段、Git 工作区切换和宿主适配不能整体接管 AgentBase。

## OBS-006 AutoSkill 提供经验维护与有限候选晋升

- 状态: confirmed
- 来源: 固定检出 `AutoSkill`；[维护决策](https://github.com/ECNU-ICALK/AutoSkill/blob/94c47ca488d4/autoskill/management/maintenance.py#L689)、[SkillEvo 循环](https://github.com/ECNU-ICALK/AutoSkill/blob/94c47ca488d4/SkillEvo/runner.py#L41)、[晋升](https://github.com/ECNU-ICALK/AutoSkill/blob/94c47ca488d4/SkillEvo/runner.py#L270)、[规则编译](https://github.com/ECNU-ICALK/AutoSkill/blob/94c47ca488d4/SkillEvo/evals.py#L27)

维护层有 add/merge/discard、相似能力检查、身份与版本保留。SkillEvo 从在线/离线 provenance 构建 replay，划分 mutate_dev/promotion_test，评估有限候选并比较 champion；样本不足不晋升。晋升写到自身 champions/registry，不自动回写主 SkillBank，README 也明确该 MVP 边界。

其 eval compiler 从 skill 内容与需求统计启发式生成引用、段落、JSON 等规则；适合发现评分候选，不能作为独立目标权威。LLM judge 缺失或解析异常返回 false，会将评分设施异常与行为失败混在布尔结果中；AgentBase 需要独立 unavailable/error 状态。其能力相似度也不足以证明两个 AgentBase owner 应合并。

可借鉴：经验先筛选再形成修改、允许合并/丢弃、候选与正式内容分开。初版不引入常驻个人 SkillBank、在线代理、检索层或自动采集用户全部会话。

## OBS-007 许可证与研究范围

- 状态: confirmed
- 来源: `EvoSkill/LICENSE`、`anthropic-skills/skills/skill-creator/LICENSE.txt`、`AutoSkill/README.md` 与根文件列表

EvoSkill 和 Anthropic 的目标 skill 附带 Apache-2.0 文本。AutoSkill README 有 MIT 标记，但本次未在顶层找到对应完整许可证文件；其 SkillBank 中还包含其他来源及许可证，不能从根标记推断全树许可一致。

本轮未复制第三方实现到 AgentBase 运行代码。若后续决定复制模块，须按实际文件确认声明、依赖和许可证；当前方案只采用经过说明的机制，不把许可证判断升级为实施授权。

## OBS-008 代码读取评测已有成本观测与有界环境准备合同

- 状态: confirmed
- 来源: [代码读取评测说明](../../../development/code-search-benchmark/README.md)、[局部 Token 分析器](../../../development/code-search-benchmark/analyze.py)、[查询网关研究说明](../../../development/source-query-gateway/README.md)

局部分析器对命令、模型可见结果和读取的 skill 文本使用 `o200k_base` 计数，输出逐项 Token、每目标 Token 及路线中位数；只接受 `evidenceComplete=true` 的记录。其输入合同要求完整计入失败、回退和首次 skill 加载。真实模型实验另记录请求级/累计用量、缓存、压缩、工具事件与耗时；累计更新不能重复求和，局部文本计数也不等同 API 用量。价格按冻结来源计算，输入字段不足时不能推导精确缓存收益。

环境准备由 `prepare_benchmark_homes.py` 统一承担；说明已要求不变环境复用、选择受管资产、复制前估算与检查空间，禁止按题/语言/重复克隆不变 home，以及使用硬链接共享可变规则。现有 64 MiB/4096 项限制是该准备入口的单批预算，不能当作 Evo 的总磁盘上限。代码读取实验的单模型、运输协议和服务档位限制具有特定研究范围，不直接成为 Evo 七类组合的通用运行配置。

上述是可借鉴的既有合同和局部实现依据，未证明 Evo 已具备跨研究排队、共享资源调度、环境池或统一进度监控。

## OBS-009 已有动作审计与运行事件，但并非完整行为追踪

- 状态: confirmed
- 来源: [会话审计合同](../../../skills/codex-event-logger/references/session-audit.md)、[代码读取实验解析](../../../development/code-search-benchmark/experiment.py) 的 `normalize_app_server_item` / 事件汇总、[候选用量解析](../../../development/agent-evaluation/agentbase_codex.py) 的 `_parse_candidate_rollout` / `candidate_agent_usage_receipt`；2026-09-09 查阅 [Codex App Server 官方文档](https://learn.chatgpt.com/docs/app-server#events)

会话审计已支持创建/复用/消息/等待/工具/文件/输入/公开进度/压缩的有界时间线，并明确扫描完整不代表宿主记录了全部行为；下一层代理须读取相应子会话。代码读取实验解析开始/完成事件、命令/MCP 等 item 和用量；SWE 用量解析保留代理关系、来源及继承历史边界，聚合后代请求成本。这些职责可复用，但不是 Evo 全流程追溯的现成实现。

官方文档描述线程、turn、item、命令、文件修改、MCP、协作调用和用量等事件；同步 hook 有开始/完成通知，异步 hook 不发同类通知。文档当前列 `collabToolCall`，本地代码识别 `collabAgentToolCall`，说明必须按实际宿主版本验证解析映射，不能只按一种名称宣称协作事件齐全。文档证明接口设计，不能证明本机每条路径已经发出或采集了这些事件。

模型内部决策、工具内部每次文件读取和外部系统全部副作用不由上述事件单独证明；公开计划、工具结果、执行回执和实际读回各有证据范围。缺失来源不补造历史，也不把本轮静态审查说成完成了真实追溯验证。

## OBS-010 原评测结果不允许任意综合分

- 状态: confirmed
- 来源: [evaluation_core.py](../../../development/agent-evaluation/evaluation_core.py) 的结果校验；[agent_eval.py](../../../development/agent-evaluation/agent_eval.py) 的报告生成

现有结果校验要求 assessment.composite_score 为 null，reward 使用原任务合同的范围；报告同样保持 composite_score=null，并不将结果声明为排行榜可比。Evo 自定义评分需保留为引用原事实的派生结果，不能把新公式填入旧字段而改变既有收据语义。

## OBS-011 Evo 首个消费者与当前接入边界

- 状态: confirmed
- 来源: [离线评分测试](../../../development/agent-evaluation/tests/test_evo_offline.py)、[运行测试](../../../development/agent-evaluation/tests/test_evo_runtime.py)、[适配器](../../../development/agent-evaluation/evo/codex_adapter.py)

离线评分已由实际 artifacts 完成多套公式计算与来源追溯；本地 command 已经过 submit、队列、独占工作区、运行收据、facts 与评分入口，定向验证覆盖暂停取消、收据恢复、跨研究复用和磁盘等待。计算器、人工评分与模型评分共用标准派生 artifacts，原始收据保持原 owner。

首个真实 Codex 消费者采用[合成角色规格](../../../development/agent-evaluation/tests/fixtures/evo/codex-role-research.json)，已实际创建一个 evidence，主代理读取独立输入并等待其回传，答案校验为 1。原始收据分别观察到 Sol 主代理与 Luna evidence，共 187872 Token；原生轨迹包含创建、等待、消息与命令。该场景约 41.5 秒，仅证明此运行链与对应采集能力，不能推导配置优化收益。

用量 owner 已将全历史快照替换为启动时游标与目标谱系筛选，避免无关历史阻断当次统计。启动前失败经明确未调用证据确认、保留 attempt 后恢复，同题没有重复模型调用；未知启动异常不按未调用处理。首场景的实际用量超出作业预留，直接说明预留不是内部请求硬限；后继派发仍受已花总量约束。

人工评审已通过真实 command 作业的等待、部分导入、完整导入、更正及评分接缝，subject 执行次数和原收据不变。独立模型 grader 已实际评分四条合成数据，消耗 24293 Token，合并后可按原 score 入口重算。单 root 的 Codex 配置已通过真实启动；与角色场景分别证明无后代和有后代的配置接入。

[七组件合成场景](../../../development/agent-evaluation/tests/fixtures/evo/components/seven-component-research.json)已同时消费 AGENTS、skill、hook、stdio MCP、候选工具、evidence profile 和 Codex 设置。原生 MCP 结果、公开命令、子代理事件及归档 hook 标记与独立答案一致，共 216528 Token、9 个真实请求，约 81.5 秒。审计 owner 已支持实际 `McpToolCall`，刷新可从已有 rollout 重建，无需重跑模型。

[单轮优化合成场景](../../../development/agent-evaluation/tests/fixtures/evo/optimization/research-codex-controller.json)已由模型修改允许的 AGENTS 文件，经实际 command 消费和独立模型评分晋升；最终集两种判定均为 1，原源码保持不变。controller 与 grader 合计 95316 Token。阶段恢复、patience 即时停止、跨 study 预算与 final 门槛经合成故障测试补齐；已有真实研究 resume/export 后仍为原十个作业和原用量，没有追加调用。该证据证明闭环可运行，不证明真实 AgentBase 内容已提升。

## GAP-001 需要组合级优化，但不需要替换已有逐题评测

- 状态: confirmed
- 关联: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, REQ-010, REQ-011, REQ-012, REQ-013, DES-002, DES-004, DES-005, DES-006, DES-007, DES-008, DES-009, DES-010, OBS-001, OBS-002, OBS-003, OBS-004, OBS-005, OBS-006, OBS-008, OBS-009, OBS-010

原逐题评测不足以承担七类组合与候选演进；新增 Evo 已接入组合选择、队列、独占可复用环境、全代理成本与公开动作、三类评分和候选生成。三个外部项目只提供机制参考，不成为本机运行依赖。旧逐题评测、原 reward 与资格验证职责保留。

OBS-011 的真实消费者已覆盖七类组合与自动循环。正式本地基础设施 160 项测试通过，随后资源与模型读取面定向复核通过；各项需求的完成证据归任务表结果。未声明模型内部请求的 Token 硬限、桌面专属行为全覆盖或内容效果提升，这些边界不由合成成功外推。完成成本的假设和重估方式见 [estimates.md](estimates.md)。
