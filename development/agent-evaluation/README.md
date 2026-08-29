# AgentBase Windows SWE 最终评测集

本目录是 AgentBase 仓库级最终评测的唯一 owner。它复用固定 DeepSWE v1.1 题目、隐藏测试、参考补丁与 `grader.py grade` 计分语义，但将执行层改为 Windows 原生候选/Verifier 双工作区。因此结果名为 **AgentBase Windows SWE**，不得作为官方 DeepSWE leaderboard 成绩。

## 职责与信任边界

- `corpus/final-v1.json`：九题、难度证据、suite、模型档位、上游提交、固定 DeepSWE 资产、项目自有 Windows adapter 引用、允许的源码范围、依赖安装和测试命令的机器真源。
- `api_pricing_snapshot.json`：评测所用 OpenAI 官方标准 API 文本 Token 单价、缓存写入与长上下文倍率的有日期价格快照；`agent_eval.py` 是唯一消费者，价格更新会改变 framework identity，不反向改写旧收据。
- `agent_eval.py`：唯一公开 CLI，负责选择、源码准备、资格验证、候选尝试、恢复、不可变收据和报告。
- `evaluation_core.py`：语料校验、源码/任务身份、工作区、patch 边界、锁、尝试和收据。
- `agentbase_codex.py`、`invoke_candidate.ps1`：维护 state root 内唯一持久评测 Codex home，把项目全局 AGENTS/config/agents 作为可重建受控面同步进去，并把完整 skill 树按 attempt 派生到候选仓库的标准发现路径；只有显式 setup 可以初始化 Windows elevated sandbox，其他入口只复用已验收后端。候选仍通过共享原生 Codex 解析器和显式指定安装根中的既有认证运行。
- `windows_verifier.py`：在候选结束后才创建干净 Verifier 工作区，安装原始提交依赖、建立与候选一致的 Windows fixture adapter 基线、应用候选 patch 与隐藏 `test.patch`、转换 Windows 原生报告并调用固定上游 grader。
- `development/common/codex_runtime.py` 与 `development/common/codex_shell_environment_policy.json`：多个本地 evaluator 共用的 `.env` 网络投影、launcher 环境净化与模型 shell 过滤 owner；本组件不复制凭据、代理值、过滤表或 ambient 控制变量处理。

候选只能看到任务说明、固定基础源码、该仓库自身指令、公开测试和 AgentBase 显式投影的能力面。自定义权限 profile 继承官方 `:workspace` 基线保护，再以更窄规则覆盖：`:root = deny` 拒绝宿主默认读取，项目根与原始安装根分别用一个精确目录 deny 触发 native Windows 可继承 ACL，不枚举随时间增长的顶层内容；`:minimal = read` 保留公共运行时，模型前冻结的每个基础 CLI 可执行文件另按精确绝对路径只读开放；`:workspace_roots` 只赋予候选仓库写权限并把 `.agentbase`、`.agents/skills`、`.git` 与 `.codex` 收窄为只读，`:tmpdir = write` 只重开一次 attempt 的运行临时面。隐藏测试、参考补丁、qualification、持久 sandbox 后端与结果状态位于显式拒绝且不做 glob 枚举的 state root，项目真源和原始安装 Codex 根目录也不可读。认证只经持久 home 中逐次创建、结束即删除的受拒绝 hardlink 供 Codex 客户端使用；模型目录投影同样逐次清理。`TEMP/TMP/TMPDIR` 指向该 attempt tmpdir，`APPDATA/LOCALAPPDATA` 与 `HOME/USERPROFILE` 分别指向它的独立子目录；launcher 在 sandbox 前为宿主 owner 固定一条可继承清理 ACE。这样 npm、pnpm、Git、esbuild 等子进程不需要为解析 home 越过 workspace ACL 去读取宿主用户目录。Python 3.13+ 会把 pytest 以 `0700` 新建的目录转换为只允许隔离身份访问的 DACL，因此两侧还会预建可继承的 `pytest-of-<user>` 根并固定 `tmp_path_retention_policy=none`，让 pytest 在 sandbox 进程退出前删除自己的私有子目录；普通缓存继续由宿主收尾。Codex 服务进程只保留冻结连接所需的网络投影，生成配置中的 `shell_environment_policy` 另外启用默认 secret-name 排除，并从模型 shell 过滤 proxy、OpenAI/Codex、认证/凭据和 Git 控制变量；无模型 `sandbox-check` 的 launcher 也由共享净化 owner 生成环境。Verifier 不运行模型，也不继承候选的依赖目录、测试配置或运行残留；它只与候选共享主机级 sandbox 后端和受控配置，不共享题目工作区。二者唯一的题目数据通道仍是经范围校验的 Git binary patch。

