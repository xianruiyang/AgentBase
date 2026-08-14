# 受监控隔离 Agent 源码查找基准协议

## 1. 职责与状态

本文件是统一源码查询网关分支的可重复基准合同，状态为 `proposed`。它固定测试对象、隔离角色、监控数据、对照顺序、质量复核和历史结果复用方式，不执行测试，也不授权发布。分支实施后扩展现有 `development/code-search-benchmark` 承担 runner、monitor、汇总与 capsule 生成；不得复制临时脚本形成第二入口，也不得把本协议或其实现放入 Codex payload。

## 2. 证据角色

| 角色 | 输入 | 允许动作 | 不得接触 |
| --- | --- | --- | --- |
| coordinator | 冻结 corpus、环境模板、候选差异、运行顺序 | 构建隔离环境、启动 monitor、汇总状态 | 运行中修改 subject prompt 或补救答案 |
| subject | 单个 case、单个隔离环境、只读工作区 | 自主选择工具并回答 | 对照输出、聚合结果、历史对话和 hidden oracle |
| monitor | subject 进程、事件流、超时合同 | 捕获 JSONL/stderr/exit/usage/tool calls，超时终止 | 向 subject 发送中途信息或改变环境 |
| auditor | detached audit capsule | 复算用量、核对环境差异、按语义 oracle 评质量 | 仓库、候选设计讨论、其他结果和未声明期望 |

subject 必须是新鲜 `codex exec --json --ephemeral` 进程或能证明等价隔离并返回完整 usage 的正式入口。线程内子 agent 若不能提供独立环境身份和 `turn.completed.usage`，不得用于总 Token 基准。

## 3. 版本化测试内容

既有测试形成以下六个种子 case，原始 prompt 和历史 oracle 已去除机器绝对路径后固化在 [benchmark-corpus-seed.json](benchmark-corpus-seed.json)。正式 corpus 为每个 case 保存 prompt、工作区角色、答案长度、结构化事实关系 oracle 和适用源码快照；源码事实变化时创建新 corpus 版本，不改写旧结果。

| Case ID | 工作区角色 | 查找目标 | 质量重点 |
| --- | --- | --- | --- |
| `agentbase-file-discovery-control` | AgentBase | 已知文件发现 | 唯一路径、无额外内容 |
| `agentbase-rg-policy-sources` | AgentBase | 正式规则来源 | 排除测试/验证脚本、路径与规则关系 |
| `agentbase-provider-observation` | AgentBase | TypeScript 定义与 DTO 暴露关系 | 唯一定义、字段、映射位置 |
| `agentbase-sgy-containing-contract` | AgentBase | Rust 完整实现与位置投影合同 | 完整范围、坐标、最小包含、失效处理 |
| `ue-command-dispatch-submit` | 大型 C++ 项目 | 生产定义及返回协议 | 完整定义范围、两个错误 code、排除替身 |
| `ue-hjson-isbarekey-occurrences` | 大型 C++ 项目 | 定义与全部调用位置 | 全集证明、定义/调用区分、结果完整性 |

这六项覆盖文件、文本、结构和语义关系，短答案与完整范围，单目标与全集，以及小型/大型项目。正式扩展优先补充 0/1/N/N+1、同文件多目标、重载/嵌套、工具失败回退和 LSP 快/慢/空/失败，不为增加数量复制等价任务。

历史 runner 的正则 `required` 只作为旧结果的原始 oracle，不进入新正式 corpus。新 oracle 以结构化事实和关系表达，例如“字段属于哪一 DTO”“哪些行是定义、哪些是调用”；语言同义表达由 auditor 裁决，避免把 `[start,end)` 误判为不满足 `end-exclusive`。

## 4. Experiment Identity

每次实验先生成只读 manifest；下列任一字段变化都产生新的 experiment identity：

- corpus schema、版本和内容 hash；
- 每个工作区的仓库标识、commit/tree hash、dirty patch hash 和只读快照 hash；
- Codex CLI 版本、模型、reasoning effort、service tier、sandbox、approval 和网络策略；
- 全局/项目规则、config、skill、插件、MCP、可执行工具版本及环境树 hash；
- control/candidate 唯一允许差异清单及其内容 hash；
- 重复次数、平衡顺序、随机种子、单回合超时和整体预算；
- runner、monitor、汇总器和 audit schema 版本。

