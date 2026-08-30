# 开发环境与门禁治理：现状分析

## OBS-001 总计划中的发布状态已陈旧

- 状态: confirmed
- 来源: 当前 `docs/plan.md`、`docs/handoff.md`、Git 与正式 Status 的直接对照

总计划仍把 `srcq 0.5.0` 和 `vscode-lsp-mcp 0.2.0` 写成未发布候选；当前 HEAD 已包含对应实现，srcq Status 为 ready 0.5.0，MCP 安装 Status 为 0.2.0，AgentBase payload 为 published。总计划还保留“Windows SWE dirty 候选”表述，而当前工作区在本轮开始时干净。

## OBS-002 最终评测安全层没有形成真实消费者结果

- 状态: confirmed
- 来源: `agent_eval.py report --suite all`、`list` 与 `sandbox-status --view machine`

当前为 0/9 qualification、0/18 task/profile run、2 个 infrastructure failure；九题虽 prepared 但全部 pending。sandbox 状态因 controlled assets stale 要求再次显式 setup，恢复动作可能请求管理员批准。

## OBS-003 既有失败审计已推翻 strict deny-read 架构

- 状态: confirmed
- 来源: `docs/work/20260820_agentbase_final_evaluation_set/failure-audit-20260821.md`

六次 oracle 没有完成第一题 reference，也没有启动候选模型；native project/auth deny-read 不成立。确定性测试曾断言同一实现生成的配置与布尔量，不能证明真实 Windows 消费者。审计已要求把基础能力 smoke 与 strict anti-cheat 分离，并在第一题闭环前停止横向扩量。

## OBS-004 安全前置占据了大部分评测实现与合同

- 状态: confirmed
- 来源: `srcq scc --by-file development/agent-evaluation` 与源码关系查询

该组件当前约 17,971 行代码，其中 `agentbase_codex.py`、候选/清理 PowerShell、Verifier sandbox 集成和 4,278 行测试大量维护 runtime setup、permission profile、ACL/canary、工具哈希与清理状态。行数本身不证明缺陷；它与 OBS-002/003 共同证明这些长期资产没有交付其支配的真实候选结果。

## OBS-005 评测仍有应保留的当前资产

- 状态: confirmed
- 来源: corpus、adapter、patch/receipt owner 与第六次 no-op 证据

固定九题 corpus、Windows adapter、严格 patch 路径、候选/Verifier 双工作区、上游 grader、结果/尝试恢复和报告路径职责仍服务最终评测目标；第六次 no-op 已证明报告先写 Verifier 工作区再由父进程读取的机制有效。

## OBS-006 代码搜索 benchmark 仍有当前消费者

- 状态: confirmed
- 来源: `development/source-query-gateway/benchmark-protocol.md`、verification 与代码引用

`development/code-search-benchmark` 仍是 Source Query Gateway 当前 benchmark runner/monitor owner，并被现行语料与证据引用。它不是仅凭名称可删除的旧目录；历史 corpus 和结果只在其明确引用范围内保留。

## OBS-007 仓库根存在无消费者本地残留

- 状态: confirmed
- 来源: 根目录与 `.github/workflows` 只读枚举、`.gitignore`

`.github/workflows` 当前为空且项目明确禁止远程 CI；根 `.pytest_cache` 是可重建测试缓存。`.codex` 保存当前 QQ hook 工作区设置，`codexRuntimeLogFile` 由当前会话 hook 消费，二者不能与普通缓存一起删除。

## GAP-001 当前状态入口相互冲突

- 状态: confirmed
- 关联: OBS-001, DES-001, AC-001

总计划和部分组件说明会把接手者引向已经退出的候选/dirty 状态，必须更新当前结论和重开条件。

## GAP-002 strict safety 层成为无效正式前置

- 状态: confirmed
- 关联: OBS-002, OBS-003, OBS-004, DES-002, DES-003, DES-005, AC-002, AC-004

评测正常入口仍被没有真实支持的 elevated sandbox 与权限 acceptance 支配；本地受控资产变化还会重新要求 setup/UAC。该路径没有当前成功消费者，并持续制造失败、维护和验证成本。

## GAP-003 测试与门禁固化了已推翻机制

- 状态: confirmed
- 关联: OBS-003, OBS-004, DES-004, AC-005

