# 受监控隔离 Agent 源码查找基准协议

## 1. 职责与状态

本文件是统一源码查询网关分支的可重复基准合同，状态为 `implemented`。它固定测试对象、隔离角色、监控数据、对照顺序、质量复核和历史结果复用方式，不执行测试，也不授权发布。`development/code-search-benchmark` 是 runner、monitor、汇总与 capsule 的唯一 owner；不得复制临时脚本形成第二入口，也不得把本协议或其实现放入 Codex payload。

## 2. 证据角色

| 角色 | 输入 | 允许动作 | 不得接触 |
| --- | --- | --- | --- |
| coordinator | 冻结 corpus、环境模板、候选差异、运行顺序 | 构建隔离环境、启动 monitor、汇总状态 | 运行中修改 subject prompt 或补救答案 |
| subject | 单个 case、单个隔离环境、带只读任务合同的源码工作区 | 自主选择只读查询工具并回答 | 修改工作区或外部状态，对照输出、聚合结果、历史对话和 hidden oracle |
| monitor | subject 进程、事件流、超时合同 | 捕获 JSONL/stderr/exit/usage/tool calls，超时终止 | 向 subject 发送中途信息或改变环境 |
| auditor | detached audit capsule | 复算用量、核对环境差异、按语义 oracle 评质量 | 仓库、候选设计讨论、其他结果和未声明期望 |

subject 必须是新鲜 `codex exec --json --ephemeral` 进程或能证明等价隔离并返回完整 usage 的正式入口。线程内子 agent 若不能提供独立环境身份和 `turn.completed.usage`，不得用于总 Token 基准。

## 3. 版本化测试内容

既有测试形成以下六个种子 case，原始 prompt 和历史 oracle 已去除机器绝对路径后固化在 [benchmark-corpus-seed.json](benchmark-corpus-seed.json)。`v11.json` 另增两个代表 case，当前共八项。正式 corpus 为每个 case 保存 prompt、工作区角色、答案长度、最小回答合同、结构化事实关系 oracle 和适用源码快照；源码事实或回答合同变化时创建新 corpus 版本，不改写旧结果。

| Case ID | 工作区角色 | 查找目标 | 质量重点 |
| --- | --- | --- | --- |
| `agentbase-file-discovery-control` | AgentBase | 已知文件发现 | 唯一路径、无额外内容 |
| `agentbase-rg-policy-sources` | AgentBase | 统一 srcq 正式规则来源 | 排除测试/验证脚本、路径与规则关系 |
| `agentbase-provider-observation` | AgentBase | TypeScript 定义与 DTO 暴露关系 | 唯一定义、字段、映射位置 |
| `agentbase-sgy-containing-contract` | AgentBase | Rust 完整实现与位置投影合同 | 完整范围、坐标、最小包含、失效处理 |
| `ue-command-dispatch-submit` | 大型 C++ 项目 | 生产定义及返回协议 | 完整定义范围、两个错误 code、排除替身 |
| `ue-hjson-isbarekey-occurrences` | 大型 C++ 项目 | 定义与全部调用位置 | 全集证明、定义/调用区分、结果完整性 |

这六项覆盖文件、文本、结构和语义关系，短答案与完整范围，单目标与全集，以及小型/大型项目。正式扩展优先补充 0/1/N/N+1、同文件多目标、重载/嵌套、工具失败回退和 LSP 快/慢/空/失败，不为增加数量复制等价任务。

`v11.json` 在上述种子上增加两个不同项目与机制的代表 case：FaceCutting3D 的 C++ 限定成员、typed receiver、非注释直接调用和公共/私有实现链，以及 OpencodeVsPlugin 的 TypeScript 类方法/局部闭包身份、事件注册/清理与状态过滤。它们用于检验共享查询决策能否跨语言和项目成立，不把某种语法或业务名称写入 skill；扩量只有在代表 case 暴露新的失效机制时进行。

