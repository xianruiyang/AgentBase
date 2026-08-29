# Agent 档位与验证尝试生命周期需求

## REQ-001 收敛自定义 Agent 角色

- 状态: superseded
- 来源: 用户 2026-08-18/19 明确要求“luna 默认就是 max，terra 不要了，sol 默认 medium”
- 关联: AC-001, AC-002, AC-003, UDES-001

Codex 可移植设置只管理 Luna 与 Sol 两个自定义角色，并按用户指定的推理档位运行。

## AC-001 Luna 默认 max

- 状态: superseded
- 关联: REQ-001

`global/config.toml` 的默认子代理为 Luna/max，`global/agents/luna.toml` 也显式声明 `max`。

## AC-002 Sol 默认 medium

- 状态: superseded
- 关联: REQ-001

`global/agents/sol.toml` 显式声明 `medium`，部署校验拒绝其他档位。

## AC-003 Terra 完成退役

- 状态: confirmed
- 关联: REQ-001

候选源码与受管当前资产不再包含 Terra；部署生命周期把历史 `agents/terra.toml` 声明为退役资产，并且不影响目标主机的无关个人代理。

## REQ-003 以语义角色降低证据与实验成本

- 状态: confirmed
- 来源: 用户 2026-08-23 要求 Luna 整理静态证据与现状地图、Sol low 快速迭代实验，主代理规划并正式实现；模型和档位应可在全局配置中独立更新；同日进一步要求以可推翻的默认选择关闭 Codex 触发冲突，不使用绝对创建义务，并纠正 `experiment` 被误解为只适用于全陌生问题；2026-08-26 增加 `operator`；2026-08-30 要求三种固定角色创建时必须使用 `fork_turns="none"`
- 关联: AC-006, AC-007, AC-008, AC-009, AC-010, AC-011, AC-012, UDES-003, UDES-004

AgentBase 管理 `evidence`、`experiment` 与 `operator` 三个语义稳定的自定义角色。前两者低成本交付可逐项接纳的静态证据和可逆实验结果，后者执行合同已确认的难脚本化有界工作；主代理保留正式交付责任。

## AC-006 Evidence 使用 Luna medium

- 状态: confirmed
- 关联: REQ-003

`global/agents/evidence.toml` 显式选择 `gpt-5.6-luna` 与 `medium`，默认只读取证并交付带范围、直接来源、反例、否定检查和未知项的证据包。

## AC-007 Experiment 使用 Sol low

- 状态: confirmed
- 关联: REQ-003

`global/agents/experiment.toml` 显式选择 `gpt-5.6-sol` 与 `low`，在有恢复依据的隔离或精确可回滚范围运行最小操作实验，不修改生产真源或执行 Git、Publish 与完成状态动作。

## AC-008 角色语义与模型身份解耦

- 状态: confirmed
- 关联: REQ-003

全局规则和编排 skill 只使用 `evidence`、`experiment` 的稳定语义身份；具体模型与档位只由对应代理 TOML 管理。部署校验检查固定语义角色集合、schema、安全模型标识和受支持档位，但不得要求角色名匹配模型后缀或复制当前模型、档位选择。

## AC-009 主代理逐项接纳并保留正式责任

- 状态: confirmed
- 关联: REQ-003

只有子问题独立有界且预计降低总体 Token 或墙钟时间时才委派。存在静态证据包时，主代理逐项接纳证据 ID；没有独立取证阶段时，可直接给实验角色已确认的当前事实和输入快照。主代理保留目标、授权、规划、正式实现、验证、状态、完成、Git 与发布责任；子代理不继续委派，输出不扩大授权或直接成为完成证据。

## AC-010 默认委派是可推翻选择而非强制创建

- 状态: confirmed
- 关联: REQ-003, AC-009, UDES-003

用户明确指定是否使用子代理时按该边界执行。用户未指定时，适用的全局 `should` 规则在必要的静态取证或可逆操作实验可独立有界且委派净收益成立时明确请求使用 `evidence` 或 `experiment`；任一条件不成立时由主代理直接完成。用户明确要求子代理只创建调度入口，不扩大原任务授权；用户未要求并行时，只在至少两个子问题分别满足同一默认委派条件、无共享未证前提或可写状态，且并发净收益成立时才优先并行。

## AC-011 Experiment 按可逆操作的信息增益触发

- 状态: confirmed
- 关联: REQ-003, AC-007, AC-009, AC-010, UDES-003

`experiment` 的选择依据是一个独立有界、可恢复的实际修改或运行能否比主代理边实现边验证更低成本地取得会改变正式实现裁决的直接证据。任务全陌生、静态证据穷尽、存在多个候选或尚无初步路径都不是前置条件；已有实现方向时，也可用最小探针确认路径、暴露错误或真实约束、收敛被前序失败遮蔽的连续问题。若主代理能以一次便宜的定向修改和验证直接闭环，或实验不能安全分离、不会改变裁决，则不委派。

