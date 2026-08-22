# 执行控制与 Skill 上下文生命周期：验证

## 真实上下文与平台证据

- 当前真实 Codex 会话 `01a00b1e-80a6-77b1-96be-814f4255283c` 最近一次压缩发生在 `2026-08-17T23:39:35.732Z`。此后同一来源、未变化的 `openai-docs/SKILL.md` 分别在 `23:45:53.971Z` 与 `23:52:35.040Z` 被完整读取，中间没有压缩；第二次读取没有取得新规则或恢复已丢失正文。
- 同一会话中，`change-governance/SKILL.md` 在压缩前已经完整读取，压缩后的 `replacement_history` 既不含 skill 名称，也不含唯一正文句“只在触发条件命中时”。这直接证明本次压缩没有保留该正文，不外推所有压缩都必然如此。
- OpenAI [Build skills](https://learn.chatgpt.com/docs/build-skills) 把 skill 定义为渐进披露：先提供名称、description 与路径，选中后加载完整 `SKILL.md`，并由 Codex 检测 skill 变化。公开合同没有把每个 new turn 定义为正文失效边界。
- 当前 WindowsApps 安装拒绝从项目终端启动 `codex.exe`；`codex --version`、`codex exec --help` 和 `codex exec resume --help` 均以访问被拒绝结束，因此没有把不可执行的嵌套 CLI 热更新实验伪装成已验证。已知内容变化后的强制重读由规则与严格场景覆盖。

这些证据共同支持把生命周期拆为三项：每轮重新路由、正文按上下文可用性复用或恢复、引用按当前动作渐进加载。它们不支持跨对话持久缓存，也不支持压缩后按历史使用记录批量重读。

## 2026-08-18 原范围规则、路由与独立证据

`validate_contract.ps1` 通过：86 cases、45 strict routing、5 strict references，11/11 项目 skill 同时具有正向和非触发覆盖。新增严格场景覆盖实施中架构判断失效、复杂任务未显式要求计划、简单任务不建形式计划、未压缩正文复用、压缩后补回已选 skill、压缩后不加载历史未选 skill，以及已知内容变化后的重读。

最终三阶段证据由三个独立 evaluator 只读取 detached capsule 后生成，并由正式合并脚本写入 `development/skill-routing/evidence/current.json`：

| 阶段 | 结果 | Capsule SHA-256 |
| --- | --- | --- |
| Routing | 86/86，严格额外 skill 检查通过 | `AC1DAF9F32FACF90EB60AA3EA8FE71052D1CB6656C1078240D07100932E6A1BC` |
| Policy | 86/86 满足期望和禁选标签 | `DCC51E24A4DC9F2CDDC65F8E5860C225EAAA3AA954BBC0169E98FB700BC86CA1` |
| References | 20/20 满足条件引用合同 | `FE0ACFDF5D3C8A0824E736DC082ED39E6326B504C346377AB3F766EDB6FD46B2` |

候选 bundle 为 `88CBCDCCBADE2DF6904CC95D631F04963D088D114713F5B159AAA5F35E7D66B9`。三个结果都声明 `detached-capsule`、未访问仓库和未访问隐藏期望；Routing 与 Policy 各覆盖 86 项，References 覆盖实际触发的 20 项。

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

正式 detached 路由证据已原子合并到 generation `B7A173D895A435B78D523CD39A190DF30581CC68A81A5CDE4FC12D95F3B968B6`：

| 阶段 | 结果 | Capsule SHA-256 |
| --- | --- | --- |
| Routing | 96/96；共享前提切片选择 `execution-governor` 与 `task-table-manager` | `D5235B47CA6BA45FAA6F143C32CFF09DA579481C4E6BBB6F146B50E6D28EC42C` |
| Policy | 96/96；该切片包含 `fact_first` 与 `vertical_validation_closure` | `EFFEFE0E9D51C59BB7545924997B76706DFCAB3C3BA9275F90D9253F9FE0161F` |
| References | 27/27；该切片选择两项执行控制引用及任务查询/依赖引用 | `810431901E627B90339F5FE0A3ED37A14D60FCEA5A9272E2A3685C5E77C5D802` |

References 最终 candidate bundle 为 `BBDC80FA6E84CF1EE599A72715778B582FDA18E2A304552CB873B340C33CD1B4`。最后一次刷新只运行 References 一次，并复用已通过的 Routing 与 Policy；没有对相同失败输入重采样。

这些证据直接覆盖规则结构、skill 发现、粗粒度行为标签和条件引用选择，不证明新 skill 的控制循环会在真实项目中按预期执行。只包含本次暂存内容与原 HEAD 的独立临时 Git tree 通过 skill 校验、同一合同与路由基础设施，并由 `manage_agentbase.ps1 -Action Validate` 运行 45 项基线 Windows SWE 确定性测试后返回 `valid:true`；临时 worktree 随后删除。当前组合工作树的同一 Validate 也通过并运行 66 tests；该数量包含接手时已有且继续保留的评测 dirty 候选，只证明组合兼容。模型 evaluator 保持禁用；真实 Codex 继续使用已安装版本，本轮没有 Publish 授权，也没有新任务运行时验收。

## 2026-08-23 UE 实践反例与第二版验证

用户提供的两天大型 UE 工作流证明第一版仍有适用失败：现有规则已经禁止阶段文档保存原始日志并要求消费者证据回流，但任务状态没有及时记录 schema 进展和 normals verifier 反例；carrier/mode/revision/persistence 维度启动过晚，重复 UE 命令仍由模型人工拼装。用户明确裁决“利用本项目的模型犯错，本质上也是本项目犯错”，因此新增 AC-066，并把规则存在与真实行为证据继续分开。

确定性验证：

- `skills/task-table-manager/tests/test_taskctl.py`：98 tests passed；新增用例覆盖执行检查点 CAS 写入/清空、显式关联 DCR 的同源 context/source snapshot，以及 `validation_dimensions` 与结果 `validation_coverage` 的生命周期分离。旧状态缺少新字段仍按空值读取。
- `quick_validate.py`：`delivery-workflow`、`execution-governor`、`task-table-manager`、`source-query` 四项全部通过。
- `validate_contract.ps1`：101 cases、60 strict routing、15 strict references、12/12 skills 正向与非触发覆盖；全局与项目指令合计 28,540 bytes，仍低于 28,672-byte 合同上限。
- `test_routing_infrastructure.ps1`：6 suites、22 个 PowerShell syntax files、0 模型调用。专项 recovery 测试同时证明同代恢复、`oracle_revalidation`、篡改来源拒绝、跨代 carry-forward、原子 merge 和 staging 清理。
- `manage_agentbase.ps1 -Action Validate`：从 Git 暂存索引构造的独立临时 worktree 在 evaluator 禁用下运行 46 项基线 Windows SWE 基础设施测试并返回 `valid:true`；当前组合工作树另运行 67 项并通过，后者包含接手时保留的 dirty 评测候选，只证明组合兼容，不把它纳入本版本范围。临时 worktree 已删除。

最终 detached evidence generation 为 `D0B41EA251A5E264D55ECC7447A24C0E5D987B806FE4F21A504483AD921DDE61`：

| 阶段 | 结果 | Capsule SHA-256 |
| --- | --- | --- |
| Routing | 101/101 | `22669F572A4473AB2B1CFCCDF4780F2C22DE50C46EA9413F7C24EB7F26EB4A27` |
| Policy | 101/101 | `1438470512CD533B11DE3D48AA8FD4820DCA255A13CC613545DBEF658401DF59` |
| References | 38/38 | `23DAC543CB853ABFA6D3CD9379ABC2CAC3D27AC2B4A851167AA8B8D8E63E60BE` |

模型阶段的失败没有按不变输入重采样：每次 Routing/Policy 失败都先修正可见触发或标签边界并形成新身份；最终 References 输出只因隐藏 oracle 过度要求 CLI 引用而失败。修正 oracle 后，相同 stage 文件、可见输入、capsule 和 evaluator 由新增 `oracle_revalidation` 精确绑定旧失败收据并以 0 input/output tokens 通过；最后刷新为 evaluator run 0、recovered 2、oracle revalidated 1。当前 evaluation plan 为 0 evaluate、3 reuse、0 blocked/pending。

这些证据证明仓库规则、taskctl 结构、评测恢复机制、路由、行为标签和引用选择；不证明真实 Codex 已加载第二版，也不证明 UE 新任务中的写回、维度边界或 runner 选择已经改变。本轮没有 Publish 授权，真实安装保持上次发布版本；行为验收必须留到另行授权发布后的新任务。
