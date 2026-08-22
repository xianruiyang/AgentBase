# AgentBase 当前接手状态

状态截点：2026-08-23（Asia/Shanghai）。

## 一句话状态

主代理推理档位迟滞与语义子代理编排已经完成、验证、同步私有远端并以 `DirectCompatibility + InstallPortableSettings` 发布：主代理只为可预期长期阶段切换 next-turn 深度；`evidence` 当前使用 Luna/medium，`experiment` 当前使用 Sol/low，主代理保留正式实现和交付责任。当前没有开放实施项，现有 Windows SWE sandbox 候选仍留在 dirty worktree，属于另一工作边界。

## 当前源码、安装与未提交边界

- 行为实现提交为 `0aba411`，已非强制推送到私有 `origin/main`；本文件所在后继提交只闭合真实发布收据。不得用历史 HEAD、Release 或安装副本反推当前源码。
- 发布前 `srcq 0.4.2` Status 为 ready，`srcq doctor` 与 `srcq query scc doctor` 均为 ok。正式 Publish 返回 `published:true`、`changed:16`，退役 `agents\luna.toml` 与 `agents\sol.toml`；回滚备份为 `C:\Users\gzxt\.codex\backups\AgentBase-20260823-030345-c7ac8ea8`。发布后同模式 Status 为 `published:true`。
- 必须保留并排除于本版本后继提交：根 `README.md`；`development/agent-evaluation/` 中除已提交的项目代理/evaluator profile 解耦外的 Windows SWE sandbox 修改及 `vendor/`；`docs/requirements.md` 中 AC-062—AC-065 等评测合同工作树 hunk。不要清理、回退或把它们误归入本版本。
- Windows SWE 仍是 9 题、Sol/medium 与 Luna/max 的 evaluator profile；它与安装到候选 Codex home 的项目自定义代理不是同一集合。本版本只修正该消费者的职责混淆，没有执行 elevated setup、qualification、候选模型或外部 Verifier。

## 当前职责与证据

- `global/AGENTS.md` 只保存跨任务选择：每段工作仍判断目标档位，但只有可预期长期负担变化才写 next-turn 设置；子任务必须独立有界且有净收益，主代理保留目标、授权、规划、正式实现、验收、Git 与发布。
- `global/agents/evidence.toml` 与 `experiment.toml` 是模型、档位和角色指令的唯一配置 owner；全局规则与 `subagent-orchestration` 只使用稳定语义身份。更换模型或档位不需要改 validator、skill 或调用名。
- `subagent-orchestration` 持有 evidence packet、主代理逐项接纳、evidence→experiment 交接、最小判别实验、反例熔断、隔离清理和无后代代理协议；子代理输出不扩大授权，也不直接成为生产实现或完成证据。
- `reasoning-governor` 只管理线程状态和 next-turn 设置，不重新裁决复杂度。孤立高难项和短机械尾段不触发自主转换。
- 静态合同为 106 cases、65 strict routing、17 strict references，13/13 skill 具有正向与非触发覆盖；当前 generation 为 `E71F2D718163322E5F4BA6804C38A57F0681B988A4C32DED06F25A4BB44CF75A`，最终刷新 `reuse=3`、模型调用 0、活跃账本 5/6 且无 unfinished。
- 干净提交态 `test_manage_agentbase.ps1` 通过；Windows SWE 确定性门禁每次 46/46；正式部署 Validate 为 `valid:true`。首次集成失败确实暴露并修正了 evaluator profile/项目代理集合混淆，没有以重跑掩盖。
- 发布只证明文件安装和部署合同。Codex 在任务启动时构建指令链，因此当前已启动任务不会追溯加载新规则；真实角色选择和交接行为需在新任务中验收。

## 下个对话的最小恢复步骤

1. 读取根 `README.md` 与本文件，运行 `git status --short`；保留上述 README、Windows SWE 与 requirements dirty 边界，不清理、不回退、不并入无关提交。
2. 若本文件所在提交已在私有上游且工作树只剩上述边界，则没有开放仓库实施项；只有出现新行为反例、选择其他子计划或改变跨组件方向时才读取 `docs/plan.md`。
3. 任务依赖真实安装状态时，按部署说明只读运行 `DirectCompatibility + InstallPortableSettings Status`；不要用本文件的最后已知值代替读回。
4. 在新任务验证本版本时，分别观察：长期阶段是否才触发推理切换；静态取证是否选择 `evidence` 并逐项接纳；路径试验是否选择 `experiment`、保持隔离并由主代理重新正式实现。行为未实测前不得把安装成功外推为模型行为成功。
5. Windows SWE 的 elevated setup/qualification 仅在相应外部操作授权下运行；普通仓库验证不得初始化 sandbox、克隆任务、安装依赖或启动候选模型。
6. 本次 Publish 授权已经消耗；任何后续真实 Codex Publish 都必须重新取得当次明确同意。