历史 runner 的正则 `required` 只作为旧结果的原始 oracle，不进入新正式 corpus。新 oracle 以结构化事实和关系表达，例如“字段属于哪一 DTO”“哪些行是定义、哪些是调用”；`answer_contract.required` 单独定义 prompt 必须显式回答的最小内容，`supporting` 只证明正确性或记录更强表达，不得被 auditor 静默升级为必答字段。语言同义表达由 auditor 裁决，避免把 `[start,end)` 误判为不满足 `end-exclusive`。

## 4. Experiment Identity

每次实验先生成只读 manifest；下列任一字段变化都产生新的 experiment identity：

- corpus schema、版本和内容 hash；
- 每个工作区的仓库标识、声明的相对 identity scope、commit/tree hash、该范围 dirty patch hash 和快照 hash；
- Codex CLI 绝对路径、文件大小、SHA-256、实际版本、模型、reasoning effort、service tier、sandbox、approval、显式 transport 和网络策略；网络策略还须绑定显式 Codex `.env` 来源、固定 allowlist、实际投影键、代理转换选项和脱敏整体 hash，不得记录原值；
- Token 用量字段语义、价格系数基准、适用模型族、价格来源日期和长上下文阈值；
- 全局/项目规则、config、skill、插件、MCP、可执行工具版本及环境树 hash；
- control/candidate 唯一允许差异清单及其内容 hash；
- 重复次数、平衡顺序、随机种子、单回合超时和整体预算；
- runner、monitor、汇总器和 audit schema 版本。

正式独立基准固定使用正常速度 `service_tier = "default"`、`sandbox = "danger-full-access"` 和 `approval_policy = "never"`，并把 transport 显式冻结为 `websocket` 或 `http-only`。每个隔离 home 必须显式设置 `features.multi_agent = false`，runner 还要把只读与不得创建子代理写入所有 subject 的公共 prompt 前缀，并将该执行合同写入 experiment identity；单个 case 重复声明只作局部可读性补充。WebSocket 使用内置 ChatGPT provider；HTTP-only 使用 runner 固定的同一 ChatGPT OAuth endpoint provider，不得由自由 `extra_config` 改写。full access 用于避免 Codex 路由层在真实查询进程启动前误拦截 `srcq` 等只读命令，不授权 subject 写入；prompt 仍明确禁止修改，运行前后身份读回负责发现越界副作用。Fast/Priority、隐式 transport、其他 sandbox 或可覆盖上述身份的额外配置不得进入默认收益对照；环境准备器和 runner 都必须拒绝。

control 与 candidate 除允许差异外必须逐项相等。环境构建不得把数据库、历史、一般运行 cache 或信任状态复制进结果；认证文件只可从既有安全 home 链接到隔离 home，不复制进实验结果或环境树。隔离 home 不得位于系统临时目录，避免 Codex 拒绝建立命令 helper；迁移对照默认只复制当前差异的因果 skill 集与系统 skill。若实验的 Control 被用户定义为当前完整 `AGENTS.md + skill` 环境，则必须另用完整模式复制全部用户 skills 与当前 remote-plugin cache、冻结启用插件内容、通过指定的当前 Codex CLI 安装并读回插件，再从最终 Control 克隆 Candidate；不能以缩减因果集替代该 Control。`plugins/cache` 是插件实际加载副本而不是可忽略的一般 cache，须连同共享冻结目录在 prepare/postflight 逐文件重算。预检发现额外差异时停止实验，不让 agent 运行后再解释混杂。

subject 的代理与证书环境由 runner 从 config 明确指定的 Codex `.env` 只读投影。固定 allowlist 之外的 `.env` 项不进入 child environment；runner 在注入前移除父 shell 的同类键，避免未记录继承。SOCKS 的代理端 DNS 与 ALL_PROXY 到 HTTP/HTTPS 键的 fanout 只能由 config 显式选择并进入身份，不能根据一次成功隐式猜测。`.env` 文件和原值不得复制到隔离 home、原始事件、manifest 或 capsule；prepare 只冻结键集合、转换选项与有效投影 hash，run 时重新读取，不匹配即在启动 subject 前停止。

