# AgentBase 当前接手状态

状态截点：2026-08-23（Asia/Shanghai）。

## 一句话状态

子代理触发冲突修订已完成源码并同步私有远端：用户未指定时，只有必要、独立有界且有净收益的 `evidence`/`experiment` 委派才是可推翻的 `should`，不是必须创建。用户叫停正式检查后，本次只手动应用 4 个安装文件；正式路由 evidence、Validate、Publish 与 Status 没有闭合。当前没有开放源码实施项，现有 Windows SWE sandbox 候选仍留在 dirty worktree，属于另一工作边界。

## 当前源码、安装与未提交边界

- 最新行为实现提交为 `3977452`，已非强制推送到私有 `origin/main`；本文件所在后继提交只记录手动应用收据。不得用历史 HEAD、Release 或安装副本反推当前源码。
- 用户要求停止检查并手动应用后，已复制 `global/AGENTS.md` 及 `subagent-orchestration` 的 `SKILL.md`、`agents/openai.yaml`、`references/coordination.md` 到 `C:\Users\gzxt\.codex` 对应位置；手动回滚备份为 `C:\Users\gzxt\.codex\backups\AgentBase-manual-20260823-050357`。本次没有运行正式 Publish、发布后 Status 或安装内容读回；此前的 DirectCompatibility 发布收据只覆盖旧版本，不能证明本修订。
- 必须保留并排除于本版本后继提交：根 `README.md`；`development/agent-evaluation/` 中除已提交的项目代理/evaluator profile 解耦外的 Windows SWE sandbox 修改及 `vendor/`；`docs/requirements.md` 中 AC-062—AC-065 等评测合同工作树 hunk。不要清理、回退或把它们误归入本版本。
- Windows SWE 仍是 9 题、Sol/medium 与 Luna/max 的 evaluator profile；它与安装到候选 Codex home 的项目自定义代理不是同一集合。本版本只修正该消费者的职责混淆，没有执行 elevated setup、qualification、候选模型或外部 Verifier。

## 当前职责与证据

- `global/AGENTS.md` 只保存跨任务选择：每段工作仍判断目标档位，但只有可预期长期负担变化才写 next-turn 设置；用户明确指定是否使用子代理时优先遵守，用户未指定时只有必要、独立有界且有净收益的取证或试路才默认委派，否则主代理直接完成。该默认是可由现场证据推翻的 `should`，不是无条件创建义务。
- `global/agents/evidence.toml` 与 `experiment.toml` 是模型、档位和角色指令的唯一配置 owner；全局规则与 `subagent-orchestration` 只使用稳定语义身份。更换模型或档位不需要改 validator、skill 或调用名。
- `subagent-orchestration` 持有 evidence packet、主代理逐项接纳、evidence→experiment 交接、最小判别实验、反例熔断、隔离清理和无后代代理协议；子代理输出不扩大授权，也不直接成为生产实现或完成证据。
- `reasoning-governor` 只管理线程状态和 next-turn 设置，不重新裁决复杂度。孤立高难项和短机械尾段不触发自主转换。
- 本次路由计划 generation 为 `B254B67DADBDC1CA356FADDD1B51766558FD3ED9C2733A8E3A843248E9F07E7E`；用户叫停前 Policy 与 Routing 已通过，References 在终止后按事实记为 `execution_failed`。`current.json` 未合并本次结果，不能沿用旧 generation 声称本修订的路由证据已经闭合，也不得自动重试。
- 按用户要求，本次未继续确定性测试、部署 Validate、正式 Publish、发布后 Status 或独立模型行为验证。手动复制只证明命令完成，不证明部署账本、规则合同或模型行为。
- Codex 在任务启动时构建指令链，因此当前已启动任务不会追溯加载新规则；真实角色选择和交接行为只能在新任务中验收。

## 下个对话的最小恢复步骤

1. 读取根 `README.md` 与本文件，运行 `git status --short`；保留上述 README、Windows SWE 与 requirements dirty 边界，不清理、不回退、不并入无关提交。
2. 若本文件所在提交已在私有上游且工作树只剩上述边界，则没有开放源码实施项；正式 evidence/Validate/Publish/Status 只有在用户明确要求重开时才继续，不能因其未闭合自动启动。
3. 本次是绕过部署账本的手动覆盖，`DirectCompatibility + InstallPortableSettings Status` 不能单独证明这 4 个文件的真实内容；任务确实依赖安装状态时，应按精确映射只读核对文件，或在取得新授权后重新走正式发布。
4. 在新任务验证本版本时，分别观察：长期阶段是否才触发推理切换；静态取证是否选择 `evidence` 并逐项接纳；路径试验是否选择 `experiment`、保持隔离并由主代理重新正式实现。行为未实测前不得把安装成功外推为模型行为成功。
5. Windows SWE 的 elevated setup/qualification 仅在相应外部操作授权下运行；普通仓库验证不得初始化 sandbox、克隆任务、安装依赖或启动候选模型。
6. 本次手动应用授权已经消耗；任何后续手动或正式 Codex 发布都必须重新取得当次明确同意。
