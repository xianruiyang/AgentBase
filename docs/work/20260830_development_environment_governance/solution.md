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

- 状态: superseded
- 解决: GAP-012, GAP-013
- 关联: DES-010, DES-011, DES-012, AC-008, AC-009, UDES-005, UDES-006, CON-004

该组合方案已被 run10、run11 与用户后继裁决替代。`multi_agent_mode_hint_text` 及对应部署身份退出；六子代理容量作为独立资源上限转交 SOL-010，不再与主动委派策略绑定。

## SOL-010 只加强 AGENTS 与编排 skill并保留六子代理容量

- 状态: confirmed
- 关联: GAP-017, GAP-018, DES-011, DES-012, AC-008, AC-009, UDES-006, UDES-007, CON-004

加强 `global/AGENTS.md`：root 在每段实质工作前裁决委派，成立后先读必要 skill 并真实调用 `spawn_agent`；在真实 child 返回前不得读取或修改拟委派内容、继续其他实质工作、声称派发或调用 `wait_agent`。加强 `subagent-orchestration` 的实际创建、失败、等待、交接和 child 默认非递归合同，并更新对应正负触发 case。保留 `[agents].max_concurrent_threads_per_session = 6` 及其 portable-settings 生命周期与测试，只作为容量上限；删除 `multi_agent_mode_hint_text` 及其部署投影。只做静态、路由和 portable-settings 受影响验证，不再运行独立行为探针、九项评测或实际 Publish。