pnpm 题目的唯一任务运行入口是每个工作区可重建的 `.agentbase/task-runtime/bin/pnpm.cmd`：准备层用 npm 按仓库 `packageManager` 的精确版本安装官方 JS runtime，并在哈希计入身份前，对固定 bundle 中 canonicalize temp/cwd 的两个已确认调用做局部 Windows sandbox 兼容替换；wrapper 仍通过冻结的 Node 入口调用它。依赖 setup、候选 shell、Verifier、`--version` 与 workspace inventory 工具探针以及依赖身份读回共同消费该入口；wrapper 与实际 `pnpm.cjs` 都进入身份且不属于源码或候选 patch。这样不依赖或开放宿主用户目录中的全局 pnpm，也不扩大候选 sandbox 权限。

Node 依赖身份由固定 manifest/lockfile、实际 npm/pnpm runtime 和规范化后的顶层依赖 inventory 组成；不哈希 pnpm 生成且含逐次运行元数据的 `node_modules/.modules.yaml`。

Clack 使用 workspace-local pnpm 的 hoisted node linker，并让 Vitest checks 使用官方 runner config loader；默认 symlink 布局和 bundle loader 会让 Node/esbuild 为包内模块与配置扫描工作区祖先目录，在 host-default-deny 下把预期的目录边界转化为启动或 ESM/CJS 判定失败。checks 同时以锁定依赖认可的 `TERM_PROGRAM=vscode` 进入 Unicode 分支，使 Windows 与固定快照使用同一符号集，并关闭跨文件并行以隔离共享 readline/fake-timer 状态，避免 JUnit 进程在报告中途退出。这些适配不改变测试选择、报告节点或 grader。

## 候选能力与证据层级

评测使用 Codex 离线身份的正式 local-binding 模式：候选和 Verifier 可以访问自己的 loopback 测试服务器，非 loopback 出站仍由 Windows firewall rule 阻断。运行时从共享 shell 策略派生唯一的受管例外 `CODEX_NETWORK_ALLOW_LOCAL_BINDING=1`；它在一般 `CODEX_*` 过滤后固定写入每条 sandbox 命令，使 Codex 的持久防火墙协调不会撤销回环，同时不包含凭据、不能开放非 loopback 网络，也不改变共享策略真源。需要本地服务的 Windows fixture adapter 使用 OS 分配的临时 loopback 端口，并把服务线程或底层任务在启动前退出直接传播为失败，避免宿主端口占用被无界等待遮蔽。

`report` 与 `assess` 返回同一份 `candidate_capabilities` 合同，并刻意区分资产存在、配置声明、运行前身份和真实 sandbox 探测；前一层不能替代后一层：