大量测试证明配置、schema 和生产者自报布尔量，而项目规则和 README 又把它们列为组件门禁；这会让安全实现内部一致性阻断开发，却不能证明最终评测目标成立。

## GAP-004 退出旧路径需要穿透当前消费者

- 状态: confirmed
- 关联: OBS-005, DES-005, AC-003, AC-006

直接删除整个评测目录会同时丢失仍有消费者的 corpus、adapter、patch、grader 和恢复职责。必须先把正常路径迁移到受信任本地 runner，再删除旧安全脚本、合同和测试。

## GAP-005 可重建本地残留没有统一清理边界

- 状态: confirmed
- 关联: OBS-007, DES-006, AC-006

空 CI 目录、测试缓存和退出后的 sandbox state 可删除，但活动 hook 状态与日志仍有消费者；需要按生命周期区分，不能以递归清理替代裁决。

## OBS-008 现有主动委派规则没有进入动作层

- 状态: confirmed
- 来源: 当前 `global/AGENTS.md`、`subagent-orchestration` skill 与本次对话直接行为

全局规则原为条件性的 `should`，skill 也把委派描述为可推翻的默认选择；在本次具有多个独立只读取证子问题的开发环境治理任务中，主代理没有选择 skill 或创建子代理，直到用户明确追问。规则存在但动作没有发生，属于路由或规则执行层的适用失败。

## OBS-009 宿主保守默认保留适用 AGENTS/skill 例外

- 状态: confirmed
- 来源: 当前运行时开发者指令的直接读回

宿主默认不允许无来源的主动委派，但明确允许用户或适用 `AGENTS.md`/skill 提出子代理要求。项目不能删除该上位来源；可以由候选全局规则明确满足例外并决定正常动作。

## OBS-010 正式路由评测不能证明真实 spawn

- 状态: confirmed
- 来源: `development/skill-routing/README.md`、`routing_evaluator_runtime.ps1`、`invoke_routing_evaluation.ps1` 与共享 JSONL parser

现有三阶段 evaluator 使用临时 `CODEX_HOME`，禁用 `multi_agent`，提示模型不得调用工具，并把任何工具事件判为失败。它能证明 skill、行为标签与引用选择，但不能观察真实代理创建；零 Token 基础设施测试和静态合同也没有该行为 oracle。

## GAP-006 主动委派条件没有形成不可省略的正常动作

- 状态: superseded
- 关联: OBS-008, OBS-009, DES-007, AC-008, AC-009

原 `should` 与 skill 的弱默认允许模型在净收益成立时仍由主代理继续；AGENTS 对冲候选已被原生 mode policy 方案替代，不再通过加重规则解决。

## GAP-007 缺少真实代理事件的代表性证据

- 状态: confirmed
- 关联: OBS-010, DES-008, AC-008

现有 evidence 不能区分“模型正确复述委派策略”和“模型实际创建代理”。本次必须用一个无显式委派提示的独立 CLI 任务补足直接行为证据，未通过时不得把规则文件完成当作行为完成。

## OBS-011 Codex CLI 已从旧 pin 更新到 npm latest

- 状态: confirmed
- 来源: `npm view @openai/codex version dist-tags --json`、bootstrap 当前源码与 `codex --version` 的 2026-08-31 直接读回

npm 稳定 `latest` 为 `0.151.0`，预发布 `alpha` 为 `0.152.0-alpha.4`；本轮开始时项目 bootstrap、部署说明、确定性测试和用户级 Codex CLI 都为 `0.148.0`。当前精确 owner 与用户 npm 原生 CLI 已更新为 `0.151.0`，bootstrap Machine 读回 `ready=true`、原生路径不在 WindowsApps、用户 npm PATH 优先且隔离选项受支持，确定性 bootstrap 测试通过。旧版行为探针未创建临时目录或启动 CLI，没有可沿用结果。

## GAP-008 行为探针的 CLI 身份不是用户指定的 latest

- 状态: superseded
- 关联: OBS-011, DES-009, AC-010, UDES-004

原有 `0.148.0` 输入会偏离用户确认的测试环境。SOL-008 已把正式 pin、说明、测试和实际用户级 CLI 更新为 `0.151.0` 并完成能力读回；该差距不再阻断 T007。

## OBS-012 第一版规则未进入委派动作且只读 sandbox 阻断读取

- 状态: confirmed
- 来源: codex-cli 0.151.0 独立行为任务的 9 条 JSONL 与 stderr

