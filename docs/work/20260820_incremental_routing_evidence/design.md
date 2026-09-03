# 模型设计

## DES-001 三阶段各自拥有模型可见身份

- 状态: confirmed
- 关联目标: REQ-001, AC-001, AC-002, AC-003

`routing_evaluation_common.ps1` 从同一合同构造三种 capsule 与阶段指纹。每个 `candidate_bundle_sha256` 只覆盖该 capsule 实际暴露的候选，`evaluation_input_sha256` 只覆盖该阶段请求和选项；隐藏 oracle 只由 validator 消费。整体 generation 指纹组合三阶段静态可见依赖，用于有界尝试周期，不替代阶段身份。

## DES-002 只读 planner 是影响投影 owner

- 状态: confirmed
- 关联目标: REQ-002, AC-004, AC-005

`get_routing_evaluation_plan.ps1` 从当前候选、当前 evidence 和可选新 Routing 结果形成 canonical 计划，再投影 model/machine 两种视图。它只比较身份并调用当前 oracle 校验：Routing 与 Policy 可以同时为 `evaluate`，References 在 Routing 变化时先为 `pending-routing`；没有 evaluator 运行需求时返回零运行。

## DES-003 runner 拥有独立 Codex 执行边界

- 状态: confirmed
- 关联目标: REQ-003, AC-006

`development/common/codex_cli_runtime.ps1` 是 Windows bootstrap 与 evaluator 共用的 npm 原生 Codex 路径 owner，覆盖 optional package 的嵌套/提升布局和主包 vendor 回退，并排除 WindowsApps 与 reparse point；同目录 `codex_shell_environment_policy.json` 是所有本地 evaluator 共用的模型 shell 过滤真源，PowerShell owner 校验并把它序列化为严格 CLI config 参数。`routing_evaluator_runtime.ps1` 只增加 evaluator 专属 sandbox 后备与运行配置。`invoke_routing_evaluation.ps1` 使用这些唯一入口，不调用受 package identity 限制的 WindowsApps 二进制。它在仓库外建立临时 work/home，为 home 建立运行期间只读的 `auth.json` 硬链接，并从用户级官方 `models_cache.json` 只投影所选模型到临时目录；投影不携带缓存时间、etag、其他模型、用户配置或插件状态。runner 使用 `--ignore-user-config --ignore-rules --sandbox read-only --ephemeral --strict-config`、关闭 analytics、显式禁用非评估能力并强制阶段 JSON schema，同时把 policy SHA-256 记入 evaluator runtime。schema 只使用 Responses 结构化输出接受的子集，数组数量和唯一性由本地 validator 检查。模型只返回 cases，任何 tool event 都失败；因此过滤加强不改变已通过 evidence 的 capsule 语义。runner 从实际环境生成带模型目录哈希与禁用能力清单的 evaluator envelope，准备完成后、外部进程启动前调用 Begin，并在所有已登记退出路径调用 Finish。

## DES-004 attempt ledger 同时接收正式运行与证明复用

- 状态: confirmed
- 关联目标: REQ-003, AC-007

`record_routing_attempt.ps1` 继续是唯一收据 owner，并增加不启动 evaluator 的 `Reuse` 动作。新的 generation 周期内，每个阶段最终由一份 `formal`/`baseline_import` 或 `evidence_reuse` 通过收据支持；reuse 收据绑定来源 evidence 和来源 receipt。进程启动前的失败使用 `orchestration_failed`，不占 evaluator 采样额度但有独立上限；进程启动后才使用 `execution_failed`。稳定、忽略提交的 lock 文件只通过打开句柄互斥，不在 writer 释放时删除。merge 原子组成唯一 `current.json`，当前 evidence 持有各阶段 receipt ID；这些关系只服务路由研究的验证与恢复，不进入部署合同。

## DES-005 generation staging 只承担崩溃恢复

- 状态: confirmed
- 关联目标: REQ-003, AC-008

`refresh_routing_evidence.ps1` 把阶段结果原子写入 `evidence/pending/<generation>/`，该目录由 `.gitignore` 排除，不是项目真源。恢复时重新运行当前阶段 validator，并同时匹配 receipt、文件 SHA-256、语义结果 SHA-256、capsule 身份与 evaluator；任何一项不一致都不得恢复。generation 改变时先把旧账本原样固化到新 staging：旧 passed receipt 在当前 oracle 下仍有效时登记零 Token `staged_carry_forward`；旧 `oracle_violation` 的精确结果在当前 oracle 下已有效时，登记引用上一代失败收据的零 Token `oracle_revalidation`。若搬运中途再次中断，新账本沿不可变快照继续剩余阶段。`current.json` 合并成功后才清理已消费的全部 generation staging；原始 JSONL 和临时 Codex home 仍立即删除。

## DES-006 确定性测试入口与模型 evaluator 分层

- 状态: confirmed
- 关联目标: REQ-004, AC-009, AC-010

`test_routing_infrastructure.ps1` 是评估机制确定性回归的唯一入口：解析 `development/skill-routing` 全部 PowerShell 和共享 Codex CLI runtime owner 并校验静态合同，再以独立 `pwsh.exe` 子进程并行运行六组套件，限制单套件时间与输出，最后从同一结果投影一行 model 摘要或 machine JSON。入口对子进程设置 `AGENTBASE_ROUTING_EVALUATOR_DISABLED=1`，正式 invoker 在 Begin 和进程启动前拒绝该值，因此测试回归不能意外转为真实模型调用。该入口只在评估基础设施变化时运行；部署只调用 payload 的快速结构合同，不把研究回归或模型 evidence 变成安装前置条件。

## DES-007 模型 evidence 只属于显式研究生命周期

- 状态: confirmed
- 关联目标: REQ-004, AC-010

`trigger-cases.json` 与 `validate_contract.ps1` 保留对规则、skill、引用和 case 集合的确定性检查。隔离 evaluator、planner、`current.json`、attempt ledger 与恢复目录继续承担模型路由研究，但没有任何部署消费者。部署 manifest schema 9 只记录 payload、受管资产生命周期和回滚所需事实；读取 schema 8 历史部署时忽略旧 routing evidence 字段。研究失败保持可诊断且不得自动重试，但不会改变 Validate、Deploy、Status 或 Rollback 的结论。
