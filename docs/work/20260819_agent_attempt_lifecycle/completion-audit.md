# 完成审计

## 目标达成

- `REQ-001` / `UDES-001`、`AC-001`、`AC-002`：作为 2026-08-19 的历史两级角色合同已完成，现已被 REQ-003/UDES-003 的语义角色合同替代；旧 Luna/Sol 文件进入 retired 生命周期。
- `AC-003`：已由生命周期清单、部署 Validate、通用 path/kind/scope 回归及 Rollback 验证覆盖；无关个人代理保留测试仍通过。
- `REQ-003` / `UDES-003`：已满足。稳定调用身份为 `evidence` 与 `experiment`，具体模型和档位只在代理 TOML 中维护，主代理保留正式交付责任。
- `AC-006`：`evidence` 使用 Luna/medium，只读证据包合同和逐项接纳协议由代理配置与编排 skill 共同覆盖。
- `AC-007`：`experiment` 使用 Sol/low，在有恢复依据的隔离或精确可回滚边界运行最小操作实验；输入可直接使用主代理已确认的当前事实与快照，已有 evidence 包时才要求先逐项接纳。
- `AC-008`：portable validator 只固定语义文件集合、schema、安全模型标识和受支持档位；未来模型/档位变体回归证明角色不再与模型后缀耦合。
- `AC-009`：全局内核保留委派选择与主代理目标/交付责任，编排 skill 规定 capsule、反例熔断、无后代代理、可选 evidence→experiment 交接和实验补丁生产裁决。
- `AC-010`：全局 `should` 对有净收益且独立有界的静态取证或可逆实验发出可推翻的默认委派请求；一次便宜定向循环、无独立边界或不改变裁决时由主代理直接完成。
- `AC-011`：已满足候选合同。`experiment` 按可逆操作的信息增益选择，不要求任务陌生、静态证据穷尽、多个候选或没有初步路径；正向路由覆盖已知 owner/契约/方向下的运行探针，负向路由覆盖主代理一次便宜修改与测试即可闭环。
- `REQ-002` / `UDES-002`：已满足。正式 attempt 必须先 Begin 后 Finish；执行失败与结果失败均可审计，merge 只消费已通过 attempt ID。
- `AC-004`：已由 started 阻断、第二次需理由和第三次拒绝的回归场景覆盖。
- `AC-005`：已由 6 收据活跃周期上限、周期轮换前 unfinished 检查、上一账本哈希链和 Git 恢复合同覆盖。

## 影响闭合

- Agent owner、编排 skill、全局路由、portable validator、部署 README、manifest/rollback 测试和 managed lifecycle 已同步为语义两角色合同。
- Windows SWE 的项目代理投影与 evaluator profile 已分离：前者消费当前 `global/agents`，后者继续由九题 corpus 固定 Sol/medium 与 Luna/max；评测不再要求两份集合相等。
- attempt owner、merge、正式 validator、baseline initializer、当前账本、组件 README、静态合同和回归测试已同步为 schema 2 两阶段合同；不存在仍调用旧 merge 重试参数的当前消费者。
- 旧 `docs/work/20260818_agent_instruction_surface/` 只保留其完成时的三角色历史证据，不作为当前真源改写。

## 约束与剩余边界

- `CON-001` 与原 `CON-003` 只描述历史实施轮和历史发布；当前 `CON-005` 已满足：本次 DirectCompatibility Publish 与发布后 Status 均成功，旧 Luna/Sol 进入真实安装的退役路径。
- `CON-002` 满足：既有 `docs/plan.md` 与 `docs/handoff.md` 改动被保留并合入当前状态，没有回退无关工作。
- `CON-004` 满足：项目 `AGENTS.md` 已持久记录日常 Git 维护与私有远端同步授权，同时保留强制推送、历史重写和远端归属变更的单次授权边界；本轮源码已形成职责分离的提交并同步。
- 2026-08-23 的 `should` 修订已完成源码和手动安装，但用户明确叫停检查并要求手动发布：Routing/Policy 已通过、References 以 `execution_failed` 结束，新三阶段 evidence 没有合并，正式 Validate/Publish 和发布后 Status 未运行。因此当前只能声明“已实现并手动应用”，不声明正式发布合同或模型行为已验证。后续只有在用户重新要求正式发布或行为验收时才恢复对应证据链，不自动重试。
- 后继可逆操作 Experiment 版本已形成新的正式三阶段 evidence，通过部署 Validate，并以 `DirectCompatibility + InstallPortableSettings` 正式 Publish；发布后 Status 为 `published:true`。它取代上一条手动应用作为当前源码与安装证据，但发布只证明受管文件安装，真实选择行为仍须新任务消费新指令链。
