# 用户目标设计

## UDES-001 采用九题难度分级 Windows 语料

- 状态: confirmed
- 来源: 用户 2026-08-20 接受重新评估后的九题 Python/TypeScript 组合
- 关联: REQ-001, AC-001, AC-002

最终集按 easy、medium、hard、very-hard 分级，保留 smoke、core、rotation 与 all；以后可以根据改动主动逐题选择，而不是每次运行完整集合。

## UDES-002 独立指候选与 Verifier 环境隔离

- 状态: confirmed
- 来源: 用户询问并确认独立代理与 verifier 的含义后要求完善
- 关联: REQ-002, AC-003, AC-004, AC-006

不额外启动一个 subagent 充当裁判。Codex 在候选工作区修改源码，框架只提取 Git patch；确定性 Verifier 在另一份干净工作区应用 patch 和隐藏测试并计分。

## UDES-003 复用已经修好的 Codex 运行条件

- 状态: confirmed
- 来源: 用户指出既有独立测试曾遗漏 \`.env\`、反复重连且边界不足
- 关联: REQ-003, AC-007, AC-008, AC-009

新入口继续使用脱敏 \`.env\` 网络投影、固定 HTTP transport、原生 Codex executable 解析、真实 Windows elevated 权限边界和有限重试/恢复；框架故障、宿主 sandbox 初始化未完成和候选能力失败必须分开，不能通过 weaker fallback 或重采样混写。

## UDES-004 评价服务整体成果但不伪造总分

- 状态: confirmed
- 来源: 用户要求这些任务成为整体项目最终评测集并可用于评价最终成果
- 关联: REQ-004, AC-005, AC-010

Windows SWE reward 是整体证据中的仓库级泛化维度，不覆盖 AgentBase 原生合同、候选能力/权限验收、路由或部署证据，也不冒充官方 DeepSWE 排名；整体入口保留证据向量而不是合成一个分数。

## UDES-005 独立候选使用完整但分层取证的 AgentBase 能力

- 状态: confirmed
- 来源: 用户 2026-08-21 在复核独立 Codex 能力清单后确认“按照你的说法完善好”
- 关联: REQ-002, AC-006

候选应实际发现完整 skill 正文与支持文件，使用 Luna/max、Sol/medium、自定义 subagent 配置以及 srcq 的 rg/fd/scc/AST/分页/machine/artifact 能力，并保留 shell、`apply_patch`、公开测试和题目所需 Windows 工具。无模型权限预检只验证可确定的资产、隔离、身份和 CLI 工作流；subagent、模型工具动作，以及依赖 host/thread/MCP 的 skill 行为必须保留为显式模型运行或对应组件的独立证据，不能为了“能力齐全”把它们伪装成已经验证，也不能开放 hooks、网络、安装或发布权限。
