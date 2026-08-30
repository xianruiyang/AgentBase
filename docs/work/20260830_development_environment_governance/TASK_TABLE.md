# 开发环境与门禁治理

> 本文件由 taskctl 生成，只是任务合同与状态的可重建视图，不表示允许执行或产品完成。
> 视图刷新时间：2026-08-30T19:02:52Z；真源仍为 tasks/、state/ 与 results/。

## 状态统计

| 状态 | 数量 |
| --- | ---: |
| todo | 6 |
| blocked | 1 |
| done | 2 |

## 当前执行前沿

### T007 · blocked

- 标题：闭合 root 主动与 child 默认非递归委派
- 当前任务结果：portable Codex mode 与全局执行规则使非 ultra 的 /root 在隐式高收益任务中主动创建子代理，同时 child 默认不递归、只有用户、父代理或适用规则明确要求当前任务嵌套时才继续创建，并允许同时打开 6 个子代理线程
- 真源：tasks/T007.json@r7; state/T007.json@r23
- 修改范围：global/AGENTS.md, global/config.toml, global/README.md, skills/subagent-orchestration/**, development/skill-routing/trigger-cases.json, development/codex-deployment/**, docs/work/20260830_development_environment_governance/**
- 目标来源：SOL-007, SOL-008, SOL-009, GAP-007, GAP-011, GAP-012, GAP-013, GAP-015, GAP-017, GAP-018, DES-008, DES-009, DES-010, DES-011, DES-012, DES-013, AC-008, AC-009, AC-010, REQ-004, REQ-005, UDES-004, UDES-005, UDES-006, CON-004, CON-005
- 证据前沿：缺少结构化 delegation-decision 到 spawn tool-call 的正式绑定 owner
- 当前消费者：codex-cli 0.151.0 run10 medium、run11 xhigh 与官方 tag/main 源码合同
- 可能改变结论的维度：codex_cli=0.151.0, reasoning_effort=medium_or_xhigh, prompt_explicitness=implicit, agent_role=root_vs_child, mode_owner=features.multi_agent_v2.multi_agent_mode_hint_text, action_owner=global_AGENTS_and_subagent_orchestration, spawned_agent_capacity=6, v2_total_capacity=7, client_decision_owner=official_tag_and_main, o…
- 当前验证 case：codex_cli=0.151.0, reasoning_effort=medium_and_xhigh, mode=root_led_custom, action_owner=global_AGENTS_and_subagent_orchestration, spawned_agent_capacity=6, oracle=root_spawn_and_no_default_nested_spawn
- 已验证覆盖：run10_prompt_inputs=candidate_mode_AGENTS_skill_loaded, run10_parent_completion=pass, run10_root_actual_agent_event=absent, run10_declared_delegation_without_spawn=confirmed, run11_parent_completion=pass, run11_root_actual_agent_event=absent, run11_declared_delegation_without_spawn=confirmed, run10_run11_nested_agent_e…
- 仍未覆盖：future_structured_delegation_decision_owner, root_actual_agent_event, child_real_default_non_nesting_event
- 最近有效证据/反例：候选静态与部署合同通过：129-case routing contract、3-stage evidence refresh、manage Validate、portable-settings tests。行为仍失败：run11 xhigh 声明创建 6 个 evidence，但 0 spawn/child return、4 空 wait；官方 main 无结构化绑定 owner。
- 下一项有界动作：客户端或模型出现结构化委派决策、spawn obligation 或等价正式机制后重开；先复核 owner、tool loop 与 root/child 权限，再运行一个新的代表 case。


## 复核与结果

- 当前状态引用结果：2
- 含验证结果：2
- 含未决结果：1
- 含结果诊断：1
- 含来源快照问题结果：1
- 结果诊断条目：5

## 上游状态

- 用户确认快照：protected

## 任务

| ID | 状态 | Owner | 开始时间 | 结束时间 | 标题 | 依赖 | 结果 | 合同修订 |
| --- | --- | --- | --- | --- | --- | --- | --- | ---: |
| T001 | todo | — | 2026-08-30T15:55:16Z | — | 闭合无 sandbox 的评测只读入口 | — | — | 1 |
| T002 | todo | — | — | — | 迁移候选与 Verifier 到受信任本地运行 | T001:hard | — | 1 |
| T003 | todo | — | — | — | 删除 strict safety 资产与生产者自证门禁 | T002:hard | — | 1 |
| T004 | todo | — | — | — | 更新跨组件当前状态与生命周期消费者 | T003:hard | — | 1 |
| T005 | todo | — | — | — | 清理其余已证无消费者的开发环境残留 | T004:ordering | — | 1 |
| T006 | todo | — | — | — | 执行影响范围验证与跨契约完成审计 | T001:hard, T002:hard, T003:hard, T004:hard, T005:hard | — | 1 |
| T007 | blocked | /root | 2026-08-30T16:30:08Z | — | 闭合 root 主动与 child 默认非递归委派 | T008:hard | — | 7 |
| T008 | done | /root | 2026-08-30T16:38:30Z | 2026-08-30T16:42:38Z | 升级 Codex CLI 稳定基线到 npm latest | — | results/T008.r4.json | 1 |
| T009 | done | /root | 2026-08-30T18:50:08Z | 2026-08-30T19:02:52Z | 加强 AGENTS 与 skill 委派边界 | — | results/T009.r8.json | 1 |
