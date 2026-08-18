# 完成审计

## 目标达成

- `REQ-001` / `UDES-001`：已满足。候选和默认设置只保留 Luna/max 与 Sol/medium；Terra 源文件删除并进入部署 retired 生命周期。
- `AC-001`：已由 `global/config.toml`、`global/agents/luna.toml` 和 portable-agent 测试直接覆盖。
- `AC-002`：已由 `global/agents/sol.toml`、role-specific validator 和错误档位测试直接覆盖。
- `AC-003`：已由生命周期清单、部署 Validate、通用 path/kind/scope 回归及 Rollback 验证覆盖；无关个人代理保留测试仍通过。
- `REQ-002` / `UDES-002`：已满足。正式 attempt 必须先 Begin 后 Finish；执行失败与结果失败均可审计，merge 只消费已通过 attempt ID。
- `AC-004`：已由 started 阻断、第二次需理由和第三次拒绝的回归场景覆盖。
- `AC-005`：已由 6 收据活跃周期上限、周期轮换前 unfinished 检查、上一账本哈希链和 Git 恢复合同覆盖。

## 影响闭合

- Agent owner、portable validator、部署 README、manifest/rollback 测试和 managed lifecycle 已同步为两角色合同。
- attempt owner、merge、正式 validator、baseline initializer、当前账本、组件 README、静态合同和回归测试已同步为 schema 2 两阶段合同；不存在仍调用旧 merge 重试参数的当前消费者。
- 旧 `docs/work/20260818_agent_instruction_surface/` 只保留其完成时的三角色历史证据，不作为当前真源改写。

## 约束与剩余边界

- `CON-001` 在初始实施轮满足，随后被用户明确的后继发布请求替代；`CON-003` 已满足。本次 `DirectCompatibility + InstallPortableSettings` 发布和发布后 Status 均成功，Luna/Sol 与 Terra 退役已进入真实 Codex。
- `CON-002` 满足：既有 `docs/plan.md` 与 `docs/handoff.md` 改动被保留并合入当前状态，没有回退无关工作。
- 本次发布授权已经消耗；未来任何 Publish 仍需新的明确授权。
- 当前范围无开放实施项；未做真实 Luna 与 Sol 质量/成本比较，因为用户已直接裁决档位且本轮目标不要求该实验。