有效 turn 使用 `gpt-5.6-sol` `medium` 正常完成，但先选择 `change-governance`，没有读取 `$subagent-orchestration` 或创建代理；JSONL 只含 `agent_message` 和一次无关的 `list_mcp_resources`。同时 `--sandbox read-only` 在进程启动前拒绝 PowerShell、cmd 与 srcq，模型无法读取 fixture。最终回答只是环境阻塞说明；没有任何 create/spawn 事件。

## GAP-009 主动委派裁决没有先于领域 skill

- 状态: superseded
- 关联: OBS-012, DES-007, AC-008

第一版规则只说净收益成立时创建角色，没有明确每轮在领域 skill 之前完成该裁决；实际模型先进入 `change-governance`，从而跳过了委派动作。该规则层修补路径已由原生 mode policy 取代。

## GAP-010 read-only sandbox 污染行为 oracle

- 状态: confirmed
- 关联: OBS-012, DES-008, AC-008, CON-004

Windows CLI 的 read-only 策略阻止任何本地只读命令，使测试同时测到了无效执行环境。后继代表任务应使用 AgentBase 正式的本地 `danger-full-access`、`approval_policy=never`，仍由只读 prompt、临时 fixture 和无修改验收约束任务行为。

## OBS-013 第二版规则已触发 spawn 路径但 ephemeral 父任务不可寻址

- 状态: confirmed
- 来源: codex-cli 0.151.0 changed-input 独立行为任务的 JSONL 与 stderr

第二版规则和候选 skill 让 `gpt-5.6-sol` `medium` 先选择 `$subagent-orchestration`，并尝试把三个独立证据组交给 evidence 角色；这证明规则已进入委派动作层。CLI 随后报告 `collab spawn failed: no thread with id`，所有 wait 事件的 `receiver_thread_ids` 为空，没有真实创建代理。该运行同时禁用了 `code_mode_host`，使模型不能读取 fixture。代理创建尚未验证，模型关于“已经交给三个代理”的文本不能替代事件证据。

## GAP-011 ephemeral 与禁用 code-mode 破坏真实行为消费者

- 状态: confirmed
- 关联: OBS-013, DES-008, AC-008, CON-004

`--ephemeral` 使当前父任务没有可供 collab 寻址的持久线程，禁用 `code_mode_host` 又切断本地读取入口；二者均不是产品规则输入，却直接阻止真实代理创建和任务完成。后继 case 必须创建正常 CLI 测试任务、保留 code-mode host，只隔离候选规则、skill、fixture 与非相关功能。该输入变化由直接错误决定，不是对同一失败的重试。

## OBS-014 0.151.0 提供直接 multi-agent mode 配置

- 状态: confirmed
- 来源: OpenAI `rust-v0.151.0` 源码、配置 schema 与本机 `codex debug prompt-input`

`features.multi_agent_v2.multi_agent_mode_hint_text` 是 `Option<String>` 配置。V2 每轮先取该值，再取模型目录 hint，二者均不存在时才按 reasoning effort 选择：`ultra` 为 proactive，其他档位为 explicit-request-only。配置值会生成独立 developer 级 `<multi_agent_mode>` 内容；本机 0.151.0 已用临时 override 直接读回自定义 marker。该入口替换 effort 派生模式，不是低优先级 AGENTS 对冲。

## OBS-015 V2 的默认三子代理是可配置容量的投影

- 状态: confirmed
- 来源: OpenAI `rust-v0.151.0` 配置源码与本机 prompt-input 读回

V2 默认 `max_concurrent_threads_per_session` 为 4 个总槽位，`effective_agent_max_threads` 减去 root 后表现为 3 个子代理。公开 `[agents].max_concurrent_threads_per_session` 表示不含 root 的 spawned-agent 线程数；0.151.0 在 V2 中把显式值加 1。设置 6 后 prompt-input 应显示 7 个含 root 总槽位。schema 只规定最小值 1，没有给出可作为工程目标的无成本最大值。

## GAP-012 AGENTS 对冲不是 mode policy 的正确 owner

- 状态: confirmed
- 关联: OBS-014, DES-010, AC-008, UDES-005

当运行时已经提供 developer 级 mode 配置时，`global/AGENTS.md`、skill 与触发合同不得复制相反的授权规则；早期对冲改动因此撤回。portable config 唯一维护 root/child 的上位授权；run9 证明授权本身不等于动作后，AGENTS 与 skill 可以在该授权内分别维护实际创建条件和角色交接，而不成为第二个 mode owner。

