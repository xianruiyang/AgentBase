# 开发环境与门禁治理：方案设计

## DEC-001 选择受信任本地评测，退出 strict anti-cheat

- 状态: confirmed
- 来源: 当前用户要求与既有失败审计的方案分叉
- 关联: UDES-001, UDES-002, DES-002, DES-005

保留工程评价和工作区隔离，取消敌对安全目标。若未来重新要求防作弊，应作为独立目标、owner 和宿主能力重新设计，不恢复本轮退出的兼容路径。

## SOL-001 重构最终评测的正常本地入口

- 状态: planned
- 解决: GAP-002, GAP-004
- 关联: DES-002, DES-003, AC-002, AC-003, AC-004, AC-007

以当前 corpus/patch/receipt 为输入，先让 validate/list/report 在无 sandbox runtime 时闭环；再让 prepare/oracle/run/recover 使用普通本地候选和独立 Verifier 工作区。删除 sandbox setup/status/check/assessment、permission profile、canary、hardlink、专用清理及其状态 identity。

验证：组件正式入口不请求 UAC、不读取或创建 sandbox runtime；确定性测试覆盖 corpus、patch、工作区、结果与恢复；一个代表性 CLI 真实读回预期状态。

## SOL-002 重建评测测试与门禁层级

- 状态: planned
- 解决: GAP-003
- 关联: DES-004, AC-003, AC-005

删除只证明安全配置字面值、producer summary、ACL/deny、setup reuse 和 sandbox 清理的测试。保留并补足 corpus/schema、Windows adapter、patch allowlist、结果身份、锁、恢复、报告转换、模型禁用和资源边界测试。组件测试仅在评测合同受影响且候选稳定后运行，不进入无关组件日常修改。

## SOL-003 更新当前状态和正式消费者

- 状态: planned
- 解决: GAP-001, GAP-004
- 关联: DES-001, DES-005, AC-001, AC-006

更新根 requirements、总计划、项目规则、README、部署说明及最终评测既有交付链；旧安全条目明确 superseded，当前入口不再引用已删除命令。同步当前 srcq/MCP 发布状态，历史失败审计保持非当前证据。

## SOL-004 按消费者审计其他旧资产

- 状态: planned
- 解决: GAP-001, GAP-005
- 关联: DES-001, DES-006, AC-006

保留仍由 Source Query Gateway 消费的 code-search benchmark；删除空 `.github/workflows`、根测试缓存和已退出且无恢复价值的评测 sandbox state。只在依赖查询证明无当前消费者后删除其他候选资产，不按 `old/security/test` 名称批量处理。

## SOL-005 完成影响范围验证与治理审计

- 状态: planned
- 解决: GAP-001, GAP-002, GAP-003, GAP-004, GAP-005
- 关联: AC-001, AC-003, AC-004, AC-005, AC-006, AC-007

先验证简化后评测组件的代表入口，再按证据扩展其确定性组件测试、受影响文档合同、部署 Validate 和必要路由计划。最终审计逐项确认旧命令/状态/schema/脚本没有当前引用、保留门禁有真实契约、当前入口和状态一致、工作区无未知 dirty；不运行九题模型评测或 Codex Publish。

## SOL-006 把主动委派改成全局内核的直接动作

- 状态: superseded
- 解决: GAP-006
- 关联: DES-007, AC-008, AC-009, UDES-003

该候选曾修改 `global/AGENTS.md`、编排 skill 和触发合同；用户改选原生 mode policy 后撤回这些未提交改动，不形成第二职责入口。由 SOL-009 直接解决。

## SOL-007 用独立 CLI 任务验证真实创建事件

- 状态: blocked
- 解决: GAP-007
- 关联: DES-008, AC-008, CON-002, CON-004

在临时 Codex home 投影候选 portable config、自定义角色和 12 个相互独立的只读组件 fixture，使用已按 SOL-008 更新并读回的稳定 latest 原生 Codex CLI、现有认证、项目正式 `danger-full-access`/`approval_policy=never`、可用的 code-mode host 和非 `ultra` 推理档位，创建非 ephemeral 的真实 CLI 测试任务并运行无委派提示词的固定请求。`debug prompt-input` 已验收 root-led mode、候选 AGENTS/skill 与 7 个含 root 总槽位；run10 `medium` 和 run11 `xhigh` 的父任务均正常完成，但 JSONL 都是 0 次 spawn/create、0 次 child return 与 4 次空 wait，且模型均先明确声称将派发。该行为 oracle 失败，不再对相同提示面重跑；恢复条件是客户端或模型提供会改变 delegation-decision 到 tool-call 绑定的新正式机制。

## SOL-008 更新 Codex CLI 稳定基线并升级实际安装

- 状态: confirmed
- 解决: GAP-008
- 关联: DES-009, AC-010, UDES-004, CON-005

bootstrap、部署 README 和确定性测试中的精确 Codex CLI 版本已从 `0.148.0` 更新为 npm 当前稳定 `latest` `0.151.0`；只用 npm 升级了用户级 `@openai/codex@0.151.0`。bootstrap `Check -View Machine` 已读回原生路径、版本、PATH 顺序与隔离选项，确定性 bootstrap 测试通过。该结果作为 SOL-007 唯一行为探针的新输入；未执行 AgentBase Publish。

## SOL-009 把 proactive mode 与六子代理容量接入 portable settings

- 状态: blocked
- 解决: GAP-012, GAP-013
- 关联: DES-010, DES-011, DES-012, AC-008, AC-009, UDES-005, UDES-006, CON-004

在 `global/config.toml` 新增公开的 `agents.max_concurrent_threads_per_session = 6` 与 root-led `multi_agent_mode_hint_text`，不显式复制 V2 总槽位设置。run6、run7 证明 mode-only 不产生真实 root spawn；run9 进一步证明 role-aware `usage_hint_text` 同样无行为收益，因此该字段退出候选。按用户允许的回退边界，`global/AGENTS.md` 负责 `/root` 先实际创建再继续不重叠工作的动作，`subagent-orchestration` 负责固定角色选择、交接，以及 child 仅在用户、父代理或适用规则明确要求当前任务嵌套时继续委派的合同；正负触发 case 分别覆盖明确嵌套与默认不嵌套。部署源白名单、managed config key 生命周期与说明已同步，但 run10、run11 证明这些提示面仍不能把模型已声明的委派决策绑定为真实 spawn；官方 tag 与 main 也没有可复用的结构化调度 owner。候选可作为最低充分规则合同继续审查，AC-008 行为目标保持 blocked，未向实际 Codex 根目录 Publish。