## AC-012 固定角色创建保持配置与拓扑隔离

- 状态: confirmed
- 来源: 用户 2026-08-30 根据 UAI14 修复后仍出现的实际 profile 继承和后代代理记录，要求创建 `evidence`、`experiment`、`operator` 时必须使用 `fork_turns="none"`，并处理其他同类问题
- 关联: REQ-003, AC-008, AC-009, UDES-004

创建 `evidence`、`experiment` 或 `operator` 时，`fork_turns` 必须显式且只能为 `"none"`；省略、`"all"` 或正整数均不符合固定角色合同。所需上下文只通过最小 capsule 传入；无法准确表达时由主代理继续处理，不用通用角色继承主代理模型、档位或完整上下文来绕过固定配置。三种子代理不得再创建子代理、新任务或分叉任务，需要拆分或越出 capsule 时停止并返回主代理。

## REQ-002 正式评估失败可追溯

- 状态: confirmed
- 来源: 用户要求处理此前评审项 5，并确认每次失败应改进而不是原样重跑
- 关联: AC-004, AC-005

每次正式独立评估都必须在 evaluator 执行前取得 attempt ID，结束后明确登记通过、结果校验失败或执行失败；不存在可被后续运行覆盖的未登记失败。

## AC-004 未完成尝试阻断正式门禁

- 状态: confirmed
- 关联: REQ-002

任何 `started` 尝试都阻断正式 Validate/Publish；相同输入最多执行两次，第二次必须说明改进或重试理由。

## AC-005 尝试账本有界且可恢复

- 状态: confirmed
- 关联: REQ-002

当前评估周期最多保留六份收据；切换周期时保存上一周期身份、账本哈希和收据数，旧账本正文可通过 Git 历史恢复。

## CON-001 本轮不安装或发布

- 状态: superseded
- 来源: 当前请求没有针对本次 Publish 的明确授权，且项目要求每次 Publish 单独授权

初始实施轮只修改并验证仓库真源，不向真实 Codex 根目录 Publish，不安装软件。用户随后在独立请求中明确要求“发布”，该约束仅对初始实施轮成立，不限制已获单次授权的后继发布。

## CON-003 后继发布仅限本次授权

- 状态: superseded
- 来源: 用户 2026-08-19 明确要求“发布”

允许按当前迁移状态执行一次 `DirectCompatibility + InstallPortableSettings` Publish，并进行只读 Status 验收；该授权不继承到以后发布。它当时没有创建 Git 授权，随后用户通过独立请求授予了项目持续 Git 维护与远端同步权限。

## CON-004 持续维护项目 Git 历史

- 状态: confirmed
- 来源: 用户 2026-08-19 明确说明“这个已经说过你来全权控制的了，可能项目 agent.md 没写”，并要求完善后处理 Git

AgentBase 内已授权并验证的项目改动默认由模型自行形成职责清晰的提交并非强制推送到已配置私有远端，不再逐次请求同类 Git 授权；历史重写、强制推送、远端或仓库归属变更和破坏性删除不包含在持续授权内。

## CON-002 保留既有工作区改动

- 状态: confirmed
- 来源: 用户接手要求与项目规则

保留并合并本轮开始前 `docs/plan.md`、`docs/handoff.md` 的 dirty 内容，不回退无关改动。

## CON-005 保留 Windows SWE 评测候选并允许本次发布

- 状态: confirmed
- 来源: 用户要求完善后发布；接手边界要求保留既有 dirty worktree
- 关联: REQ-003, AC-006, AC-007, AC-008, AC-009

本次角色、规则、skill、部署生命周期和路由证据完成后，允许按真实安装模式向当前 Codex 根目录 Publish 一次；既有 `development/agent-evaluation/`、根 README 与 requirements 评测合同改动继续排除于本版本提交和行为声明。

## CON-006 保留当前 dirty 边界并直接应用本次修订

- 状态: confirmed
- 来源: 用户要求按 `should` 方案修改后直接应用，不运行独立测试
- 关联: REQ-003, AC-009, AC-010

保留根 README、Windows SWE 评测候选、`vendor/` 与其 requirements 合同的既有 dirty 边界；修订完成后允许以 `DirectCompatibility + InstallPortableSettings` 向当前 Codex 根目录 Publish 一次。不单独运行功能测试、完整回归或外部评测；只保留模型可见身份改变后正式 Publish 必需的路由证据，以及发布入口自带的不可绕过确定性校验。