```text
independent Codex candidate
├─ projected assets
│  ├─ global/AGENTS.md + portable config/transport overlay
│  ├─ evidence=Luna/medium + experiment=Sol/low + operator=Luna/max project custom agents
│  ├─ Sol/medium + Luna/max evaluator profiles (independent runtime selection)
│  ├─ target repository AGENTS/instructions from the fixed base tree
│  └─ complete `.agents/skills` trees (SKILL/references/scripts/assets), hash-pinned and read-only
├─ configured capabilities
│  ├─ host default deny + minimal runtime read + workspace read/write
│  ├─ shell/apply_patch/public tests (behavior requires a candidate model run)
│  ├─ shared hash-pinned model-shell secret/network/control policy; service transport stays separate
│  ├─ elevated Windows profile + explicit project/state/installed Codex deny + external network blocked + loopback enabled
│  ├─ process temp/appdata/home scoped to one attempt tmpdir
│  └─ multi-agent enabled; behavior remains explicit model evidence
├─ identity before model
│  ├─ Codex, srcq, rg, fd, scc, hyperfine, ast-grep, Git, pwsh, Python, Node
│  └─ task dependency runtime and npm/pnpm identity
├─ sandbox preflight before model
│  ├─ state/project canaries + staged/installed auth unreadable
│  ├─ every skill file hash-readable + skill tree write-denied + workspace write probe
│  ├─ exact TEMP/TMP/TMPDIR/APPDATA/LOCALAPPDATA/HOME/USERPROFILE attempt scope
│  ├─ launcher persists trusted pre-model failure under denied state
│  ├─ hash-pinned exact-path manifest for every base CLI
│  ├─ task venv Python or npm/pnpm exact runtime added per candidate
│  └─ srcq/scc doctors + AST/cache + rg pagination + fd tree + scc machine + artifact round trips
├─ separate evidence owners
│  ├─ routing behavior
│  ├─ custom-subagent runtime behavior
│  ├─ skill scripts that require host/thread services
│  ├─ vscode-lsp-mcp
│  ├─ hooks/event logging/QQ
│  └─ plugin packaging/deployment
└─ excluded from SWE
   └─ external command network, web search, hooks, host apps/plugins/MCP, install, publish
```

