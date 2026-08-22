# 完成审计

## 目标达成

- `REQ-001` / `UDES-001`、`AC-001`、`AC-002`：作为 2026-08-19 的历史两级角色合同已完成，现已被 REQ-003/UDES-003 的语义角色合同替代；旧 Luna/Sol 文件进入 retired 生命周期。
- `AC-003`：已由生命周期清单、部署 Validate、通用 path/kind/scope 回归及 Rollback 验证覆盖；无关个人代理保留测试仍通过。
- `REQ-003` / `UDES-003`：已满足。稳定调用身份为 `evidence` 与 `experiment`，具体模型和档位只在代理 TOML 中维护，主代理保留正式交付责任。
- `AC-006`：`evidence` 使用 Luna/medium，只读证据包合同和逐项接纳协议由代理配置与编排 skill 共同覆盖。
- `AC-007`：`experiment` 使用 Sol/low，只消费已接纳证据，在隔离边界运行最小判别实验且不得修改生产真源、Git 或发布状态。
- `AC-008`：portable validator 只固定语义文件集合、schema、安全模型标识和受支持档位；未来模型/档位变体回归证明角色不再与模型后缀耦合。
- `AC-009`：全局内核保留委派选择与主代理责任，编排 skill 规定 capsule、反例熔断、无后代代理、逐项接纳和 evidence→experiment 交接；严格路由覆盖两类真实触发和概念讨论非触发。
- `REQ-002` / `UDES-002`：已满足。正式 attempt 必须先 Begin 后 Finish；执行失败与结果失败均可审计，merge 只消费已通过 attempt ID。
- `AC-004`：已由 started 阻断、第二次需理由和第三次拒绝的回归场景覆盖。
- `AC-005`：已由 6 收据活跃周期上限、周期轮换前 unfinished 检查、上一账本哈希链和 Git 恢复合同覆盖。

## 影响闭合

- Agent owner、编排 skill、全局路由、portable validator、部署 README、manifest/rollback 测试和 managed lifecycle 已同步为语义两角色合同。
- Windows SWE 的项目代理投影与 evaluator profile 已分离：前者消费当前 `global/agents`，后者继续由九题 corpus 固定 Sol/medium 与 Luna/max；评测不再要求两份集合相等。
- attempt owner、merge、正式 validator、baseline initializer、当前账本、组件 README、静态合同和回归测试已同步为 schema 2 两阶段合同；不存在仍调用旧 merge 重试参数的当前消费者。
- 旧 `docs/work/20260818_agent_instruction_surface/` 只保留其完成时的三角色历史证据，不作为当前真源改写。

## 约束与剩余边界

- `CON-001` 与原 `CON-003` 只描述历史实施轮和历史发布；当前 `CON-005` 的新一次 Publish 授权已取得，执行结果尚待写回。
- `CON-002` 满足：既有 `docs/plan.md` 与 `docs/handoff.md` 改动被保留并合入当前状态，没有回退无关工作。
- `CON-004` 满足：项目 `AGENTS.md` 已持久记录日常 Git 维护与私有远端同步授权，同时保留强制推送、历史重写和远端归属变更的单次授权边界；本轮源码已形成职责分离的提交并同步。
- 当前候选的代码、确定性测试、路由 evidence 与正式 Validate 已闭合；只剩按当前授权执行一次真实 Publish、Status 读回和发布收据写回。
