# 执行控制与 Skill 上下文生命周期：现状与证据

## OBS-001 当前规则把首次读取与每轮使用混在同一动作

- 状态: confirmed
- 来源: `global/AGENTS.md` 修改前正文
- 证据上限: 证明 AgentBase 候选缺少跨 turn 与压缩后的正文有效性裁决，不单独证明宿主内部缓存实现

原规则要求依赖 skill 前完整读取 `SKILL.md`，但没有区分本轮重新路由、正文仍在当前上下文、正文已被压缩移除和内容已知变化。按保守解释，连续命中同一 skill 时会重复读取。

## OBS-002 未压缩续轮发生了可避免的重复读取

- 状态: confirmed
- 来源: 当前真实 Codex 会话 `01a00b1e-80a6-77b1-96be-814f4255283c` 的有界 JSONL 字段扫描、目标文件状态和 `tiktoken 0.13.0 / o200k_base`
- 证据上限: 直接覆盖该会话中的两次读取及对应文件身份，不外推所有 Codex 版本

最近一次上下文压缩发生在 `2026-08-17T23:39:35.732Z`；此后同一来源的 `openai-docs/SKILL.md` 分别在 `23:45:53.971Z` 与 `23:52:35.040Z` 被完整读取，中间没有压缩。该文件最后修改于 `2026-08-16T11:02:33Z`，正文为 1,103 tokens，因此第二次读取没有取得新规则或恢复已丢失正文。

## OBS-003 真实压缩没有保留此前已读 skill 的完整正文

- 状态: confirmed
- 来源: 同一会话最近一次 `compacted` 事件及其 `replacement_history` 有界字段检查
- 证据上限: 证明本次真实压缩结果，不断言每次压缩必然删除所有 skill 正文

`change-governance/SKILL.md` 在 `2026-08-17T22:56:07.440Z` 被读取，随后 `23:39:35.732Z` 的压缩替换历史既不包含该 skill 名称，也不包含其唯一正文句“只在触发条件命中时”。因此压缩后的名称、摘要或先前使用记录不能被当作完整正文仍然可用的证据。

## OBS-004 官方合同按选择加载并检测 skill 变化

