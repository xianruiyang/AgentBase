# Skill routing validation

本目录维护 AgentBase 全局规则与关键 skill 的静态触发合同，以及只读取脱离仓库 capsule、不读取隐藏期望的分阶段独立研究。它可观察候选在给定请求下选择哪些 skill、粗粒度行为和条件引用，但模型结果不是部署门禁，也不证明 skill 内步骤或具体任务执行已经正确完成。

## 正式产物

- [`trigger-cases.json`](trigger-cases.json)：为规则路由独立构造的合成触发用例、严格路由用例、策略标签和条件引用选择的隐藏 oracle；不收录真实项目题面或答案。
- [`validate_contract.ps1`](validate_contract.ps1)：规则与 skill 的结构、引用、身份、集合关系和触发集合静态合同；不复制或裁决规则正文语义。
- [`routing_evaluation_common.ps1`](routing_evaluation_common.ps1) 与 [`routing_fingerprint.ps1`](routing_fingerprint.ps1)：三阶段 capsule、真实模型可见身份、cases-only 输出 schema、当前 oracle 和整体 generation 的唯一 owner。
- [`get_routing_evaluation_plan.ps1`](get_routing_evaluation_plan.ps1)：只读增量计划；默认返回低 Token model 视图，`-View machine` 返回同一 canonical 计划的完整 JSON。
- [`build_routing_evaluation.ps1`](build_routing_evaluation.ps1)：只构建指定阶段 capsule，供审计或外部受控运行使用。
- [`development/common/codex_cli_runtime.ps1`](../common/codex_cli_runtime.ps1)、[`development/common/codex_shell_environment_policy.json`](../common/codex_shell_environment_policy.json) 与 [`routing_evaluator_runtime.ps1`](routing_evaluator_runtime.ps1)：前两者唯一维护多个本地 evaluator 共享的 npm 原生可执行布局、版本身份、单模型 catalog 投影、JSONL 用量/工具事件解析与哈希固定的模型 shell 过滤，后者只维护路由 evaluator 专属的 sandbox 后备、禁用能力参数和有界诊断。服务环境与模型 shell 分离；cases-only 成功路径禁止任何 tool event，因此策略加强不改变 capsule 可见语义或要求重采样。
- [`invoke_routing_evaluation.ps1`](invoke_routing_evaluation.ps1)：单阶段隔离 Codex CLI runner。
- [`refresh_routing_evidence.ps1`](refresh_routing_evidence.ps1)：显式研究刷新入口；先计划，只启动必需阶段，Routing 与 Policy 可并行，最后原子合并。
- [`test_routing_infrastructure.ps1`](test_routing_infrastructure.ps1)：零模型 Token 的统一确定性测试入口；解析全部 PowerShell 脚本并并行验证指纹、capsule、planner、隔离 runtime、attempt ledger 与崩溃恢复。
- [`record_routing_attempt.ps1`](record_routing_attempt.ps1)：正式尝试生命周期的唯一 owner；真实评估使用 `Begin`/`Finish`，证明复用使用 `Reuse`。
- [`merge_routing_evidence.ps1`](merge_routing_evidence.ps1)：唯一正式证据合并入口；只接受当前 generation 内三份已通过收据及语义一致的阶段结果。
- 本机 `evidence/current.json`：最近一次完成的路由研究快照；不进入 Git，Validate、Deploy 与 Status 不消费它。
- 本机 `evidence/attempts.json`：当前研究 generation 的有界收据账本；不进入 Git，只证明运行或复用来源、失败和重试边界，不反推 skill 正确性。

新 generation 尚未三阶段合并时，`current.json` 可以继续指向上一份已完成快照，而 `attempts.json` 指向当前失败或进行中的研究周期；二者此时不得假定同代。账本可单独验证 schema、限额和收据关系；只有 merge 已完成、两者同代时才用 `-CurrentEvidencePath` 追加验证三阶段通过收据绑定。

新克隆不包含真实运行快照和收据；确定性测试在临时目录生成合成结果，不需要复制个人 evidence。缺少研究结果不构成模型验证通过，也不授权自动启动 evaluator。

## 静态合同

全局规则或 skill 触发语义变化时，先同步 `trigger-cases.json` 中适用的正向、相近非触发、混合意图和严格用例，再运行：

```powershell
& '.\development\skill-routing\validate_contract.ps1' -ProjectRoot (Get-Location).Path
```

静态通过只证明文件结构、引用、身份、集合关系和测试 oracle 自洽，不证明规则语义正确或模型行为已经改变。全局规则使用普通 Markdown，不要求 must/should 前缀；校验只检查非空和完全重复的段落，不从标签解释约束强度。规则语义只由唯一正文和行为评估维护；静态脚本不得以精确文案、开发组件内部实现或等价改写差异形成第二契约。

修改评估基础设施时运行统一确定性入口；默认 model 视图只返回一行摘要，`-View Machine` 返回同一结果的结构化投影。入口对子进程设置只允许阻止 evaluator 的测试边界，invoker 在该边界内会先于 Begin 和外部进程拒绝执行，因此回归走错分支也不会消耗模型 Token。它不刷新 `current.json`：