## GAP-013 默认 V2 容量低于已确认的并行工作需要

- 状态: confirmed
- 关联: OBS-015, DES-011, AC-009, UDES-005

默认 3 个子代理会限制多个独立取证或实现片段；项目已有 Luna 默认子代理与有界编排合同，可以显式采用官方公开默认的 6 个 spawned-agent 线程。容量只是上限，mode policy 和编排边界仍须避免无收益 fan-out。

## OBS-016 第一版 direct mode 仍未调用 spawn

- 状态: confirmed
- 来源: run5 的 0.151.0 prompt-input、JSONL、stderr 与父任务结果

run5 在 `medium` 下只读回一条候选 proactive mode 和 7 个含 root 槽位，父任务正常完成 12 个组件审查。模型文字明确声称将并行取证并选择编排 skill，但随后由主线程读取全部组件；JSONL 没有 spawn/create，三个 wait 的 receiver 与 state 均为空。该结果排除了 AGENTS 对冲缺失、mode 未加载、容量不足和任务未完成，直接证明第一版“use sub-agents”文本仍允许声称委派而不调用工具。

## GAP-014 direct mode 缺少成功创建前的动作顺序约束

- 状态: superseded
- 关联: OBS-016, OBS-017, DES-010, AC-008, UDES-005

run5 曾支持“第一版文本缺少动作顺序”的局部解释；run6 把先调用 `spawn_agent`、成功前不得自行完成、声称委派或空 wait 写入同一 developer mode 后，模型仍自行完成并五次空 wait。该差距不是继续加强措辞可以闭合，由 GAP-015 取代。

## OBS-017 强动作顺序文本仍未调用 spawn

- 状态: confirmed
- 来源: run6 的 0.151.0 prompt-input、JSONL、stderr 与父任务结果

run6 在 `gpt-5.6-sol`、`medium`、正常非 ephemeral CLI 线程中读回唯一强动作 mode 与 7 个含 root 槽位。父任务完成，但 JSONL 没有 spawn/create、非空 receiver 或 child state，五个 wait 均为空。该反例否定了“只需把主动委派写得更强”的方案。

## OBS-018 官方 proactive 文本在 medium 下仍未调用 spawn

- 状态: confirmed
- 来源: run7 的 0.151.0 prompt-input、JSONL、stderr、metadata 与父任务结果

run7 使用 OpenAI `rust-v0.151.0` 的 `PROACTIVE_MULTI_AGENT_MODE_TEXT` 精确文本；prompt-input 证明唯一 mode 逐字和换行匹配，并唯一显示 7 个含 root 槽位。父任务 exit 0 且 turn completed，但 JSONL 只有四个 receiver `[]`、state `{}` 的空 wait，没有 spawn/create 或 child 回传。skills 遍历上限只出现在 stderr，未阻止父任务完成，也没有 collab 工具错误，不能把无 spawn 归因于配置未加载、容量、CLI 失败或测试任务中断。

## GAP-015 multi_agent_mode_hint_text 不是代理调度器

- 状态: confirmed
- 关联: OBS-014, OBS-017, OBS-018, DES-010, AC-008, UDES-005

`multi_agent_mode_hint_text` 能直接替换 effort 派生的 explicit-request-only developer mode，因此是消除上位保守提示的正确入口；它仍只是每轮注入模型的 mode policy，不会在客户端侧自动创建代理或强制一次 tool call。0.151.0 的 exact official proactive 文本在 `medium` 下仍无真实代理事件，说明仅靠 portable config 不能证明或保证 AC-008，也不能据此把 Ultra 的实际主动委派表现永久复制到其他档位。

## OBS-019 0.151.0 提供独立的 spawn tool usage 输入

- 状态: confirmed
- 来源: OpenAI `rust-v0.151.0` feature schema、tool spec 与唯一注册路径

`features.multi_agent_v2.usage_hint_text` 是正式配置字段；`spec_plan.rs` 把它传给 V1/V2 的 `SpawnAgentToolOptions`，`multi_agents_spec.rs` 再把非空值加入 `spawn_agent` 工具描述。它与 developer `multi_agent_mode_hint_text` 是不同模型交互面：前者参与工具选择语义，后者定义本轮 multi-agent mode；两者都不直接执行 spawn。