control 与 candidate 除允许差异外必须逐项相等。环境构建不得把凭据、数据库、历史、缓存、信任状态或临时 HOME 复制进结果；运行时凭据只通过既有安全入口使用。预检发现额外差异时停止实验，不让 agent 运行后再解释混杂。

## 5. 单次可重复流程

1. coordinator 冻结 corpus、源码快照和候选差异，生成 manifest 与 hash；已登记且 identity 完全相同的历史基线直接复用。
2. 为每个环境建立新的最小 Codex home 和只读工作区视图；预检工具、规则、skill、插件、MCP 和配置清单，确认差异恰好等于 allowlist。
3. 按预先记录的平衡顺序运行。两环境、每项两次时使用 A-B-B-A；更多重复使用预生成的平衡随机区块，不能查看中间结果后改变次数或顺序。
4. monitor 启动一个无历史 subject，持续读取事件流并保存原始 JSONL、stderr、退出状态和 wall time。超时、事件损坏或进程异常作为该次真实失败保留；不得用静默重试替换记录。
5. monitor 从最后一个 `turn.completed.usage` 记录 input、cached input、output、reasoning output，并保存完整工具调用顺序、失败和最终答案。它不判断质量。
6. 全部 subject 结束后生成 detached audit capsule，只包含冻结 manifest、corpus/oracle、环境差异证明、原始文件 hash、规范化记录和答案，不包含凭据、候选讨论或既有结论。
7. auditor 先核对缺项、重复、配对、事件/summary 一致性和计量恒等式，再按结构化语义 oracle 逐案裁决质量；oracle 缺陷与答案缺陷分别记录。
8. 汇总器只纳入身份有效、记录完整的 run，依次比较质量、总 Token 和 wall time；报告总计、配对差、按 case 分布、失败/回退和适用统计范围，不用总均值掩盖异质性。

## 6. 计量与裁决

- `actual_total_tokens = input_tokens + output_tokens`。
- cached input 是 input 子集，reasoning output 是 output 子集，均单列但不重复相加。
- wall time 从 subject 进程启动到退出，包含工具、失败、回退和外部服务等待。
- 工具调用数、失败调用、MCP 调用、stdout/stderr 大小只解释机制，不替代总 Token。
- raw oracle、严格语义和核心语义分开报告；发布裁决使用预先确认的严格语义合同。
- 质量任一适用 case 退化时先修正或判失败；质量同等时才比较 Token，Token 不变差时才比较速度。
- 样本不足、环境告警、网络漂移或配对方差较大时降低因果与泛化结论，不临时追加有利样本。

## 7. 历史基线的复用边界

2026-08-14 两轮真实 Codex 数据和独立审计是本分支的现实依据，聚合值写入 [plan.md](plan.md)。它们证明 skill 固定加载、额外工具回合和失败回退能够抵消局部输出压缩，也证明结构定位在部分任务中确有收益。

旧数据没有完整记录工作区 commit/dirty patch，两个 Codex home 也曾存在非目标差异，因此只能固定为历史观察，不能伪装成新协议下可逐字复现的因果基线。新实验可复用其任务种子和已审计总数；只有新的 experiment identity 与历史记录所需字段能够证明相等时才复用对照 run，否则运行新的受影响对照。

完全裸 Codex 的 1,082,040 Token 同时移除了大量非搜索规则、skill 和配置，只保留为理论下界。五-skill 消融才是搜索能力固定成本的主要历史对照。

## 8. 产物与生命周期

正式实现至少生成：`corpus.json`、`experiment.json`、`environment-diff.json`、每次 run 的 JSONL/stderr、`summary.json`、`audit-capsule.json` 和独立 `audit-result.json`。大体积原始结果进入明确的 benchmark 产物目录或外部归档，不写入对话；仓库只保留版本化语料、schema、runner、必要小型 fixtures、聚合结果和 hash 索引。所有这些内容均为项目开发资产，Plugin 与 DirectCompatibility payload 都必须排除；测试结果只能影响发布裁决，不能成为运行时输入。

未完成、被终止或 identity 无效的实验保留状态但不进入聚合。候选机制未变化时不重复运行；机制、语料或环境变化时只使实际依赖它的结果失效。发布到 Codex 仍需要用户针对当次明确确认，benchmark 通过本身不创建发布授权。