当前 srcq 迁移对照由 [prepare_benchmark_homes.py](prepare_benchmark_homes.py) 从同一个 Codex home 构建。初始迁移 control 保留旧的 rg/fd/AST 查询 skills，candidate 退出它们并从项目真源安装 `source-query`；增量对照则让两侧都保留基线 `source-query`，只替换 candidate 的当前版本。完整 Control 使用 `current-control` 模式，固定 Luna medium、standard、hooks 关闭和 subject 子代理关闭这些实验约束，同时复制当前完整规则与 skills、冻结并安装当前启用插件；保留的插件 skill 名称与内容不变，快照 marketplace 使用实验专属身份以避开 Codex 保留名称。候选二进制必须先通过真实 `srcq rg <native argv...>` 探针，再进入私有 `bin`。允许差异必须逐文件限于相应 bundle，不能把整个 skills 目录列为通配差异。正式 subject 会访问的每个工作区必须在两侧 `config.toml` 中以相同规范路径预登记为 trusted；不得依赖首次运行自动写入信任状态，否则冻结后的环境身份已变化，该批结果无效。

环境准备入口为：

```powershell
python -X utf8 development\source-query-gateway\prepare_benchmark_homes.py --installed-codex-home $env:USERPROFILE\.codex --control $env:LOCALAPPDATA\AgentBase\benchmark-homes\<run-id>\control --candidate $env:LOCALAPPDATA\AgentBase\benchmark-homes\<run-id>\candidate --srcq-exe <current-srcq.exe> --baseline-mode current-control --codex-exe <current-codex.exe> --trusted-project <workspace-a> --trusted-project <workspace-b>
```

## 5. 单次可重复流程

1. coordinator 冻结 corpus、候选差异、运行参数和工作区 identity scope；oracle 来源必须落在相应 scope 内，已登记且 identity 完全相同的历史基线才可复用。
2. 为每个环境建立新的最小 Codex home；绑定真实 Codex 可执行文件身份，并只对本次实际调度的环境用正式 sandbox、模型、推理深度、PATH、transport 和冻结网络投影执行一次能力预检。预检工作目录必须是 home preparer 已在两侧同等预登记的正式工作区，runner 须在预检前后核对所有声明 workspace identity，不能把预检副作用冻结成基线；也不得让单侧首次访问临时工作区后新增 trust 状态。含 srcq 的环境须在同一 Codex 预检中分别成功执行 `srcq.exe --version` 与 `srcq query scc doctor`，从 command event stdout 证明 wrapper 与真实 scc 后端均可启动；无 srcq 的历史 control 执行 `rg.exe --version`。预检必须取得完整 usage，且 JSONL/stderr 中没有 WebSocket 连接失败、sampling retry 或 HTTP fallback；失败时不进入 subject 调度且不静默重试。
3. 首次初始化完成后冻结环境树和声明范围内的源码快照，确认差异恰好等于 allowlist，再生成最终 manifest 与 hash；run 前还须核对 runner 源码 hash 与 Python 版本未变。
4. 按预先记录的平衡顺序运行。两环境、每项两次时使用 A-B-B-A；更多重复使用预生成的平衡随机区块，不能查看中间结果后改变次数或顺序。
5. monitor 启动一个无历史 subject，持续读取事件流并保存原始 JSONL、stderr、退出状态和 wall time。超时、事件损坏、进程异常、WebSocket 连接失败、sampling retry 或 HTTP fallback 作为该次真实失败保留并使 experiment postflight 无效；不得用静默重试替换记录。
6. monitor 从最后一个 `turn.completed.usage` 记录 input、cached input、cache write input（事件提供时）、output、reasoning output，并保存完整工具调用顺序、失败和最终答案。它校验非负整数与子集关系，但不判断质量；缺失 cache write 不得静默按零处理。
7. 全部 subject 结束后生成 detached audit capsule，只包含冻结 manifest、corpus/oracle、环境差异证明、setup 与 subject 原始文件 hash、规范化记录和答案，不包含凭据、候选讨论或既有结论；capsule 同时声明可独立复算的规范化哈希算法及排除字段。
8. auditor 先核对缺项、重复、配对、事件/summary 一致性和计量恒等式，再按结构化语义 oracle 逐案裁决质量；oracle 缺陷与答案缺陷分别记录。
9. 汇总器只纳入身份有效、记录完整的 run，依次比较质量、总 Token 和 wall time；报告 subject-only、setup-only、including-setup、配对差、按 case 分布、失败/回退和适用统计范围，不用总均值掩盖异质性。

