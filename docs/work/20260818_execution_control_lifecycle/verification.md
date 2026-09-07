# 执行控制与 Skill 上下文生命周期：验证

## 真实上下文与平台证据

- 当前真实 Codex 会话最近一次压缩发生在 `2026-08-17T23:39:35.732Z`。此后同一来源、未变化的 `openai-docs/SKILL.md` 分别在 `23:45:53.971Z` 与 `23:52:35.040Z` 被完整读取，中间没有压缩；第二次读取没有取得新规则或恢复已丢失正文。完整会话身份只保留在机器日志。
- 同一会话中，`change-governance/SKILL.md` 在压缩前已经完整读取，压缩后的 `replacement_history` 既不含 skill 名称，也不含唯一正文句“只在触发条件命中时”。这直接证明本次压缩没有保留该正文，不外推所有压缩都必然如此。
- OpenAI [Build skills](https://learn.chatgpt.com/docs/build-skills) 把 skill 定义为渐进披露：先提供名称、description 与路径，选中后加载完整 `SKILL.md`，并由 Codex 检测 skill 变化。公开合同没有把每个 new turn 定义为正文失效边界。
- 当前 WindowsApps 安装拒绝从项目终端启动 `codex.exe`；`codex --version`、`codex exec --help` 和 `codex exec resume --help` 均以访问被拒绝结束，因此没有把不可执行的嵌套 CLI 热更新实验伪装成已验证。已知内容变化后的强制重读由规则与严格场景覆盖。

这些证据共同支持把生命周期拆为三项：每轮重新路由、正文按上下文可用性复用或恢复、引用按当前动作渐进加载。它们不支持跨对话持久缓存，也不支持压缩后按历史使用记录批量重读。

## 2026-08-18 原范围规则、路由与独立证据

`validate_contract.ps1` 通过：86 cases、45 strict routing、5 strict references，11/11 项目 skill 同时具有正向和非触发覆盖。新增严格场景覆盖实施中架构判断失效、复杂任务未显式要求计划、简单任务不建形式计划、未压缩正文复用、压缩后补回已选 skill、压缩后不加载历史未选 skill，以及已知内容变化后的重读。

最终三阶段证据由三个独立 evaluator 只读取 detached capsule 后生成，并由正式合并脚本写入 `development/skill-routing/evidence/current.json`：

| 阶段 | 结果 |
| --- | --- |
| Routing | 86/86，严格额外 skill 检查通过 |
| Policy | 86/86 满足期望和禁选标签 |
| References | 20/20 满足条件引用合同 |

候选与 capsule 的完整机器身份保留在正式 evidence。三个结果都声明 `detached-capsule`、未访问仓库和未访问隐藏期望；Routing 与 Policy 各覆盖 86 项，References 覆盖实际触发的 20 项。

## 2026-08-18 原范围上下文成本边界

以 `tiktoken 0.13.0 / o200k_base` 计，当前 11 个项目 `SKILL.md` 主文件合计 11,591 tokens，单项 260—2,049 tokens；真实重复读取的 `openai-docs/SKILL.md` 为 1,103 tokens。三项机制进入 `global/AGENTS.md` 后，候选常驻正文由本轮修改前的 4,621 增至 4,730 tokens，增加 109；对已观察到的一次 1,103-token 重复读取，净减少约 994 tokens。该差值只说明已观察路径，不作为固定节省比例，也不允许跳过应选 skill 或必要引用。

## 2026-08-18 原范围部署候选与边界

- `validate_contract.ps1` 的 PowerShell 语法解析通过。
- `manage_agentbase.ps1 -Action Validate` 返回 `valid=true`，证明当前仓库候选的全局规则、路由证据、受管资产和部署合同一致。
- 本轮没有执行 `Publish`，没有写入真实 Codex，也没有提交或推送 Git。当前运行不会追溯加载候选规则；真实行为只能在用户另行明确同意发布后，于新任务中验证。

## 2026-08-21 重开验证

原完成证据只证明计划启动、架构失效回退和 skill 正文生命周期，没有证明 AC-036 的运行期纵向闭环。九题评测准备在首个真实消费者尚未成立时横向展开，并由前置失败逐层遮蔽下游，构成直接重开证据；本轮据此新增 `execution-governor` 并重新划分五项 owner，而不是在原软优先级上继续追加特例。

静态与零模型验证结果：

- `skill-creator/scripts/quick_validate.py` 在显式 UTF-8 解释器模式下验证 `execution-governor` 结构通过；系统默认 GBK 导致的首次 `UnicodeDecodeError` 只证明校验器宿主编码，不是 skill 内容失败。
- `validate_contract.ps1` 通过：96 cases、55 strict routing、10 strict references，12/12 skill 都有正向与非触发覆盖；全局与项目指令合计保持在项目 28,672-byte 上限内。
- `test_routing_infrastructure.ps1` 通过 6 个 suite，解析 22 个 PowerShell 文件，模型调用为 0。

正式 detached 路由证据已原子合并；完整 generation 与 capsule 身份保留在机器 evidence：

| 阶段 | 结果 |
| --- | --- |
| Routing | 96/96；共享前提切片选择 `execution-governor` 与 `task-table-manager` |
| Policy | 96/96；该切片包含 `fact_first` 与 `vertical_validation_closure` |
| References | 27/27；该切片选择两项执行控制引用及任务查询/依赖引用 |

最后一次刷新只运行 References 一次，并复用已通过的 Routing 与 Policy；没有对相同失败输入重采样。

这些证据直接覆盖规则结构、skill 发现、粗粒度行为标签和条件引用选择，不证明新 skill 的控制循环会在真实项目中按预期执行。只包含本次暂存内容与原 HEAD 的独立临时 Git tree 通过 skill 校验、同一合同与路由基础设施，并由 `manage_agentbase.ps1 -Action Validate` 运行 45 项基线 Windows SWE 确定性测试后返回 `valid:true`；临时 worktree 随后删除。当前组合工作树的同一 Validate 也通过并运行 66 tests；该数量包含接手时已有且继续保留的评测 dirty 候选，只证明组合兼容。模型 evaluator 保持禁用；真实 Codex 继续使用已安装版本，本轮没有 Publish 授权，也没有新任务运行时验收。

## 2026-08-23 UE 实践反例与第二版验证

用户提供的两天大型 UE 工作流证明第一版仍有适用失败：现有规则已经禁止阶段文档保存原始日志并要求消费者证据回流，但任务状态没有及时记录 schema 进展和 normals verifier 反例；carrier/mode/revision/persistence 维度启动过晚，重复 UE 命令仍由模型人工拼装。用户明确裁决“利用本项目的模型犯错，本质上也是本项目犯错”，因此新增 AC-066，并把规则存在与真实行为证据继续分开。

确定性验证：

- `skills/task-table-manager/tests/test_taskctl.py`：98 tests passed；新增用例覆盖执行检查点 CAS 写入/清空、显式关联 DCR 的同源 context/source snapshot，以及 `validation_dimensions` 与结果 `validation_coverage` 的生命周期分离。旧状态缺少新字段仍按空值读取。
- `quick_validate.py`：`delivery-workflow`、`execution-governor`、`task-table-manager`、`source-query` 四项全部通过。
- `validate_contract.ps1`：101 cases、60 strict routing、15 strict references、12/12 skills 正向与非触发覆盖；全局与项目指令合计 28,540 bytes，仍低于 28,672-byte 合同上限。
- `test_routing_infrastructure.ps1`：6 suites、22 个 PowerShell syntax files、0 模型调用。专项 recovery 测试同时证明同代恢复、`oracle_revalidation`、篡改来源拒绝、跨代 carry-forward、原子 merge 和 staging 清理。
- `manage_agentbase.ps1 -Action Validate`：从 Git 暂存索引构造的独立临时 worktree 在 evaluator 禁用下运行 46 项基线 Windows SWE 基础设施测试并返回 `valid:true`；当前组合工作树另运行 67 项并通过，后者包含接手时保留的 dirty 评测候选，只证明组合兼容，不把它纳入本版本范围。临时 worktree 已删除。

最终 detached evidence 已合并；完整 generation 与 capsule 身份保留在机器 evidence：

| 阶段 | 结果 |
| --- | --- |
| Routing | 101/101 |
| Policy | 101/101 |
| References | 38/38 |

模型阶段的失败没有按不变输入重采样：每次 Routing/Policy 失败都先修正可见触发或标签边界并形成新身份；最终 References 输出只因隐藏 oracle 过度要求 CLI 引用而失败。修正 oracle 后，相同 stage 文件、可见输入、capsule 和 evaluator 由新增 `oracle_revalidation` 精确绑定旧失败收据并以 0 input/output tokens 通过；最后刷新为 evaluator run 0、recovered 2、oracle revalidated 1。当前 evaluation plan 为 0 evaluate、3 reuse、0 blocked/pending。

这些证据证明仓库规则、taskctl 结构、评测恢复机制、路由、行为标签和引用选择；不证明真实 Codex 已加载第二版，也不证明 UE 新任务中的写回、维度边界或 runner 选择已经改变。本轮没有 Publish 授权，真实安装保持上次发布版本；行为验收必须留到另行授权发布后的新任务。

## 2026-08-23 第三版验证与发布

用户表示准备发布后，才对稳定候选集中执行完整验证。确定性证据如下：

- `skills/task-table-manager/tests/test_taskctl.py`：102 tests、137.195 秒，全部通过；覆盖同源 `active_frontiers`、执行检查点、结果覆盖边界和 `result_history_state_write_drift` 的 advisory/恢复语义。
- `quick_validate.py`：本次涉及的 `delivery-workflow`、`execution-governor`、`task-table-manager`、`change-governance` 与 `subagent-orchestration` 均通过；显式 `-X utf8` 修正宿主默认 GBK 后没有内容错误。
- `validate_contract.ps1`：114 cases、73 strict routing、21 strict references、13/13 skills 具有正向与非触发覆盖。
- `test_routing_infrastructure.ps1`：6 suites、22 个 PowerShell syntax files、0 模型调用、18.731 秒；专项恢复测试证明同代恢复、跨代 passed carry、同代或跨代 `oracle_revalidation`、篡改来源拒绝、原子 merge 与 staging 清理。
- `manage_agentbase.ps1 -Action Validate`：67 项 Windows SWE 基础设施测试通过，返回 `valid:true`；evaluator 保持禁用，没有启动 elevated sandbox、外部 clone、qualification 或候选模型。

最终 detached evidence 已合并；完整 generation 与 capsule 身份保留在机器 evidence：

| 阶段 | 结果 |
| --- | --- |
| Routing | 114/114 |
| Policy | 114/114 |
| References | 45/45 |

验证中每次模型失败都先区分规则/引用边界、oracle 与恢复基础设施，再改变对应输入或 oracle；没有对未变输入原样重采样。最后一份 References 输出只包含一个合理的可选引用差异，移除不成立的严格排他后由同一文件、capsule、evaluator 和失败收据以 0 Token 复核；最终刷新为 evaluator run 0、recovered 2、oracle revalidated 1。

用户随后针对本次操作明确授权发布。`DirectCompatibility + InstallPortableSettings` Publish 再次运行 67 项基础设施测试并通过，写入 20 个受管资产，回滚备份为 `<CODEX_ROOT>\backups\AgentBase-20260823-150728-c301230b`；同范围只读 Status 返回 `published:true`。这些证据证明仓库候选和真实安装一致，不证明当前已启动任务追溯加载新规则；子代理选择、局部快速路径、状态写回和 preflight 的真实模型行为仍须在新任务中观察。

## 2026-08-23 第四版发布前验证

真实多组件工作再次暴露：已有“不机械展开笛卡尔积”规则主要约束验证选择，模型仍会在首个可用结果成立前逐组合编写实现、fixture、示例和测试。用户进一步校准，纵向开发不是从首条路线演化设计，而是在上游设计、owner、契约与依赖均已完成后，深度优先制作其中一个正式可用结果并以真实消费者验证；缩小的是同时展开的结果数量与证据成本，不是生产实现。第四版据此新增 AC-075，并在原执行 owner 内形成可组合 coverage basis，没有新增设计 owner、任务字段、矩阵文件、CLI 门禁或固定 case 上限。

发布前集中验证结果：

- `quick_validate.py`：`execution-governor`、`delivery-workflow` 与 `task-table-manager` 全部通过；三个主 skill 都保持 8,192-byte 上限内。
- `validate_contract.ps1`：117 cases、76 strict routing、23 strict references、13/13 skills 具有正向与非触发覆盖。新增场景覆盖 60-tuple 测试编写停滞、高阶三元交互和低成本 2×2 闭集快速路径。
- `test_routing_infrastructure.ps1`：6 suites、22 个 PowerShell syntax files、0 模型调用、20.962 秒。
- `manage_agentbase.ps1 -Action Validate`：67 项 Windows SWE 基础设施测试通过并返回 `valid:true`；evaluator、外部 clone、qualification、候选模型和 elevated sandbox 均未启动。

最终 detached evidence 已合并；完整 generation 与 capsule 身份保留在机器 evidence：

| 阶段 | 结果 |
| --- | --- |
| Routing | 117/117 |
| Policy | 117/117 |
| References | 46/46 |

最终刷新只运行 References 一次，Routing 与 Policy 通过不可变上一代收据各 carry-forward 一次；刷新后计划为 0 evaluate、3 reuse、0 blocked/pending。形成候选期间的 Policy 反例使小而廉价闭集明确退出 coverage-basis 治理，并删除不改变动作的冗余严格标签；References 反例则区分依赖合同与 authoring 工具、组合决策与失败成本引用。每次重新评估前都改变了相应模型可见定义或引用入口；没有对未变输入原样重采样。

实现提交 `ce5de0f` 的独立临时 worktree 运行 46 项基线基础设施检查并返回 `valid:true`，排除了接手时已有 dirty 评测候选；当前组合工作树的 67 项检查也通过，只补充证明两者兼容。用户针对本次操作明确授权后，`DirectCompatibility + InstallPortableSettings` Publish 再次运行 67 项检查并通过，更新 7 个受管对象，回滚备份为 `<CODEX_ROOT>\backups\AgentBase-20260823-190448-db62872f`；同范围只读 Status 返回 `published:true`。这些证据证明仓库候选与真实安装一致，不证明当前已启动任务追溯加载第四版，也不替代新任务中对实际纵向执行和组合覆盖行为的观察。

## 2026-09-03 第五版候选静态验证

UeAgentInterface15 的真实 trace 证明第四版抽象原则仍未稳定进入修改动作：公共合同未稳时横向展开消费者，旧测试与生产迁移交织，多个消费者绑定构建，首错后逐点重跑，子代理返回超过主线即时接纳能力，代码量取代纵向闭环成为进展表达。第五版据此增加活动切片锁、首错后的邻接 preflight、消费者批次解绑和按证据前沿消费子代理结果；不新增状态字段、CLI 门禁、固定子代理数量或领域检查清单。

当前只执行候选形成期的低成本静态检查：

- `quick_validate.py`：`execution-governor` 与 `subagent-orchestration` 均通过；首次默认 GBK 读取失败后，仅以 `PYTHONUTF8=1` 重跑同一内容，确认是宿主解释器编码而非 skill 内容错误。
- `validate_contract.ps1`：137 cases、87 strict routing、28 strict references，13/13 skills 具有正向与非触发覆盖；新增三项场景分别覆盖活动切片锁、首错后邻接 preflight 和子代理结果接纳顺序。
- `trigger-cases.json` 可解析，`git diff --check` 通过。

detached 路由刷新首次取得两个失败阶段：新活动切片场景把“只决定下一动作”过度要求为立即选择 `change-governance`，另有两个既有 Policy 标签未被稳定识别；修正隐藏 oracle 与 `read_only`/`authority_lifecycle` 可见定义后，Routing 与 Policy 以改变后的输入通过。References 随后只漏选已有唯一活动消费者场景不需要的 `decision-frontier.md`；移除该过严隐藏要求后，正式刷新恢复两个已通过阶段并以零模型 Token 复核 References，最终没有对未变输入重采样。

正式部署证据：

- `manage_agentbase.ps1 -Action Validate` 返回 `valid:true`。
- 用户针对本次操作明确授权后，`DirectCompatibility + InstallPortableSettings` Deploy 更新 6 个受管对象；回滚备份为 `<CODEX_ROOT>\backups\AgentBase-20260903-165708-41b81ce9`。
- 同范围 Status 返回 `deployed:true`。

这些证据证明第五版仓库真源、路由证据、部署 payload 与真实安装一致，没有创建版本、标签或发行资产。当前已启动任务不会追溯加载新规则；第五版能否在复杂 UE 新任务中阻止静默切换消费者和未闭合分支堆积，仍须在新任务中取得实际行为证据。

## 2026-09-03 第六版替换闭环验证

第五版后的持续证据表明，抽象的最低充分、旧路径退出和有效 oracle 仍可在动作层退化为加法式修补：新机制加入后保留旧同责路径，契约变化后继续维护只绑定旧实现的测试与门禁，评审修复后把建议递归加入当前实现。第六版据此实现 SOL-028；没有新增 skill、状态字段、CLI、影响账本或硬门禁。

候选与路由验证：

- `execution-governor`、`change-governance`、`delivery-workflow` 与 `task-table-manager` 的结构检查通过；全局候选为 18,306 bytes，与项目规则合计 27,721 bytes，保留 951 bytes 组合预算；`task-table-manager` 为 7,928 bytes。
- `validate_contract.ps1` 通过：141 cases、87 strict routing、28 strict references，13/13 skills 具有正向与非触发覆盖。
- 路由形成期的反例用于修正隐藏 oracle 与引用边界：已确认的独立并存和单一评审阻塞项保留快速路径；失效验证资产不强制无关标签；Task Table 的只读影响查询、状态写回与合同修改分别选择引用。输入或 oracle 不变时没有重新采样。
- 最终三阶段 evidence 当前有效；计划为 0 evaluate、3 reuse、0 blocked、0 pending。零模型基础设施通过 6 suites、22 个 PowerShell 文件。
- 计划与刷新入口默认仅返回模型所需摘要，机器身份和完整结构只在显式 machine 视图中提供。

独立行为验证使用已安装 Codex CLI、`gpt-5.6-sol` 与 `max`，每个场景运行一次：

| 场景 | 目标行为 | 实际结果 | 独立验收 |
| --- | --- | --- | --- |
| 同责替换 | 新解析路径接管唯一公共入口；旧 helper 与调用序列测试退出，不建兼容或门禁 | 只修改生产文件与对应测试，删除旧 helper 和实现绑定断言，保留公共空键合同 | 4/4 tests passed |
| 评审收敛 | 一个直接 blocker 与两个相邻建议并存时，只修 blocker | 只修复 tuple/filter 行为，没有新增建议中的 class、cache 或环境配置 | 1/1 test passed |

正式 `manage_agentbase Validate` 返回 `valid:true`。用户授予本轮持续 Deploy 权限后，`DirectCompatibility + InstallPortableSettings` Deploy 更新 9 个受管对象，Status 返回 `deployed:true`；未形成版本、标签或分发资产。独立场景目录已删除。启动告警和一次测试场景中的过宽文件发现没有改变本目标结论，按评审停止边界保留为非阻塞观察，不扩成当前实施。

这些证据直接覆盖规则/skill 结构、路由、安装以及两个代表动作，不证明复杂多消费者、长构建或子代理任务已经普遍改变。后者只有出现真实反例时才按定义、路由、动作或写回的最早失效层重开。

## 2026-09-04 后继维护行为与停止判定

第六版完成后继续以独立 Codex CLI、`gpt-5.6-sol` 与 `max` 取得三组互补证据；每个样本只运行一次，没有因结果不理想重采样，原始产物保留在 `%LOCALAPPDATA%\AgentBase\experiments`，不进入仓库或部署 payload：

| 场景 | 证据边界 | 实际结果 |
| --- | --- | --- |
| 合法无动作 | 较早安装环境中的单轮样本，用于证明模型能够拒绝错误缺陷前提，不外推为第六版专属收益 | 识别既有唯一 owner 与两个消费者已满足合同，零编辑、tracked diff 为零，事后 6/6 tests passed；只有隔离环境内的 Codex/Hook 运行日志 |
| 单轮同责替换 | 第六版候选后的独立单轮样本 | API/CLI 改用 canonical owner，旧生产路径、旧专属测试和旧结构门禁退出，审计导入合同保留，4/4 tests passed；没有兼容包装或新增门禁 |
| 同任务两轮连续维护 | 本次真实安装规则下的同一线程；第二轮在第一轮完成后再次改变公共合同 | 第一轮同步 API/CLI/current tests/verify 并删除旧生产路径、旧测试与旧门禁，5/5 tests passed；第二轮再同步规范、canonical owner、API/CLI 与测试，继续拒绝已退出旧合同，7/7 tests passed；两轮均未新增平行 parser、兼容路径或结构门禁 |

连续样本补足了“单轮能替换，但后继合同变化是否又回到加法式修补”的关键未知；合法无动作样本则说明没有差距时可以停止。静态审计未发现当前动作层仍缺少定义、路由或引用入口，行为样本也没有给出新反例，因此继续向 `global/AGENTS.md` 或现有 skill 追加同义约束只会增加常驻上下文和维护责任。最终规则 payload 保持第六版，不人为创建第七版；复杂多消费者、长构建与真实子代理协作仍只在出现直接 trace 时按最早失效层重开。