```powershell
& '.\development\skill-routing\test_routing_infrastructure.ps1' -ProjectRoot (Get-Location).Path
```

该脚本是测试结果投影 owner：维护者与研究自动化消费默认一行摘要或显式 machine JSON，两种视图来自同一次套件结果。输出只存在于当前进程 stdout，不缓存、不写回 evidence，也不作为模型行为正确性的第二证明来源；失败时只返回有界套件诊断和可重跑的确定性入口。

## 阶段身份与影响计划

三个阶段只绑定 evaluator 实际可见的内容：

- Routing：`global/AGENTS.md`、项目 skill description、peer skill description、请求和可用 peer；skill 正文与 `agents/openai.yaml` 不可见，也不进入身份。
- Policy：`global/AGENTS.md`、行为标签定义和请求；它不读取或绑定 Routing 结果，因此两者可以并行。
- References：当前 Routing 结果真正选中的 reference-aware skill 正文、相关请求和这些 skill 的选择投影；它不绑定完整 Routing evaluator、无关 skill 或未选中的正文。

隐藏的 expected、forbidden 与 strict 字段只由 validator 消费。若阶段可见身份未变，planner 先用当前 oracle 重验旧结果：通过才返回 `reuse`；若新 oracle 拒绝旧结果则返回 `blocked`，不得以另一轮相同输入采样碰成功。evaluator 协议、输出 schema、指纹算法或无法证明边界的变化会改变 capsule 身份并触发相应完整阶段。

只读查看最小计划：

```powershell
& '.\development\skill-routing\get_routing_evaluation_plan.ps1' -ProjectRoot (Get-Location).Path
& '.\development\skill-routing\get_routing_evaluation_plan.ps1' -ProjectRoot (Get-Location).Path -View machine
```

计划区分 `evaluate`、`reuse`、`pending-routing` 和 `blocked`。Routing 需要新结果时，References 先为 `pending-routing`；正式入口取得新 Routing 结果后用同一 planner 重新计算，而不是预先假设 References 必须运行。

## 显式研究刷新与隔离 runner

只有明确研究路由行为或诊断已发生的路由失败时才调用：

```powershell
& '.\development\skill-routing\refresh_routing_evidence.ps1' -ProjectRoot (Get-Location).Path
```

若全部阶段仍有效，它返回 `already-current`，不启动 evaluator、不新增收据。需要刷新时，它先为不变阶段登记 `evidence_reuse`，再并行启动需要的 Routing/Policy，取得有效 Routing 后判断 References，最后通过 merge 原子更新 `current.json`。首次从旧协议迁移时三阶段都会运行；后续非 reference skill 正文变化为零运行，reference-aware skill 正文变化只运行 References，全局规则变化并行运行 Routing 与 Policy。

默认输出是供模型读取的最小摘要，不包含 generation、receipt 或证据路径等机器身份；程序需要完整结构时显式传 `-View machine`。

阶段结果在 merge 完成前原子保存在被 Git 忽略的 `evidence/pending/<generation>/`。若模型阶段已经通过而外层编排随后失败，下一次刷新重新校验结果，并同时匹配 current generation 的 passed receipt、文件哈希、语义哈希、capsule 与 evaluator 后直接恢复，不重复调用模型。若同一结果仅被旧 oracle 拒绝，当前 oracle 已接受且文件、可见输入、capsule 与 evaluator 仍精确匹配，则在当前 generation 内或通过不可变的上一代账本链追加零 Token `oracle_revalidation` 收据并引用原失败收据，不重新采样。generation 改变时，刷新先把旧账本原样固化到新 staging；阶段可见身份仍有效且旧 stage、旧 passed receipt、账本链和当前 oracle 一致时登记零 Token `staged_carry_forward`，中途重启也沿这份账本快照继续搬运剩余阶段。merge 成功后才删除所有已消费 staging。该目录只是崩溃恢复资产，不是第二证据真源。

runner 只接受可直接执行且不在 WindowsApps 下、不是 reparse point 的用户态 Codex CLI；共享 owner 依次识别用户 npm `@openai/codex` 的嵌套 optional package、提升 optional package 与主包 vendor 回退布局，evaluator 再以 `.codex/.sandbox-bin` 为已验证后备。正式模型默认为 `gpt-5.6-sol`、推理档位默认为 `medium`。每个阶段使用仓库外随机 workdir、临时 `CODEX_HOME`、只读且运行期间禁止写回的现有 `auth.json` 硬链接，并通过共享 owner 把用户级官方 `models_cache.json` 中所选模型投影为只含一个模型的临时目录，避免空 home 的远端目录刷新；缓存时间、etag、其他模型、用户配置和插件状态均不进入投影。runner 使用 `--ignore-user-config`、`--ignore-rules`、`--sandbox read-only`、`--ephemeral`、`--strict-config`、`analytics.enabled=false`、显式禁用插件/应用/hooks/skills/shell 等非评估能力和强制 JSON Schema。schema 只承担结构、枚举和必填字段，数组数量与唯一性由本地 validator 承担，以适配 Responses 的结构化输出子集。每个阶段要求模型在内部逐项检查正向与非触发边界，但不输出理由；模型仍只生成 cases。runner 生成带模型目录 SHA-256 与禁用能力清单的 evaluator envelope，通过共享 JSONL parser 检查不存在工具调用并读取完整用量，再检查真实仓库或用户 skill 根访问痕迹和真实认证文件哈希未变。临时 capsule、模型目录、schema、结果和诊断在结束后删除，不持久化原始模型日志。

