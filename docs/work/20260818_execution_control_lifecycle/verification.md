# 执行控制与 Skill 上下文生命周期：验证

## 真实上下文与平台证据

- 当前真实 Codex 会话 `01a00b1e-80a6-77b1-96be-814f4255283c` 最近一次压缩发生在 `2026-08-17T23:39:35.732Z`。此后同一来源、未变化的 `openai-docs/SKILL.md` 分别在 `23:45:53.971Z` 与 `23:52:35.040Z` 被完整读取，中间没有压缩；第二次读取没有取得新规则或恢复已丢失正文。
- 同一会话中，`change-governance/SKILL.md` 在压缩前已经完整读取，压缩后的 `replacement_history` 既不含 skill 名称，也不含唯一正文句“只在触发条件命中时”。这直接证明本次压缩没有保留该正文，不外推所有压缩都必然如此。
- OpenAI [Build skills](https://learn.chatgpt.com/docs/build-skills) 把 skill 定义为渐进披露：先提供名称、description 与路径，选中后加载完整 `SKILL.md`，并由 Codex 检测 skill 变化。公开合同没有把每个 new turn 定义为正文失效边界。
- 当前 WindowsApps 安装拒绝从项目终端启动 `codex.exe`；`codex --version`、`codex exec --help` 和 `codex exec resume --help` 均以访问被拒绝结束，因此没有把不可执行的嵌套 CLI 热更新实验伪装成已验证。已知内容变化后的强制重读由规则与严格场景覆盖。

这些证据共同支持把生命周期拆为三项：每轮重新路由、正文按上下文可用性复用或恢复、引用按当前动作渐进加载。它们不支持跨对话持久缓存，也不支持压缩后按历史使用记录批量重读。

## 规则、路由与独立证据

`validate_contract.ps1` 通过：86 cases、45 strict routing、5 strict references，11/11 项目 skill 同时具有正向和非触发覆盖。新增严格场景覆盖实施中架构判断失效、复杂任务未显式要求计划、简单任务不建形式计划、未压缩正文复用、压缩后补回已选 skill、压缩后不加载历史未选 skill，以及已知内容变化后的重读。

最终三阶段证据由三个独立 evaluator 只读取 detached capsule 后生成，并由正式合并脚本写入 `development/skill-routing/evidence/current.json`：

| 阶段 | 结果 | Capsule SHA-256 |
| --- | --- | --- |
| Routing | 86/86，严格额外 skill 检查通过 | `AC1DAF9F32FACF90EB60AA3EA8FE71052D1CB6656C1078240D07100932E6A1BC` |
| Policy | 86/86 满足期望和禁选标签 | `DCC51E24A4DC9F2CDDC65F8E5860C225EAAA3AA954BBC0169E98FB700BC86CA1` |
| References | 20/20 满足条件引用合同 | `FE0ACFDF5D3C8A0824E736DC082ED39E6326B504C346377AB3F766EDB6FD46B2` |

候选 bundle 为 `88CBCDCCBADE2DF6904CC95D631F04963D088D114713F5B159AAA5F35E7D66B9`。三个结果都声明 `detached-capsule`、未访问仓库和未访问隐藏期望；Routing 与 Policy 各覆盖 86 项，References 覆盖实际触发的 20 项。

## 上下文成本边界

以 `tiktoken 0.13.0 / o200k_base` 计，当前 11 个项目 `SKILL.md` 主文件合计 11,591 tokens，单项 260—2,049 tokens；真实重复读取的 `openai-docs/SKILL.md` 为 1,103 tokens。三项机制进入 `global/AGENTS.md` 后，候选常驻正文由本轮修改前的 4,621 增至 4,730 tokens，增加 109；对已观察到的一次 1,103-token 重复读取，净减少约 994 tokens。该差值只说明已观察路径，不作为固定节省比例，也不允许跳过应选 skill 或必要引用。

## 部署候选与边界

- `validate_contract.ps1` 的 PowerShell 语法解析通过。
- `manage_agentbase.ps1 -Action Validate` 返回 `valid=true`，证明当前仓库候选的全局规则、路由证据、受管资产和部署合同一致。
- 本轮没有执行 `Publish`，没有写入真实 Codex，也没有提交或推送 Git。当前运行不会追溯加载候选规则；真实行为只能在用户另行明确同意发布后，于新任务中验证。
