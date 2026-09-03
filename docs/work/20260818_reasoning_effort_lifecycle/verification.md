# 推理深度生命周期：验证

## 平台与因果证据

- OpenAI [Model guidance](https://developers.openai.com/api/docs/guides/latest-model) 明确要求有意选择 `reasoning.effort`，并按工作负载比较质量、延迟和成本；它没有把档位选择绑定到 Goal。
- OpenAI [Follow a goal](https://learn.chatgpt.com/use-cases/follow-goals) 把 Goal 定义为跨轮持续执行 durable objective 的入口，适用于需要自动继续直到可验证停止条件的长期工作。
- 当前真实 Codex 线程的 max→high→max 实验中，两次设置都返回 `updateAccepted=true`、`readbackVerified=true`、`matchesRequestedEffort=true`、`sentTurn=false`；设置当轮保持原档位，由 Goal 拉起的真实下一轮才采用新档位。历史同一线程还存在无 Goal 的配置变化。合并证据只支持“设置影响 next turn；Goal 可续轮”，不支持“只有 Goal 才能设置”。

## 组件与真实线程

| 检查 | 结果 | 直接证明范围 |
| --- | --- | --- |
| `node --check skills/reasoning-governor/scripts/reasoning-governor.mjs` | 通过 | Node 模块语法有效 |
| `node --test skills/reasoning-governor/tests/test_reasoning_governor.mjs` | 8/8 通过 | 小帧读写、设置读回、1-byte 结构分块、null/缺失、10 MiB 中段字段、正文伪字段和默认模型回执 |
| `skill-creator/scripts/quick_validate.py`（Python UTF-8 模式） | 通过 | `SKILL.md` frontmatter、名称与基础结构有效；Windows 系统默认 GBK 不作为 UTF-8 项目文件的失败 oracle |
| 修改前真实 `-Status` | 19,062,770-byte snapshot 返回 `readbackVerified=false`、档位 null、无传输错误 | 固定 4 MiB tail 对当前长对话产生误判 |
| 修改后真实默认 `-Status` | `exit=0`，`{ok:true op:status effort:max}` | 仓库脚本能从当前长对话读回实际 next-turn 配置，且默认模型视图最小充分 |
| 修改后真实 `-View machine` | `readbackVerified=true`、`currentConfiguredEffort=max`，snapshot 随对话增长至约 19.2 MB | 完整 machine receipt 与默认模型视图来自同一次 canonical 语义 |

同一次真实成功状态的默认模型回执为 30 个 ASCII 字符，完整 machine JSON 为 599 个字符；前者只保留 `ok/op/effort`。字符差只证明表示规模，是否充分由上述真实读回、machine 对照和组件场景共同证明，不把字符比例冒充固定 Token 收益。

## 后继负担门控实测

当前对话先直接观察到一次漏判：较长的 skill 生命周期探索包含真实会话取证、平台合同、跨 owner 设计和三阶段验证，但执行前没有调用 governor。后继实施本修正时，模型先把下一段目标判断为 `high`，再运行真实 `-Status`，读回 `{ok:true op:status effort:max}`；由于设置只影响下一轮、当前任务预计能在本轮闭合，降到 high 不能摊销中断和恢复成本，因此没有设置。该结果直接覆盖“目标判断可以触发查询，但查询不必触发切换”，不证明尚未发布规则已经改变当前运行。

以 `o200k_base` 计，候选全局规则由后继修改前 4,730 增至 4,784 tokens；Reasoning Governor 的 description 由 82 增至 118 tokens，按需加载正文由 1,197 增至 1,398 tokens。新增常驻成本为 90 tokens，正文增量只在 skill 被选中时加载；它换取长探索不漏判以及短任务、已有充分读回不做固定查询的可验证边界，不把单次状态调用或潜在模型质量收益伪装成固定节省比例。

## 规则、路由与独立证据

`validate_contract.ps1` 通过：90 cases、49 strict routing、6 strict references，11/11 项目 skill 同时具有正向和非触发覆盖。后继严格场景覆盖无 Goal 的可摊销错配、长探索与治理 skill 共存、短任务不查询、当前读回已经充分、显式短状态查询仍执行、用户固定范围和纯设计讨论。

首次独立 Routing 输入把“固定 low 不升档”和“高风险迁移审查”放在同一场景，独立模型合理额外选择 `change-governance`，严格门禁拒绝该结果。测试 oracle 随后只把工作对象收敛为高难度纯逻辑证明，保留档位冲突而移除无关治理触发；没有放宽禁止额外 skill 的门禁，也没有复用失败结果。

最终三阶段证据由三个不同 evaluator run 生成并合并到 `development/skill-routing/evidence/current.json`：

| 阶段 | 结果 | Capsule SHA-256 |
| --- | --- | --- |
| Routing | 90/90，严格额外 skill 检查通过 | `F6B6B4946221DE5BABD8858DBD18CADD9AD89B47922AC29A56350BC09D53E89F` |
| Policy | 90/90 满足期望和禁选标签 | `5848B33EA94810EF04894F5CAF144084D3C5222333AAC763840A18BE49BCA39C` |
| References | 21/21 满足条件引用合同 | `ADAC255B8C128BF66049B4E7BF932BEDC8566813D4063F30BA4403FBC6827454` |

候选 bundle 为 `24CC35AECD613FAAED13E45A2B2FE69D724FFA9E53009E049CA8942FC12EBA18`。Policy 中未声明且未禁选的兼容标签按项目既有合同保留为诊断；正式期望、禁选与 Routing/References 严格集合全部通过。第一次后继 capsule 评估进行时，主审发现 description 可能让短任务非触发覆盖用户显式查询，随即停止并作废；新候选增加显式短查询严格正例后重新独立评估，没有复用旧结果。

## 2026-08-23 长期阶段迟滞验证

- `reasoning-governor` 的结构校验在 Python UTF-8 模式通过；系统默认 GBK 首次读取 UTF-8 中文时报 `UnicodeDecodeError`，输入环境改为项目编码合同后通过，不把相同失败原样重跑。
- `validate_contract.ps1` 通过：106 cases、65 strict routing、17 strict references，13/13 skill 均有正向与非触发覆盖。新增严格场景分别证明可预期长期阶段允许进入 governor、孤立高难项和短机械尾段不得因自主切换触发 governor。
- `test_routing_infrastructure.ps1` 通过：6 suites、22 个 PowerShell syntax files、0 模型调用。
- 当前 generation 为 `E71F2D718163322E5F4BA6804C38A57F0681B988A4C32DED06F25A4BB44CF75A`。Routing、Policy、References 三阶段均由当前来源链恢复或零 Token 重验，计划为 `reuse=3`、`evaluate=0`、`blocked=0`；活跃账本 5/6 收据、没有 `started`。
- 首次 Policy 结果把概念讨论误选为实际委派行为，oracle 保持 skill 禁选并移除不适用行为标签；首次 References 结果又暴露两个旧严格场景漏列真实必需引用。修正 oracle 后只对原已通过结果按精确来源收据重验，没有重采样或放宽选择门禁。

## 部署候选与边界

从暂存候选生成的独立干净 worktree 中，`test_manage_agentbase.ps1` 全部通过，随后正式 `manage_agentbase.ps1 -Action Validate` 返回 `valid=true`，证明长期阶段迟滞、代理角色、路由证据、受管资产与部署合同在同一提交态一致。

用户明确授权后，从当时的独立干净 worktree 以 `DirectCompatibility + InstallPortableSettings` 向真实 Codex 根完成一次部署；旧入口返回 `published:true`、`changed:16`，同范围 Status 也返回旧字段 `published:true`。这些字段是 schema 7 的历史命名，只证明安装文件和部署合同，不表示形成版本或分发资产；当前已启动任务不会追溯加载新规则。

## 2026-09-03 已知后继轮边界复验

- `reasoning-governor` 结构校验通过；`validate_contract.ps1` 通过，共 142 个场景、88 个严格路由场景、28 个严格引用场景，13/13 skill 同时具有正向与非触发覆盖。
- 新增严格非触发场景明确：一个可在已开始当前轮闭合的中等多文件替换，没有 active Goal 或已知后继轮时，不选择 governor。无 Goal 正例则明确下一次自然用户消息会继续同一长期证明，设置成功后结束当前轮等待。
- 修改前独立样本 `v8-replacement-assets-candidate` 完成替换并通过 3/3，但额外加载 governor 且一次状态查询失败；修改后同任务新进程样本 `v9-replacement-assets-final` 通过 4/4，没有加载或调用 governor，旧生产路径、旧测试和旧 gate 均退出，独立 audit 合同保留。
- 后继样本耗时 296.6 秒、30 条命令、15 个工具批次，输入 804697、其中缓存 748160，输出 9276；上一样本为 302.1 秒、31 条命令、9 个工具批次，输入 675069、其中缓存 623104，输出 10627。该对照只证明误查询消失且质量保持，不证明总成本改善；多数独立源码读取和最终静态检查已经合批，一次已知 skill 对仍未合批不足以支持新增同义规则。
- `test_manage_agentbase.ps1` 通过，正式 `Validate` 返回 `valid:true`。在用户本轮持续 Deploy 授权下，候选已部署到 `DirectCompatibility + InstallPortableSettings`，紧随的 Status 返回 `deployed:true`；没有形成版本、标签或分发资产，也没有执行 Release。

实验原始事件、结果和结构化摘要保留在仓库外的本地主机实验目录，不进入 Codex payload。部署只证明安装内容与确定性合同；当前已启动任务不会追溯加载新规则，行为结论来自上述独立新进程样本。
