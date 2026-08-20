# 模型设计

## DES-001 最终评测由单一 Windows owner 维护

- 状态: confirmed
- 关联目标: REQ-001, REQ-004, AC-002, AC-010

\`development/agent-evaluation/\` 唯一维护语料、公开 CLI、Windows adapter、资格与候选收据和报告。它消费 DeepSWE 固定 task assets、AgentBase 候选面和共享 Codex runtime，但不复制路由 evidence、部署结果或源码查询 benchmark 的职责。

## DES-002 仓库真源、隐藏状态和工作区分层

- 状态: confirmed
- 关联目标: AC-001, AC-003, AC-004

仓库只保存 schema/corpus/adapter/测试；默认 state root 保存固定源码、隐藏资产、尝试、日志与不可变收据；独立 work root 保存候选和 Verifier clone。state 与 work 互不包含且都不与项目或安装 Codex 根目录重叠，候选 profile 明确拒绝完整 state 与安装 Codex 根目录。Verifier 每次结束后删除；候选只在尚有恢复价值的非终态保留，终态默认删除，调试需显式保留。

## DES-003 候选运行投影真实 AgentBase

- 状态: confirmed
- 关联目标: AC-006, AC-007

候选临时 Codex home 单向复制当前全局 AGENTS 与 agents，并从 \`global/config.toml\` 生成配置；完整 skill 树不放入不可发现的 Codex home，而是逐 attempt 复制到候选仓库标准发现路径 \`.agents/skills/\`，用全树文件清单固定身份并从 Git status/patch 中排除。自定义 \`agentbase_candidate\` 不继承宽泛 profile：以 \`:root = deny\` 关闭宿主默认读取、\`:minimal = read\` 重新开放公共工具运行路径、\`:workspace_roots\` 只赋予候选根 write 且把 `.agents/skills`、`.git`、`.codex` 收窄为 read，并以 \`:tmpdir = write\` 为当前 attempt 临时面建立唯一例外；项目真源、完整 state root/installed Codex root 仍显式 deny，network false、approval never、web disabled 与 Windows elevated sandbox 保持。评测 HTTP provider 由独立 overlay 合入；服务 launcher 可消费冻结网络投影，但生成配置用正式 \`shell_environment_policy\` 对模型 shell 启用默认 secret-name 排除，并过滤 proxy、OpenAI/Codex、认证、凭据与 Git 控制变量。launcher 把 \`TEMP/TMP/TMPDIR\` 统一置于 denied state 内的 attempt tmpdir，把 \`APPDATA/LOCALAPPDATA\` 置于其子目录；tmpdir 与项目、workspace、安装根互斥，prompt/result 只允许位于 denied state。安装 Codex 根目录作为显式运行输入参与配置身份；sandbox child 只读取 workspace 内由真源单向派生并绑定哈希的 skill/工具清单，不为项目真源、state 同级内容或 denied Codex home 重开例外。候选 prompt 对 Python 题指向已准备的 workspace venv，对 Node 题指向 corpus 固定 package manager scripts；安装 Codex home 不是反向真源。

候选 prompt 的逐题修改范围直接从同一 task 的 `allowed_patch_paths` 派生，并与最终 patch 校验保持单向同源；通用提示只禁止该清单外的测试、依赖与 lockfile，不另建可能排除合法配置或 snapshot 解法的语义门禁。

## DES-004 共享 Codex 运行职责只有一个 owner

- 状态: confirmed
- 关联目标: AC-007

\`development/common/codex_runtime.py\` 继续唯一维护 dotenv 网络投影与子进程环境净化：先移除 ambient OpenAI/Codex 凭据、常见 token、Git/SSH/云与包管理器命名空间、语言注入和未冻结网络别名，再按调用方是否需要服务连接应用哈希冻结的 allowlist；候选/benchmark 的 Codex 服务进程消费投影，无模型 sandbox-check 消费空投影后的净化环境。\`development/common/codex_shell_environment_policy.json\` 唯一维护所有 evaluator 的模型 shell 过滤表，Python/PowerShell consumer 只校验、固定哈希并序列化，不把 launcher 环境伪装成模型 shell 合同。\`development/common/codex_cli_runtime.ps1\` 维护用户 npm/native Codex 解析、版本读取、JSONL 证据解析、单模型 catalog 投影与同一 policy 的 PowerShell CLI 参数。路由 evaluator、源码查询 benchmark 与 Windows SWE 调用这些共享 owner，各自只维护任务策略。

## DES-005 Verifier 适配保留评分语义

- 状态: confirmed
- 关联目标: AC-003, AC-004, AC-005

Verifier 从固定上游 clone 创建工作区，先安装原始第三方依赖，再应用 reference/candidate 与隐藏 test patch；patch 后必需的 build/codegen/可编辑元数据刷新在禁网 profile 中作为题目检查执行。固定上游 patch 的适配器只修复 hunk 内缺失前缀的空 context 行，并在不可变 Verifier 收据中同时绑定源/应用哈希。pytest 直接提供 JUnit；Jest JSON 转为 CTRF fullName；Vitest JUnit 转为 \`<classname>: <name>\` CTRF，Meriyah 额外按 XML attribute 规则折叠空白。派生 config 只改报告路径，固定 grader 继续拥有 P2P/F2P 和 reward。

## DES-006 qualification 与候选身份分层

- 状态: confirmed
- 关联目标: AC-004, AC-007, AC-008

Qualification base 绑定 corpus、行为相关 framework 文件、task assets/tree 和上游 tree；README、测试与说明文件不因无行为变化使昂贵资格失效。完整 qualification 再绑定实际依赖及其执行工具、Codex/Git/PowerShell 与语言运行时组成的 Verifier runtime。候选身份绑定当前候选面、framework、生效候选配置、匹配 qualification、依赖、网络 descriptor、全部实际工具/Codex 身份、model/profile。变化使旧证据自然退出当前选择，不覆盖历史收据。

## DES-007 单题状态机可恢复

- 状态: confirmed
- 关联目标: AC-002, AC-008

状态按 registered → candidate-setup → candidate-running → candidate-finished → patch-captured → verifier → terminal 推进。缺少 qualification 或 launcher 在模型前写入 denied state 的受信 preflight 失败记为 blocked-precondition，不计入基础设施重试；候选可写 workspace 回执不决定该状态。模型只在 candidate-running 调用一次。已有 candidate-finished/patch-captured 的同身份失败阻止再次 run，recover 重新核对冻结身份与 patch，优先复用不可变候选/Verifier 收据。合法零分、越界零分和成功都终止同一身份；没有可恢复候选产物的基础设施失败才进入一次有理由重试。锁只回收已证明死亡的 PID owner。

## DES-008 能力与最终评价按证据层级组合

- 状态: confirmed
- 关联目标: REQ-004, AC-006, AC-009, AC-010

共享 shell policy 的 SHA-256 同时进入 candidate config identity 与能力合同，策略漂移产生新身份而不是静默改变模型工具环境。

候选能力合同唯一由当前 candidate surface、corpus 与实际运行依赖派生，分别表达 projected assets、configured capabilities、runtime identity、sandbox preflight、separate evidence owners 和 excluded capabilities；资产存在、配置值与 preflight 都不得提升为模型行为通过。运行身份 owner 把基础 CLI 与该题实际依赖运行时投影为哈希固定的精确路径清单，skill owner 则把完整正文、references、scripts 与 assets 投影为另一份全树清单；sandbox child 只验证并消费这两份派生物，不再按工具名或单个 skill probe 维护第二套能力映射。launcher 校验 child stdout，workspace 收据只供诊断，模型前置条件的权威结果写入 denied state。无模型 \`sandbox-check\` 使用共享 owner 产生的不含服务网络投影和 ambient 凭据/控制变量的环境，并在与候选相同的 elevated profile 中真实验证宿主默认 deny 下的 state/project canary 与 staged/installed auth 不可读、skill 全树逐文件可读且不可写、workspace 写入、attempt temp/appdata 范围、清单/工具哈希、全部基础 CLI、当前任务 venv Python 或 package manager，并通过同一 \`srcq\` 完成 doctor、scc doctor、AST/cache、rg 分页、fd tree、scc machine 与 artifact 往返。模型 shell 环境净化、shell、\`apply_patch\`、公开测试和自定义 subagent 均作为 configured model actions 保留，需要真实候选模型行为证据；host/thread/MCP 依赖的 skill 行为由对应组件 owner 取证。elevated 宿主初始化不可用形成可恢复 \`blocked-precondition\`，未知错误仍失败。

\`assess\` 是跨 owner 的无模型证据组合入口：消费部署 \`Validate\`、sandbox assessment、当前路由计划/evidence 和 SWE report，不复制这些 owner 的判定，也不刷新路由、运行 qualification 或模型。真实 sandbox acceptance 可能请求管理员批准完成宿主 elevated 初始化，因此只能显式运行；它保留六维证据、失败/阻塞/待补集合、Token/时间和健康状态，\`composite_score\` 固定为空。