正式隔离合同要求 `elevated` 原生 Windows sandbox。[OpenAI Windows sandbox](https://learn.chatgpt.com/docs/windows/windows-sandbox) 与 [Permissions](https://learn.chatgpt.com/docs/permissions) 的平台边界说明 `unelevated` 不能执行全部读写拆分策略，因此它不能作为 state/installed-root deny 的等价降级；更窄的 `.agents/skills` read 与 `:tmpdir` write 按正式权限优先级覆盖 workspace/state 的宽规则。[Codex config reference](https://developers.openai.com/codex/config-reference/) 定义的 `shell_environment_policy` 是模型 shell 的独立环境边界，不能用 launcher 的服务连接环境替代。[Build skills](https://learn.chatgpt.com/docs/build-skills) 规定仓库 skill 从 `.agents/skills` 发现，并在选择时读取完整 `SKILL.md`、按需读取 references/scripts/assets，所以单个探针或 Codex home 中不可发现的副本都不能代表候选 skill 能力。管理员批准只属于显式 `sandbox-setup`：它成功后把 Codex 可执行文件身份、非秘密后端结构和 setup marker 固定到本地运行时状态；`.sandbox-secrets` 只验证为非 reparse 的真实目录，允许为空，也不枚举、记录内容或文件名。批准取消时返回 `blocked-precondition` 并禁用自动重试。`sandbox-check` 及题目入口先验证该状态，缺失、失效或 Codex 版本变化时在启动 Codex 前返回 `blocked-precondition`；已启动 sandbox 但 acceptance 未通过才返回 `failed` 和精确失败检查。若一个已验收状态仍被 Codex 拒绝，框架立即将其失效，后续调用不再重复触发 setup。

这里的可固定“后端结构”只包括 Codex 身份、setup marker 与 command runner 等稳定核心。Codex 自有 `cap_sid` 会随新 workspace/tmpdir 扩展，是可变 SID 注册表：框架只校验普通文件、大小上限、JSON 字段和 SID 结构，不把其易变字节、条目数或路径历史写入稳定身份；旧版静态哈希状态可由显式 `sandbox-setup` 在稳定核心一致时就地刷新，不启动 sandbox 或请求 UAC。只有 Codex 明确拒绝 elevated 后端才触发失效，child 路径、测试或普通命令启动失败不得冒充后端损坏。

## 固定语料

难度是 DeepSWE v1 页面公开的“成功 rollout / 116”经验分层，不是官方难度标签：

```text
agentbase-windows-swe-v1
├─ easy
│  ├─ returns-validated-error-accumulation       76/116
│  └─ sql-formatter-bigquery-pipe-formatting     70/116
├─ medium
│  ├─ httpx-multipart-response-parsing           48/116
│  ├─ awilix-async-container-initialization      44/116
│  └─ bandit-interprocedural-taint-checks        42/116
├─ hard
│  ├─ fastapi-implicit-head-options              29/116
│  └─ meriyah-explicit-resource-declarations     25/116
└─ very-hard
   ├─ clack-async-autocomplete-options           18/116
   └─ superjson-error-stack-serialization        17/116
```

Suite：

- `smoke`：Returns + SQL Formatter。
- `core`：smoke + HTTPX + Awilix + Bandit + FastAPI。
- `rotation`：Meriyah + Clack + SuperJSON。
- `all`：core + rotation。

全部任务使用 Python 或 TypeScript，避开 Unix owner、signal、pseudo-TTY、可执行位和 `/proc` 等不适合 Windows 首批移植的语义。Bandit 覆盖 AST/跨过程数据流；Awilix 与 Clack 分别覆盖依赖图事务和 UI 异步竞态，能力不按语言表面重复。

## 状态与生命周期

默认程序状态与工作区故意分开：

```text
%LOCALAPPDATA%\AgentBase\
├─ agent-evaluation-state\
│  ├─ sources\
│  │  ├─ deep-swe-<commit>\
│  │  └─ upstreams\<task>-<base>\
│  ├─ sandbox-runtime\
│  │  ├─ codex-home\
│  │  │  ├─ AGENTS.md + config.toml + agents\    (项目真源的受控派生面)
│  │  │  └─ .sandbox + .sandbox-bin + .sandbox-secrets + cap_sid    (主机后端状态)
│  │  └─ runtime.json    (不含 secret 内容或文件名的就绪身份)
│  ├─ qualification-runs\
│  ├─ qualifications\<task>\<identity>.json
│  ├─ attempts\<attempt-id>\
│  │  ├─ attempt.json
│  │  ├─ candidate.patch
│  │  ├─ runtime-temp\    (仅运行期；含 appdata/home/localappdata，结束后删除)
│  │  ├─ codex-logs\
│  │  └─ verifier\
│  ├─ results\<task>\<profile>\<identity>.json
│  └─ locks\
└─ agent-evaluation-workspaces\
   └─ <attempt-or-oracle>\
      ├─ candidate\    (终态后删除；有可恢复输出的中断会保留)
      └─ verifier-*\  (正常结束后删除；调试可显式保留)
```

state root 保存隐藏资产、持久 sandbox 后端与机器收据；候选权限 profile 默认拒绝宿主文件读取，只重开 `:minimal`、候选 workspace 和每次 attempt 的 `:tmpdir`，并在 workspace 内把完整 skill 投影收窄为 read-only，同时显式拒绝项目真源、完整 state root 与已安装 Codex 根目录。state/work 必须互不包含，也不得与项目仓库或安装根重叠；tmpdir 虽位于 state 内，但只由更窄的临时路径规则开放，不能扩张到同级 canary、收据或持久 Codex home。全局 sandbox runtime 锁把 setup、候选 preflight/model 和 Verifier 串行化，避免认证 hardlink、模型目录投影或后端状态并发覆盖。仓库只维护语料、适配器和确定性测试，不提交 checkout、依赖、日志、报告或收据，这些开发资产也不进入 Codex 发布 payload。

## 使用

以下命令均从仓库根执行。`validate`、`list`、`next`、`check`、`report` 和 `sandbox-status` 不安装软件、不运行模型、不启动 sandbox，也不触发 elevated 初始化：

```powershell
python.exe -X utf8 development\agent-evaluation\agent_eval.py validate
python.exe -X utf8 development\agent-evaluation\agent_eval.py list --suite all
python.exe -X utf8 development\agent-evaluation\agent_eval.py next --suite core
python.exe -X utf8 development\agent-evaluation\agent_eval.py check --task returns-validated-error-accumulation
python.exe -X utf8 development\agent-evaluation\agent_eval.py report --suite all
python.exe -X utf8 development\agent-evaluation\agent_eval.py sandbox-status --view machine
```

主机第一次使用或 Codex 可执行文件/稳定后端核心变化后，显式执行唯一 setup 入口；它可能请求一次管理员批准，状态已经就绪或仅需把旧版 `cap_sid` 静态哈希状态迁移到可变注册表合同时会直接复用，不会重复启动 sandbox setup：

```powershell
python.exe -X utf8 development\agent-evaluation\agent_eval.py sandbox-setup --view machine
```

真实权限验收与跨 owner 总评只复用已就绪运行时：

```powershell
python.exe -X utf8 development\agent-evaluation\agent_eval.py sandbox-check --view machine
python.exe -X utf8 development\agent-evaluation\agent_eval.py assess --suite all --view machine
```

二者都不启动模型、不刷新路由 evidence、不执行 qualification、不安装题目依赖、也不 Publish，更不会隐式 setup 或请求管理员批准。运行时未准备好时它们在启动 Codex 前阻断；`sandbox-check` 通过返回 0、真实 acceptance 失败返回 2、setup 前置条件未满足返回 3。`assess` 仍生成完整证据向量，把失败、阻塞和待补证据分别列出。

外部动作始终显式且一次只处理一题：

```powershell
python.exe -X utf8 development\agent-evaluation\agent_eval.py prepare --task returns-validated-error-accumulation
python.exe -X utf8 development\agent-evaluation\agent_eval.py oracle --task returns-validated-error-accumulation
python.exe -X utf8 development\agent-evaluation\agent_eval.py run --task returns-validated-error-accumulation --profile sol
python.exe -X utf8 development\agent-evaluation\agent_eval.py recover --attempt-id <attempt-id>
```

`prepare` 只克隆固定 DeepSWE task tree 与精确上游 base commit。`oracle` 不运行模型，但会在临时工作区安装题目依赖，并至少重复两次验证：未修改源码必须为 `0`，官方参考补丁必须为 `1`，各次依赖与 Verifier 运行工具身份必须一致。`run` 只接受当前 corpus/framework/task/dependency/verifier-runtime identity 的 qualification；Sol 固定 `medium`，Luna 固定 `max`。长运行只在既有 attempt state 的阶段真实变化时向 stderr 输出一行 `STAGE <attempt-id> <stage>`；最终 human/machine 结果仍独占 stdout，不新增进度状态源。

`sandbox-status`、`sandbox-setup`、`sandbox-check`、`assess`、`oracle`、`run` 与 `recover` 的 `--installed-codex-root` 默认取 `CODEX_HOME`，未设置时取 `%USERPROFILE%\.codex`；使用非默认安装根时必须在相关入口传入同一值。网络默认从默认 Codex 根的 `.env` 只投影 allowlist，descriptor 仅保存来源、键名、转换选项和整体 SHA-256，不保存代理值。该投影只供 Codex 服务连接；模型 shell 由生成配置过滤这些网络键以及 secret/control 类 ambient 变量，无模型 sandbox launcher 则从同一净化函数生成不含投影的进程环境。候选通过所选安装根中既有 `auth.json` 的临时 hardlink 使用认证，运行期间持有只读共享锁并在结束后删除链接；候选 profile 同时拒绝完整 state root 与原始安装根，认证内容和凭据不进入收据。固定 HTTP transport overlay 避免 WebSocket 反复重连，模型缓存只投影当前所选模型并在运行结束后删除。

## 隔离、patch 与恢复

候选启动前，框架通过 Codex app-server 的 `command/exec` 使用同一 `agentbase_candidate` elevated 权限 profile 运行无模型 preflight；该入口与真实 `codex exec` 共用权限解析和 Windows sandbox manager，不使用会丢弃 deny-read override 的调试 `codex sandbox` 子命令。此本地 runner 对当前进程显式禁用 app-server remote control，避免读取桌面持久开关后建立与评测无关的 websocket；该 host 标记仍由模型 shell 的 `CODEX_*` 过滤隔离：

无模型 app-server preflight 与真实候选 CLI 都通过各自的 inline-table CLI override 把当前动态 workspace 标记为 trusted；Codex 的 override path 解析器只按 `.` 分段，不能用带引号的动态 path 作为 dotted key。该覆盖只影响本次加载，不把 `[projects.<path>]` 写回持久评测 `config.toml`。preflight 返回后还必须复核完整受控身份，任何写回都会阻断本次并由正式同步恢复，但不得伪装成 elevated 后端损坏而触发 UAC。因此受控配置身份只表示项目规则、可移植配置、transport 与权限合同，不与 Codex 自有的动态 workspace 历史混合。

1. state root canary、项目根 `README.md` 与 staged/installed `auth.json` 必须不可读；
2. 框架从仓库 `skills/` 单向派生候选根 `.agents/skills/`，清单覆盖全部 `SKILL.md`、references、scripts 与 assets；child 必须逐文件核对集合、字节数和 SHA-256，并证明整个投影可读但不可写，候选仓库其他位置的独立写探针必须通过；
3. `TEMP`、`TMP` 与 `TMPDIR` 必须精确指向 denied state 内只为本 attempt 重开的 `runtime-temp`，`APPDATA`、`LOCALAPPDATA` 与 `HOME/USERPROFILE` 必须分别指向其独立子目录；该目录与候选 workspace、项目和安装根互斥。preflight/候选进程退出后，框架只用哈希固定脚本在同一 permission profile 下逐项删除其子项，不跟随 reparse point；脚本必须证明 owner 下的相对路径精确为 `runtime-temp`，可信父进程只删除已经为空的根目录；
4. child 从 stdout 返回结果，由 launcher 校验并持久化；决定 `blocked-precondition` 的副本由 launcher 在模型启动前写入 denied state，候选可写的 workspace 副本不拥有尝试分类权；
5. 框架把模型前已经冻结的基础工具绝对路径、可执行文件 SHA-256 和版本参数写入 workspace 内的哈希固定清单；preflight 自身也只用该清单中已复核哈希的 PowerShell 绝对路径启动，sandbox child 再验证清单并按精确路径执行 `srcq`、`rg`、`fd`、`scc`、`hyperfine`、`ast-grep`、Git、PowerShell、Python、Node；Verifier 的每条 sandbox 命令同样必须把 `argv[0]` 展开为已存在的绝对文件，任何裸命令都在启动 Codex 前阻断；
6. 每次候选再把该题实际依赖运行时加入同一清单：Python 题使用 workspace venv Python，Node 题使用实际 npm 或 pnpm；
7. `srcq doctor` 与 `srcq query scc doctor` 使用清单中已验证哈希的同一 `srcq` 路径；随后以隔离语料实际完成 AST 查询及 cache info/remove、三页 `@next` 续读、fd machine tree、scc machine languages 和原生 artifact/machine envelope 往返。doctor 只证明环境可用，不能替代这些候选必需工作流。

完整 skill 投影和两份清单是每次 attempt 从项目真源重建的派生物，唯一消费者是候选启动前的权限验收与随后同一候选 Codex；它们由 Git exclude 隐藏且始终排除于候选 patch、项目提交和发布 payload。候选 prompt 对 Python 题明确使用已准备且身份固定的 `.agentbase-venv\Scripts\python.exe`，对 Node 题明确使用 corpus 固定的 npm/pnpm scripts，避免公开检查意外使用另一套依赖。它还从同一题 `base` bucket 派生可直接执行的公开回归命令，移除报告专用参数和任何隐藏测试过滤名，并给出当前 workspace 的 Git safe-directory 前缀；模型不必靠失败探测依赖、测试路径或 sandbox Git ownership。Prompt 明确禁止候选创建 Git 提交；父进程直接从最终工作树提取 patch，避免候选将无需提交的权限拒绝当成产品问题。候选可以用 shell、`apply_patch` 和公开测试修改题目 workspace，但这些以及自定义 subagent 的真实行为只有显式候选模型运行才能证明；无模型 preflight 只证明配置、身份、权限与确定性 CLI 工作流。需要 host/thread 服务、MCP、hooks 或插件安装的 skill 能力继续由相应组件 owner 单独验证。

候选 prompt 同时直接投影该题的 `allowed_patch_paths`。因此 Bandit 的 `setup.cfg` 或 Meriyah 的特定 snapshot 等合法解法不会被通用禁令误伤；清单外的测试、依赖与 lockfile 仍禁止，最终 patch 继续由同一 corpus 范围机械门禁。

题目可选的 `windows_adapter` 只引用 `windows-adapters/` 下项目自有、哈希固定的 fixture patch，并声明精确 `patch_paths`；静态校验先用 Git 完整解析 patch，再要求解析所得路径与声明集合一致，因此损坏 hunk 或漏报路径不会推迟到真实 oracle 才暴露。候选与 Verifier 都先在安装原始提交依赖后应用它并形成确定性干净 Git 基线；候选 prompt 将其标为只读环境支持，最终解法相对该基线提取，因此 adapter 不进入候选 patch，也不修改 state root 中固定的 DeepSWE checkout。Verifier 收据按 `windows-adapter → reference/candidate → hidden-tests` 记录实际应用顺序与哈希。

候选 patch 最多 100 个文件、8 MiB，拒绝 symlink/submodule，并按题目只允许真实解法范围，例如 Bandit 仅允许 `bandit/**` 与官方解法确实使用的 `setup.cfg`。测试、runner、lockfile、`.agentbase` 和未列入该题解法范围的依赖 manifest 不会进入 patch。Verifier 在应用 patch 前从原始提交安装第三方依赖；题目确需在 patch 后刷新 build/codegen/可编辑包元数据时，只在 network-disabled Verifier profile 中执行并记入检查记录。

固定上游 patch 先按原始 SHA-256 验证，再经过唯一的保守归一化器：只在 unified hunk 声明范围内给缺失前缀的空 context 行补一个空格，其他字节不改。Verifier 收据同时记录源 patch、实际应用字节的 SHA-256 和补齐计数；这解决 SQL Formatter 上游参考补丁的 20 个 permissive 空行，同时不改变其解法内容。

尝试在模型进程前登记。有效 reward `0` 与 `1` 都是不可重采样的终态；候选越界形成终态 `0`。缺少当前 qualification 是不消耗重试额度的前置条件。模型退出后先持久化候选 JSONL/结果并核算 rollout，再执行同身份临时目录清理；清理失败只把阶段停在 `candidate-finished`，不得遮蔽或重跑已经完成的模型输出。基础设施失败在身份不变时最多重试一次，并要求 `--retry-reason`；如果已有 `candidate-finished` 或 `patch-captured` 产物，`run` 会阻止重新调用模型并要求 `recover --attempt-id`。`recover` 重新核对冻结身份，必要时先重试同身份清理，再核对 patch；它优先复用已经落盘的不可变候选/Verifier 收据，只在缺少 Verifier 收据时重建 Verifier。进程死亡留下的单题锁可按 PID 只回收已证明失活的 owner；带超时的依赖或 Verifier 命令会用精确 PID 终止完整 Windows 后代进程树，保留超时日志，并在清理工作树前有界等待句柄释放。终态工作区默认清理，显式 `--retain-workspace` 才保留。

## 计分与完成边界

Python 使用 pytest JUnit；Jest 使用内建 JSON 的 `fullName`；Vitest 使用内建 JUnit 并转换为与上游 `junit-to-ctrf --use-suite-name` 相同的 `<classname>: <name>`。Meriyah 固定 grader 语料中的非 BMP node identity 来自 UTF-16 surrogate replacement，并同时使用 NFC；只有该题的 report 合同显式启用同一转换，其他 JUnit 名称保持原值。sandbox 内的测试只收到 Verifier workspace 下 `.agentbase-verifier/reports` 路径；可信父进程验证普通文件、边界和 64 MiB 上限后复制或转换到 state artifact，再把这些可信报告路径写入任务原始 `config.json` 的派生副本，最后调用每题字节一致、SHA-256 固定的 DeepSWE `grader.py grade`。grader 仍按原始 P2P/F2P node ids、missing-as-failed、worst-status-wins 和二值 reward 计分。task 可声明 `exclude-stable-skips`，把映射到固定 P2P 集的 JUnit `skip` 作为候选排除集；仅当上游 base tests 在 Windows 存在确定性不兼容时，才可声明 `exclude-stable-nonpassing`，同时投影其 `failure/error`。两种策略都只读取 `base` bucket，不接触任务新测试；首个 no-op、后续 no-op/reference 及真实候选的观察必须逐项完全一致，且跨两次 qualification 稳定，排除集进入 identity 与收据。未映射结果、任务新测试、集合漂移或候选新增失败均不被中和，也不得用策略修正 F2P。

Windows 命令适配、报告转换与环境已经改变，所以结果只能说明 AgentBase Windows SWE 语境下的仓库级泛化能力。`report` 保留资格状态、每题 reward、覆盖、耗时、能力合同与基础设施健康；候选运行结束后只从本次新建的隔离 runtime rollout 读取根线程与全部后代线程。每个线程按 `subagent_history_start_ordinal` 排除继承前缀，以 `turn_context.model` 和逐响应 `last_token_usage` 计算普通输入、缓存命中、缓存写入和输出成本；超过 272K 输入的请求单独应用价格快照中的长上下文倍率，不能用线程累计 Token 代替。结果同时给出主代理、子代理、所选正式结果及当前 framework/corpus/candidate 身份下所有已调用模型尝试（包括后续失败或重试）的美元成本。该值按官方 API 单价精确折算，但当前 transport 使用 ChatGPT backend，因此 `actual_billing_observed=false`，不表示 Codex 订阅账单。

`assess` 再组合部署 `Validate` 的 Windows 原生合同、真实 candidate isolation preflight、当前路由 evidence 和所选 SWE 报告，形成 `windows-native-contract`、`candidate-verifier-isolation`、`routing-behavior`、`external-generalization-reward`、`cost-and-time`、`infrastructure-health` 六个独立维度。路由评估尚未持有逐响应模型与缓存写入证据时只保留 Token/时间，不并入 SWE 的 API 等价美元值。`failed`、`blocked` 与 `pending` 分开，`composite_score` 固定为空，不以一个任意总分掩盖缺题或未验证范围。

新 clone 中九题默认都是 `pending`。只有真实 Windows no-op/reference qualification 完成后该题才可被 `next` 或 `run` 使用；确定性单元测试只证明框架合同，不证明任一真实题已完成资格验证。

## 确定性验证

```powershell
& (Join-Path (Get-Location).Path 'development\agent-evaluation\test_agent_evaluation_infrastructure.ps1') -ProjectRoot (Get-Location).Path
```

该入口设置 `AGENTBASE_AGENT_EVALUATOR_DISABLED=1`，只运行静态语料校验与单元测试。部署 `Validate` 和真实 `Publish` 前置消费它，但不会克隆外部源码、安装任务依赖、运行 oracle、启动模型或执行真实候选 Verifier。