- 状态: confirmed
- 来源: [OpenAI Docs：Build skills](https://learn.chatgpt.com/docs/build-skills)
- 证据上限: 证明公开产品合同，不证明当前 WindowsApps 包的未公开内部缓存细节

官方文档把 skill 定义为渐进披露：初始只提供名称、description 和 Codex 中的文件路径，决定使用后加载完整 `SKILL.md`；文档同时说明 Codex 自动检测 skill 变化，未出现更新时重启。公开合同没有把每个 new turn 定义为正文失效边界。

## OBS-005 重复加载具有可观测的上下文成本

- 状态: confirmed
- 来源: 当前候选 11 个项目 skill 主文件的同 tokenizer 计量
- 证据上限: 只计 `SKILL.md` 正文，不包含引用、工具往返或返工成本

11 个项目 skill 的完整正文合计 11,591 tokens，单项为 260—2,049 tokens。实际成本取决于本轮选择的 skill；这支持消除同一正文的无效重复，不支持为了省 Token 跳过应选 skill 或必要引用。

## OBS-006 受控嵌套 CLI 实验不可用

- 状态: confirmed
- 来源: 当前宿主执行 `codex --version`、`codex exec --help` 与 `codex exec resume --help`
- 证据上限: 只证明当前 WindowsApps 安装拒绝从该终端启动 `codex.exe`

三个入口都以“拒绝访问”失败，因此本轮不能用嵌套 CLI 额外复现文件热更新。该未知项不改变方案：已知变化时必须重读；没有变化证据且完整正文仍在有效上下文时不做每轮文件探测或重复读取。

## GAP-001 Skill 生命周期缺少有效性边界

- 状态: confirmed
- 关联: AC-007, OBS-001, OBS-002, OBS-003, OBS-004, OBS-005

当前规则把“本轮是否适用”和“正文是否仍可用”混为 turn 级失效，既会在未压缩上下文重复读取，也没有明确压缩后只恢复当前所需正文的动作。

## GAP-002 架构判断失效后的说明时点不明确

- 状态: confirmed
- 关联: AC-024

原规则只要求在风险影响当前结果时说明，没有禁止先按已经失效的 owner 或架构完成，再把正确架构作为残留风险告知。

## GAP-003 计划启动条件错误依赖用户措辞

- 状态: confirmed
- 关联: AC-036

原规则把“用户明确要求”与跨步骤控制需要并列为建立计划的触发，容易让复杂任务在用户没说“计划”时缺少控制，也让简单任务因形式要求产生无用计划。

## OBS-007 原完成证据没有覆盖运行期证据前沿

- 状态: confirmed
- 来源: `docs/work/20260820_agentbase_final_evaluation_set/failure-audit-20260821.md`、2026-08-21 当前对话中的用户纠正、原 `completion-audit.md`
- 证据上限: 证明原 AC-036 完成判断只覆盖计划是否建立与软优先级，没有证明真实执行会先闭合共享前提和首个消费者

九题最终评测在第一题尚未经过完整候选消费者前已形成横向执行意图；管理员批准、sandbox、环境和 runner 前置失败串行暴露，下游产品机制没有实际执行，却持续以“修一层再跑一层”的方式推进。用户明确指出该过程已耗费约 16 小时。原完成审计把“复杂任务会建计划”当作纵向闭环证据，不能覆盖这次反例。

## OBS-008 运行期排序职责分散且只有软约束

- 状态: confirmed
- 来源: 修改前 `delivery-workflow`、`task-table-manager`、`change-governance`、`reasoning-governor` 正文和任务依赖合同
- 证据上限: 证明候选规则没有唯一的运行期下一动作 owner，不证明任一模型必然采用错误顺序

原 Delivery Workflow 和 Task Table Manager 只在“条件相当时”偏好最近闭环，没有把共享前提证明和首个真实消费者写成下游实际消费的硬依赖；Change Governance 同时承担反复失效，Reasoning Governor 又同时判断任务负担与写入线程配置。相同控制问题跨多个 skill 存在局部规则，但没有一个 owner 负责证据前沿、失败遮蔽、批量扩展与成本熔断。

## GAP-004 共享未证前提没有形成消费者门禁

- 状态: confirmed
- 关联: AC-036, OBS-007, OBS-008

多个动作依赖同一未知判断时，现有合同不能保证先证明共同前提并完成一个真实消费者，也不能把该关系投影为后续任务真实消费的 `hard` 依赖。

## GAP-005 失败遮蔽与昂贵验证缺少统一控制 owner

- 状态: confirmed
- 关联: AC-036, OBS-007, OBS-008

基础设施失败、无效 oracle 和产品机制失败没有在运行期由同一职责分类；被当前失败遮蔽的下游容易被误写成失败或继续逐层重跑，用户对原因、时间或 Token 成本的质疑也没有成为暂停昂贵动作并重裁的明确输入。

## GAP-006 推理目标判断与线程设置职责相互缠绕

- 状态: confirmed
- 关联: AC-008, AC-009, AC-050, OBS-008

Reasoning Governor 同时承担“任务需要什么档位”和“如何读写 next-turn 设置”，使模型必须先选中该 skill 才会得到本应决定是否选择它的任务负担判断。复杂执行需要把目标档位与状态价值交给运行期控制，而线程 skill 只保留读回、设置和生命周期机制。

## OBS-009 真实 UE 工作流中规则存在但执行状态仍滞后

- 状态: confirmed
- 来源: 用户提供的两天大型 UE 工作流总结、后续事实复核与任务状态摘录
- 证据上限: 直接证明该受支持工作流中的可预防行为失败，不外推所有项目或模型版本

原规则已经要求最小语义闭包、消费者证据即时回流和阶段文档不保存原始日志，但实际执行中 `T50` 状态仍停在“下一步开始 normals”，没有记录已经完成的 schema 投影或刚发现的 verifier 反例；`WORK_STATUS.md` 与 `TASK_TABLE.md` 的可重建视图也处于 drift/partial 或计数不一致。规则正文存在没有使当前证据前沿成为一次读取可得、反例后必须先更新的执行状态。

## OBS-010 同一能力的 oracle 会被验证维度和脆弱调用改变

- 状态: confirmed
- 来源: 用户提供的 UE normals 真实公开 SDK 消费者结果与 `-ExecCmds` 失败复盘
- 证据上限: 覆盖 carrier、mode、revision、持久化会改变本次 normals 结论，以及重复外部命令的人工作业风险

DynamicMeshActor/StaticMesh、face/angle/area 模式、revision 状态与持久化边界会改变行为或 oracle；单一 fixture 通过被错误外推。另一方面，重复 UE 启动命令因分隔符、引号和环境人工拼装在产品逻辑前失败。前者需要最小判别组合与覆盖边界，后者需要领域 runner，而不是把 UE 语法写进跨项目规则。

## OBS-011 未重放现态会把工具误用写成产品缺口

- 状态: confirmed
- 来源: 用户提供的 srcq 0.4.2 实测复核与本轮原命令重放
- 证据上限: 证明已见批评中续页、fixed strings、预算和输出视图本已存在；剩余现象仍须按具体版本与命令判断

`srcq more q<number>`、`-F`、输出预算和 model/machine 视图已经存在；此前的若干失败分别来自不存在路径、未闭合正则、祖先与子目录重叠范围，或把 wrapper 参数传给原生 `rg`。`structured projection unavailable` 是已见现象，但在绑定版本、帮助、原输入与 fallback 充分性前不能直接称为产品缺陷。

## OBS-012 旧 oracle 修正后仍强制模型重采样

- 状态: confirmed
- 来源: 本轮 generation `D0B41EA251A5E264D55ECC7447A24C0E5D987B806FE4F21A504483AD921DDE61` 的真实 References 失败、原结果与刷新入口
- 证据上限: 直接覆盖同一 stage 文件、可见输入、capsule 与 evaluator 身份不变而隐藏 oracle 改正的恢复路径

References 模型输出只因隐藏 oracle 过度要求 CLI 引用而被记为 `oracle_violation`；修正 oracle 后原文件已通过当前验证，但刷新仍要求 `RetryJustification` 并准备重新调用模型。原账本只有 passed-result 恢复和跨代 carry-forward，没有“原输出不变、仅 oracle 已纠正”的零 Token 来源。

## GAP-007 可观察模型行为没有成为规则系统质量边界

- 状态: confirmed
- 关联: AC-066, OBS-009

项目能够区分具体修复 owner，但没有明确禁止用“模型执行问题”把受支持场景中的可预防错误排除在 AgentBase 质量之外，也没有要求从规则、路由、动作入口、反馈、状态回流和行为验证定位最早缺口。

## GAP-008 证据前沿、验证维度与覆盖范围没有进入现有任务 owner

- 状态: confirmed
- 关联: AC-036, OBS-009, OBS-010

任务合同不能声明会改变行为或 oracle 的维度，状态不能保存当前前沿、消费者、case、最近证据和失效来源，结果也不能区分实际覆盖组合；`context` 因而不能一次返回当前检查点与关联 DCR。反例后的“先写回再继续”仍依赖模型记忆。

## GAP-009 脆弱命令与工具缺陷判断缺少可执行升级边界

- 状态: confirmed
- 关联: AC-066, OBS-010, OBS-011

全局规则没有把反复人工拼装的稳定接口升级到领域 runner，也没有要求在声称工具缺陷前绑定当前身份、对应帮助和原输入并分类输入、范围、正常协议、降级、截断与产品故障。

## GAP-010 Oracle 修正没有零 Token 恢复来源

- 状态: confirmed
- 关联: AC-066, OBS-012

相同模型输出已经满足当前 oracle 时，重新采样既不增加产品信息，又违反“不变输入不为期待不同结果重跑”。账本需要一种精确引用旧失败收据、文件哈希、capsule 和 evaluator 的通过来源，并继续受总收据上限与原子 merge 约束。