## 6. 计量与裁决

- `actual_total_tokens = input_tokens + output_tokens`。
- cached input 与 cache write input 是 input 的分类；reasoning output 是 output 子集；`visible_output = output - reasoning output`，所有子项均单列但不重复相加。
- 价格系数以短上下文普通输入 Token 为 `1`：当前 GPT-5.6 短上下文为 `1 / 0.1 / 1.25 / 6`，单次请求输入超过 272K 时整次请求为 `2 / 0.2 / 2.5 / 9`，顺序分别是普通输入、缓存读取、缓存写入、包含推理的输出。若改用该长上下文本身的普通输入为基准，输出系数是 `4.5`。
- `turn.completed` 只能提供 subject 聚合用量，不能还原每次模型请求的上下文档位；cache write 字段也可能缺失。报告必须分别给出短/长场景、缓存写入已知时的精确值或未知时的上下界，并标明单位是价格等价量而非真实美元账单。
- wall time 从 subject 进程启动到退出，包含工具、失败、回退和外部服务等待。
- 工具调用数、失败调用、MCP 调用、stdout/stderr 大小只解释机制，不替代总 Token。
- raw oracle、回答合同、核心语义和额外观察分开报告；发布裁决只使用预先确认且不超过 prompt 的 `answer_contract.required`，支持事实未在答案复述不得回写为核心失败。
- 质量任一适用 case 退化时先修正或判失败；质量同等时才比较 Token，Token 不变差时才比较速度。
- 样本不足、环境告警、网络漂移或配对方差较大时降低因果与泛化结论，不临时追加有利样本。

## 7. 历史基线的复用边界

2026-08-14 两轮真实 Codex 数据和独立审计是本分支的现实依据，聚合值写入 [plan.md](plan.md)。它们证明 skill 固定加载、额外工具回合和失败回退能够抵消局部输出压缩，也证明结构定位在部分任务中确有收益。

旧数据没有完整记录工作区 commit/dirty patch，两个 Codex home 也曾存在非目标差异，因此只能固定为历史观察，不能伪装成新协议下可逐字复现的因果基线。新实验可复用其任务种子和已审计总数；只有新的 experiment identity 与历史记录所需字段能够证明相等时才复用对照 run，否则运行新的受影响对照。

完全裸 Codex 的 1,082,040 Token 同时移除了大量非搜索规则、skill 和配置，只保留为理论下界。五-skill 消融才是搜索能力固定成本的主要历史对照。

## 8. 产物与生命周期

正式实现至少生成：`corpus.json`、`experiment.json`、`environment-diff.json`、每次 run 的 JSONL/stderr、`summary.json`、`audit-capsule.json` 和独立 `audit-result.json`。大体积原始结果进入明确的 benchmark 产物目录或外部归档，不写入对话；仓库只保留版本化语料、schema、runner、必要小型 fixtures、聚合结果和 hash 索引。所有这些内容均为项目开发资产，Plugin 与 DirectCompatibility payload 都必须排除；测试结果只能影响发布裁决，不能成为运行时输入。

未完成、被终止或 identity 无效的实验保留状态但不进入聚合。候选机制未变化时不重复运行；机制、语料或环境变化时只使实际依赖它的结果失效。发布到 Codex 仍需要用户针对当次明确确认，benchmark 通过本身不创建发布授权。