runner 在 Codex 进程前先 `Begin`，所有已取得 attempt ID 的退出路径都用相同 ID `Finish`。进程启动前的 runner/编排失败记为 `orchestration_failed`，进程启动后的 CLI/超时/隔离失败记为 `execution_failed`，结果身份或结构失败记为 `identity_or_schema`，当前 oracle 失败记为 `oracle_violation`。检查的输入、实现和环境未变化时不得原样重跑；只有可见输入、实现或环境的真实原因修正后才使用阶段 `-RetryJustification`，仅修正隐藏 oracle 时复用精确原结果。每个可见输入最多两次真实 evaluator 尝试；零 Token revalidation 不占采样次数，启动前失败另行有界为两次且不冒充模型采样，整个 generation 仍受六份收据总上限约束。

冷目录准备、认证或模型目录投影在 `Begin` 前完成；这些步骤失败时没有外部 evaluator 尝试，不产生伪收据。`Begin` 后但进程启动前的失败会落盘为 `orchestration_failed`，进程启动后的失败才记为 `execution_failed`；有界诊断同时保留首尾，避免启动日志挤掉最终根因。

审计时仍可单独构建 capsule；Policy 不接受 Routing 路径，References 必须传入已经通过的 Routing 结果：

```powershell
& '.\development\skill-routing\build_routing_evaluation.ps1' -Phase Routing -ProjectRoot (Get-Location).Path
& '.\development\skill-routing\build_routing_evaluation.ps1' -Phase Policy -ProjectRoot (Get-Location).Path
& '.\development\skill-routing\build_routing_evaluation.ps1' -Phase References -ProjectRoot (Get-Location).Path -RoutingResultsPath '<routing-result>.json'
```

## 收据、复用与恢复

`record_routing_attempt.ps1` 是研究尝试生命周期的唯一 owner。每次真实 evaluator 执行必须先 `Begin`，使 `started` 收据先于外部运行持久化；随后必须用同一 attempt ID `Finish`。未完成的 `started` 收据会阻断该 generation 的合并和后续正式研究刷新，不能通过重新执行掩盖。

`Reuse` 不把旧文件存在当作正确性证明。它重新构造当前阶段 capsule、运行当前 oracle，并记录来源 evidence SHA-256、来源 receipt ID、当前阶段身份、语义结果 SHA-256、既有 evaluator 身份和零运行 Token。merge 从当前阶段沿 receipt、语义结果和 source link 验证并写回新的 receipt ID，不从 evaluator 时间或文件变短推断可复用。

每份收据只保存 phase、generation、候选/输入/capsule/语义结果哈希、evaluator 身份、开始与完成 UTC 时间、来源关系、耗时与 Token 计数、结果、最多 500 字符失败摘要、变化字段和可选重试理由，不保存原始模型日志。相同 phase、candidate、input 与 capsule 的后续正式收据必须显式说明理由；每个不变输入最多两次真实 evaluator 尝试和两次启动前编排失败，达到相应上限后必须改变原因或可见输入，不能原样刷到成功。

`evidence/attempts.json` 由登记入口在独占锁下原子维护；被 Git 忽略的稳定 `.lock` 文件只提供跨进程句柄互斥，不在释放时删除，因此并行 writer 不存在“旧 owner 删除新 owner 锁文件”的竞态。一个活跃周期最多六份收据。这里的周期是 Routing capsule、Policy capsule和全部 reference-aware skill 正文组成的整体 generation，不再借用 Routing capsule 充当三阶段身份。generation 改变时，只有旧周期不存在未完成尝试才滚动；新账本保留上一周期 ID、账本 SHA-256 与收据数，旧正文通过 Git 历史恢复，不在当前模型读取面无限累积。

`validate_routing_attempt_history.ps1` 负责 schema、generation、唯一 evaluator、未完成尝试、每输入的 evaluator/编排失败分类上限、六份收据上限，以及 `current.json` 中每个阶段 receipt 与语义结果的唯一绑定。仓库首次引入账本时，`initialize_routing_attempt_history.ps1` 可从已经验证的 current evidence 生成三份 `baseline_import` 收据，并明确声明更早尝试未被重建；它拒绝覆盖已有历史。

这些证据只覆盖 skill 路由、粗粒度行为标签、条件引用选择、独立输入边界和运行/复用 provenance。组件回归、release gate、实际安装状态与具体任务结果仍由各自正式 owner 验证。