## GAP-016 mode 授权尚未投影到角色不对称的工具动作

- 状态: superseded
- 关联: OBS-018, OBS-019, DES-010, DES-012, AC-008, AC-009, UDES-006

run7 只改变 developer mode，没有设置 `usage_hint_text`；用户随后把授权收窄为 root-led。run9 已按该角色边界把 `usage_hint_text` 投影到工具描述，但 root 仍无真实创建，因此工具描述不是缺失的动作 owner；由 GAP-017 取代。

## OBS-020 role-aware tool usage 仍未产生 root spawn

- 状态: confirmed
- 来源: run9 的 0.151.0 prompt-input、官方 tool-spec 路径、JSONL、stderr 与父任务结果

run9 沿用 run7 的 `gpt-5.6-sol`、`medium`、正常非 ephemeral 线程、12 组件 fixture 与隐式请求，唯一机制变化是 root-led mode 加 role-aware `usage_hint_text`。父任务完成且没有 child 嵌套创建，但 root 仍无 spawn/create 或 child return，四个 wait 的 receiver/state 为空。该反例证明重复或加强工具描述不能替代可执行的全局路由动作。

## GAP-017 root 主动委派缺少可执行的 AGENTS 动作

- 状态: superseded
- 关联: OBS-018, OBS-020, OBS-021, DES-010, DES-012, AC-008, AC-009, UDES-006

原生 mode 已解除 root 的显式请求限制并能约束 child，但 mode 与 tool metadata 都没有在代表任务中让 medium root 调用工具。用户明确允许原生入口不足时回到 AGENTS；run10 已按该边界加入全局动作与编排合同，却仍无真实 spawn，因此“缺一条 AGENTS 动作”不是完整原因，由 GAP-018 取代。

## OBS-021 AGENTS 回退在 medium 与 xhigh 下都未绑定真实 spawn

- 状态: confirmed
- 来源: run10、run11 的 prompt-input、JSONL、metadata 与父任务结果

run10 证明 root-led mode、7 个含 root 槽位、候选 `global/AGENTS.md` 与候选 `subagent-orchestration` 均进入 `gpt-5.6-sol` `medium` 输入；模型读取候选 skill 后两次明确决定派发 evidence，却由 root 批量读取全部组件并四次调用空 wait，spawn/create 与 child return 均为空。run11 只把 effort 改为仍非 Ultra 的 `xhigh`，模型再次声称将创建 6 个子代理，约 292 秒后正常完成父任务，真实事件仍是 0 次 spawn 与 4 次空 wait。两次均没有 collab 工具错误，排除了配置未加载、档位过低、容量不足、任务无委派收益和创建调用后基础设施失败。

## OBS-022 0.151.0 与官方 main 没有结构化委派决策 owner

- 状态: confirmed
- 来源: OpenAI `rust-v0.151.0`、官方 main `94cbbdd` 的配置、tool spec、AgentRegistry、V2 wait 与测试差异

V2 `wait_agent` 的正式职责是等待当前 turn 的 mailbox、steer 或 timeout，不接收 targets；既有测试明确允许没有 child 时超时。`list_agents` 只列 live agent，不保存历史 spawn。官方 main 仍没有 delegation decision、planner/tool-choice、spawn obligation、最大递归深度或 child non-recursive 配置；V2 spawn spec 反而明确 child 具有继续创建子代理的能力。用 live child 把空 wait 改成错误无法区分“从未创建”和“已完成退出”，并会反转既有 mailbox/steer 契约。

## GAP-018 模型委派决策与 spawn 工具调用之间没有可执行绑定

- 状态: confirmed
- 关联: OBS-021, OBS-022, DES-013, AC-008, AC-009, CON-004

0.151.0 可用的 mode developer 文本、spawn tool `usage_hint_text`、全局 AGENTS 与编排 skill 都已分别进入代表任务，模型仍能先声明具体派发再跳过 `spawn_agent`。继续追加同义提示、解析自由文本、把合法 wait 改成错误或加 Hook 都不能形成可靠 owner。若未来在客户端层闭合，必须先新增结构化委派决策及 root/child 权限状态，由正式 tool loop 消费并提供可测试的 spawn 事实；在该 owner 存在前，当前只能保留最低充分的 root/child 规则合同，不能声称真实行为已验证。
