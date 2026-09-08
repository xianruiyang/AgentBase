# AgentBase Evo 现状与源码研究

本文件供方案维护者复核选型与适配依据；只记录会改变方案的源码事实，不保存真实题目、原始对话或逐题答案。研究日期为 2026-09-09。第三方版本与恢复方式由 [sources.json](../../../development/references/sources.json) 和[参考目录说明](../../../development/references/README.md)维护。以下均为静态源码审查，未运行第三方模型、评测、服务或安装器。

## OBS-001 AgentBase 已有逐题执行与独立验证底座

- 状态: confirmed
- 来源: [评测 README](../../../development/agent-evaluation/README.md)、`agent_eval.py` 的 `command_run` / `command_recover`

Windows SWE 入口已有固定 corpus/task/base/依赖身份、独立 candidate/verifier 工作区、受限 patch、逐题资格、attempt 和不可变收据、锁与恢复。`recover` 复用候选产物，只恢复 Verifier，不重跑模型；真实题库和评测结果留本机。模型成本包括候选及其后代，分别报告 reward、覆盖、成本与基础设施健康。

这些机制适合复用为优化循环的单次执行后端。现有资格与 DeepSWE grader 只适用于原逐题合同，不能要求任意 hook 或主观输出也采用 no-op=0/reference=1 的资格方式。

## OBS-002 当前投影不能表达任意指定组合

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

可借鉴：有/无 skill 对照、逐项证据评分、盲比、输出审阅和针对失败的泛化改写。不能直接当作五类组件组合的现成运行时。

## OBS-005 EvoSkill 提供实际候选搜索与版本选择

- 状态: confirmed
- 来源: 固定检出 `EvoSkill`；[主循环](https://github.com/sentient-agi/EvoSkill/blob/36f6f0495229/src/loop/runner.py#L220)、[数据划分](https://github.com/sentient-agi/EvoSkill/blob/36f6f0495229/src/api/data_utils.py#L32)、[Codex 成本字段](https://github.com/sentient-agi/EvoSkill/blob/36f6f0495229/src/harness/codex/executor.py#L186)、[技能发现](https://github.com/sentient-agi/EvoSkill/blob/36f6f0495229/src/harness/codex/skill_discovery.py#L17)

实际循环按类别采样训练失败，提出并生成修改，在固定验证集上评分，以 Git 版本维护有限 frontier；有最大轮数、连续无改进停止及采样 checkpoint。checkpoint 保存迭代号与采样偏移，不是完整尝试、用量与进程恢复。主循环的候选可保留为父代，不必每次从原始版本开始。

现有 skill/prompt mutation 范围比五类组件及其构建、宿主生命周期窄。Codex adapter 将 `duration_ms`、`total_cost_usd` 设为 0、`usage` 设为空；这些占位不能用于 AgentBase 的成本比较。其技能发现使用 `.agents/skills` 指向 `.claude/skills` 的符号链接，不等价于项目现有 Windows 受控投影。当前划分函数返回 train 与 validation，主循环反复用 validation 选优；独立最终验收需要另行设计。

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

## GAP-001 需要组合级优化，但不需要替换已有逐题评测

- 状态: confirmed
- 关联: REQ-001, REQ-002, REQ-003, REQ-004, OBS-001, OBS-002, OBS-003, OBS-004, OBS-005, OBS-006

已有系统缺少显式组合与可变范围、候选构建产物绑定、跨适配器研究编排、人工待评与裁决、开发/选优/最终验收分层，以及跨候选预算和晋升语义。三个外部项目都未直接覆盖 AgentBase 所需的全部内容与 Windows 宿主生命周期。处理方法见 [solution.md](solution.md)，不据此改动现有生产配置或启动评测。
