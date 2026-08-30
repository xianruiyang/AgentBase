# 开发环境与门禁治理：目标设计

## DES-001 README 与组件说明索引当前开发职责

- 状态: confirmed
- 关联目标: REQ-001, AC-001, AC-006

根 README 只索引当前组件 owner 和正式本地入口；`docs/plan.md` 维护跨组件当前结论与重开条件；组件 README 维护本组件运行和验证合同。历史工作区与审计只提供证据，不定义当前状态。

## DES-002 Windows SWE 使用受信任候选与独立 Verifier 工作区

- 状态: confirmed
- 关联目标: REQ-003, AC-002, AC-003, AC-004, AC-007

`development/agent-evaluation` 继续唯一维护 corpus、候选、Verifier、patch、资格、尝试和报告。候选在普通本地 Windows 工作区消费当前 AgentBase 投影；Verifier 在候选结束后从固定 base 建立另一工作区，只消费校验后的 patch 并运行隐藏测试。两者的分离服务可复现性和 oracle 完整性，不声称构成敌对安全边界。

## DES-003 候选运行复用共享 Codex runtime owner

- 状态: confirmed
- 关联目标: REQ-003, AC-003, AC-004

候选通过 `development/common/codex_runtime.py` 取得受控服务连接环境，并在普通 `danger-full-access`、`approval_policy=never` 的本地工作区运行。项目候选 AGENTS/config/agents/skills 由真源单向投影；不建立持久 sandbox home、permission profile、凭据 hardlink或安全能力汇总。

## DES-004 门禁只属于能机械证明风险的入口 owner

- 状态: confirmed
- 关联目标: REQ-002, AC-003, AC-005

corpus validator、patch capture、结果/锁/资源限制、部署生命周期和任务/交付 CAS 分别拥有自己的局部门禁。模型行为、验证充分性、文档新鲜度、外部依赖缺失和当前覆盖只由模型基于结果判断，不提升为共享阻断。

## DES-005 旧安全职责执行单向退出

- 状态: confirmed
- 关联目标: REQ-001, REQ-003, AC-002, AC-006

删除 sandbox 专用脚本、CLI 命令、状态 schema、配置字段、测试和说明；从 root requirements、总计划、项目规则、部署导航和最终评测交付链移除当前语义。历史失败审计保留并明确其路径已退出，不维护可重新启用的兼容入口。

## DES-006 本地可重建状态不成为项目真源

- 状态: confirmed
- 关联目标: REQ-001, AC-006

空远程工作流目录、测试缓存、已退出评测 sandbox runtime 和无恢复价值的旧 workspace 可以清理；当前对话 hook 配置、运行中日志、安装目标和其他有活跃消费者的宿主状态不因仓库治理删除。

## DES-007 全局内核直接决定主动委派动作

- 状态: superseded
- 关联目标: REQ-004, AC-008, AC-009, UDES-003

该候选曾把 `global/AGENTS.md` 作为跨项目主动委派入口；OBS-014 证明 Codex 已有更高层且同责的 mode policy 配置。当前设计由 DES-010 取代，AGENTS 与 skill 只保留通用编排职责。

## DES-008 真实行为证据与静态路由证据分层

- 状态: confirmed
- 关联目标: REQ-004, AC-008, CON-004

静态配置、prompt-input 与三阶段路由 evidence 分别只证明配置加载、模型输入和 skill 边界；一次独立、非 ephemeral 的 Codex CLI 测试任务从临时 Codex home 读取候选 portable config，以项目正式的 `danger-full-access`、`approval_policy=never`、可用的 code-mode host 和非 `ultra` 档位读取固定的独立组件 fixture，并从 JSONL 观察真实代理创建事件。CLI 持有正常任务身份以支持 collab 寻址；原始输出和 fixture 只存在于有界临时目录，Codex 自有任务历史只承担该次测试运行，不成为项目真源。当前任务只记录身份、oracle 和结果；该测试不是 Hook、门禁、发布许可或长期第二状态源。

## DES-009 Windows bootstrap 唯一维护 Codex CLI 精确基线

- 状态: confirmed
- 关联目标: REQ-005, AC-010, CON-005

`development/codex-deployment/bootstrap_windows.ps1` 继续以精确稳定版本维护 Codex CLI package identity、支持判断和安装动作；部署 README 解释当前 pin，确定性测试消费同一身份。版本升级先由 npm `latest` 取得当前稳定值，再同步这些消费者并只升级用户 npm 包；不把动态 `@latest` 写入长期 bootstrap，也不引入第二安装入口。

## DES-010 portable config 唯一维护主动委派 mode policy

- 状态: confirmed
- 关联目标: REQ-004, AC-008, AC-009, UDES-005

`global/config.toml` 的 `[features.multi_agent_v2].multi_agent_mode_hint_text` 定义角色不对称的委派授权，由现有 portable-settings 合并器、managed key 生命周期和 Status 共同维护。它只对 `/root` 撤销要求显式请求的较早 mode，并明确 `/root/...` 子代理仍须用户、父代理或适用规则明确要求才可嵌套委派；`global/AGENTS.md`、`subagent-orchestration` skill 与 Hook 不复制或加强该策略，只承担全局执行内核和角色交接。该字段是 prompt policy owner，不是客户端调度器；是否真实调用 `spawn_agent` 必须由行为证据另行验收，不能由配置读回推定。

## DES-011 公开 agents 设置维护 spawned-agent 容量

- 状态: confirmed
- 关联目标: REQ-004, AC-009, UDES-005

`[agents].max_concurrent_threads_per_session = 6` 是项目的可移植并发容量真源，语义是不含 root 的同时打开 spawned-agent 线程数；在 0.151.0 V2 中读回为 7 个含 root 总槽位。使用公开 `[agents]` owner 而不复制 V2 总槽位值，可避免同名字段的 off-by-one 与双重配置；默认模型和 effort 继续由相邻现有字段维护。

## DES-012 AGENTS 与编排 skill 落实 root/child 动作边界

- 状态: confirmed
- 关联目标: REQ-004, AC-008, AC-009, UDES-006

DES-010 只负责高层授权；`global/AGENTS.md` 负责把 `/root` 的净收益判断落实为先实际调用 `spawn_agent`、再继续不重叠工作，并排除计划、skill 选择、文字声称和空等待。`subagent-orchestration` 在主代理主动、用户明确要求使用，或 child 收到用户、父代理或适用规则对当前任务的明确嵌套要求时选择 `evidence`、`experiment`、`operator`。没有该要求的 child 自己完成有界任务或把拆分需要返回父代理，不继续创建；明确嵌套只允许 `spawn_agent`，不授权用户任务或分叉线程。该职责分层不保留无行为收益的 `usage_hint_text`，真实 CLI 同时验收 root 正向与 child 默认非递归边界。

## DES-013 客户端闭合必须拥有结构化委派决策

- 状态: confirmed
- 关联目标: REQ-004, AC-008, AC-009, CON-004

客户端只有在正式状态明确记录当前 agent 身份、一次结构化委派决策、对应 spawn 事实与 child 嵌套权限时，才可把决策绑定到 tool loop。不得解析模型自由文本、用当前 live-agent 列表伪造历史状态、改变 V2 `wait_agent` 的 mailbox/steer/timeout 语义，或用 Hook/Stop 门禁补偿。没有该 owner 时，portable mode、AGENTS 与 skill 只定义最低充分的提示和角色合同，行为仍须按具体模型与客户端版本单独验收。
