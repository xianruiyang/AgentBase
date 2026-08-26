# AgentBase Windows SWE 最终评测集

本目录是 AgentBase 仓库级最终评测的唯一 owner。它复用固定 DeepSWE v1.1 题目、隐藏测试、参考补丁与 `grader.py grade` 计分语义，但将执行层改为 Windows 原生候选/Verifier 双工作区。因此结果名为 **AgentBase Windows SWE**，不得作为官方 DeepSWE leaderboard 成绩。

## 职责与信任边界

- `corpus/final-v1.json`：九题、难度证据、suite、模型档位、上游提交、资产哈希、允许的源码范围、依赖安装和测试命令的机器真源。
- `agent_eval.py`：唯一公开 CLI，负责选择、源码准备、资格验证、候选尝试、恢复、不可变收据和报告。
- `evaluation_core.py`：语料校验、源码/任务身份、工作区、patch 边界、锁、尝试和收据。
- `agentbase_codex.py`、`invoke_candidate.ps1`：生成临时 Codex home，投影项目全局 AGENTS/config/agents，并把完整 skill 树派生到候选仓库的标准发现路径；复用共享原生 Codex 解析器和显式指定安装根中的既有认证，在 Windows elevated sandbox 中运行候选。
- `windows_verifier.py`：在候选结束后才创建干净 Verifier 工作区，安装原始提交依赖、应用候选 patch 与隐藏 `test.patch`、转换 Windows 原生报告并调用固定上游 grader。
- `development/common/codex_runtime.py` 与 `development/common/codex_shell_environment_policy.json`：多个本地 evaluator 共用的 `.env` 网络投影、launcher 环境净化与模型 shell 过滤 owner；本组件不复制凭据、代理值、过滤表或 ambient 控制变量处理。

候选只能看到任务说明、固定基础源码、该仓库自身指令、公开测试和 AgentBase 显式投影的能力面。自定义权限 profile 不继承宽泛预设：`:root = deny` 拒绝宿主默认读取，`:minimal = read` 保留公共工具运行所需最小路径，`:workspace_roots` 只赋予候选仓库写权限并把 `.agents/skills`、`.git` 与 `.codex` 收窄为只读，`:tmpdir = write` 只重开一次 attempt 的运行临时面。隐藏测试、参考补丁、qualification 与结果状态位于显式拒绝的 state root，项目真源和原始安装 Codex 根目录也不可读。认证只经临时 home 中受拒绝的 hardlink 供 Codex 客户端使用；`TEMP/TMP/TMPDIR` 指向该 attempt tmpdir，`APPDATA/LOCALAPPDATA` 是它的子目录，避免 srcq 缓存或宿主状态污染候选 patch。Codex 服务进程只保留冻结连接所需的网络投影，生成配置中的 `shell_environment_policy` 另外启用默认 secret-name 排除，并从模型 shell 过滤 proxy、OpenAI/Codex、认证/凭据和 Git 控制变量；无模型 `sandbox-check` 的 launcher 也由共享净化 owner 生成环境。Verifier 不运行模型，也不继承候选的依赖目录、测试配置或运行残留。候选和 Verifier 可以在同一 Windows 主机运行，但目录、依赖与信任边界彼此独立，二者唯一数据通道是经范围校验的 Git binary patch。

## 候选能力与证据层级

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
│  ├─ elevated Windows profile + explicit project/state/installed Codex deny + network disabled
│  ├─ process temp/appdata scoped to one attempt tmpdir
│  └─ multi-agent enabled; behavior remains explicit model evidence
├─ identity before model
│  ├─ Codex, srcq, rg, fd, scc, hyperfine, ast-grep, Git, pwsh, Python, Node
│  └─ task dependency runtime and npm/pnpm identity
├─ sandbox preflight before model
│  ├─ state/project canaries + staged/installed auth unreadable
│  ├─ every skill file hash-readable + skill tree write-denied + workspace write probe
│  ├─ exact TEMP/TMP/TMPDIR/APPDATA/LOCALAPPDATA attempt scope
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
   └─ command network, web search, hooks, host apps/plugins/MCP, install, publish
```

正式隔离合同要求 `elevated` 原生 Windows sandbox。[OpenAI Windows sandbox](https://learn.chatgpt.com/docs/windows/windows-sandbox) 与 [Permissions](https://learn.chatgpt.com/docs/permissions) 的平台边界说明 `unelevated` 不能执行全部读写拆分策略，因此它不能作为 state/installed-root deny 的等价降级；更窄的 `.agents/skills` read 与 `:tmpdir` write 按正式权限优先级覆盖 workspace/state 的宽规则。[Codex config reference](https://developers.openai.com/codex/config-reference/) 定义的 `shell_environment_policy` 是模型 shell 的独立环境边界，不能用 launcher 的服务连接环境替代。[Build skills](https://learn.chatgpt.com/docs/build-skills) 规定仓库 skill 从 `.agents/skills` 发现，并在选择时读取完整 `SKILL.md`、按需读取 references/scripts/assets，所以单个探针或 Codex home 中不可发现的副本都不能代表候选 skill 能力。`sandbox-check` 只在真实 preflight 通过后标记 `passed`；sandbox 已启动但 acceptance 未通过时返回 `failed` 和精确失败检查。若 Codex 的管理员批准初始化尚不可用，它返回 `blocked-precondition`、有界诊断和恢复动作；其他未知失败仍作为基础设施错误退出，不会被降级成前置条件。

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
│  ├─ qualification-runs\
│  ├─ qualifications\<task>\<identity>.json
│  ├─ attempts\<attempt-id>\
│  │  ├─ attempt.json
│  │  ├─ candidate.patch
│  │  ├─ runtime-temp\    (仅运行期；含 appdata/localappdata，结束后删除)
│  │  ├─ codex-logs\
│  │  └─ verifier\
│  ├─ results\<task>\<profile>\<identity>.json
│  └─ locks\
└─ agent-evaluation-workspaces\
   └─ <attempt-or-oracle>\
      ├─ candidate\    (终态后删除；有可恢复输出的中断会保留)
      └─ verifier-*\  (正常结束后删除；调试可显式保留)
```

state root 保存隐藏资产与机器收据；候选权限 profile 默认拒绝宿主文件读取，只重开 `:minimal`、候选 workspace 和每次 attempt 的 `:tmpdir`，并在 workspace 内把完整 skill 投影收窄为 read-only，同时显式拒绝项目真源、完整 state root 与已安装 Codex 根目录。state/work 必须互不包含，也不得与项目仓库或安装根重叠；tmpdir 虽位于 state 内，但只由更窄的临时路径规则开放，不能扩张到同级 canary、收据或 Codex home。仓库只维护语料、适配器和确定性测试，不提交 checkout、依赖、日志、报告或收据，这些开发资产也不进入 Codex 发布 payload。

## 使用

以下命令均从仓库根执行。`validate`、`list`、`next`、`check` 和 `report` 不安装软件、不运行模型，也不触发 elevated sandbox 初始化：

```powershell
python.exe -X utf8 development\agent-evaluation\agent_eval.py validate
python.exe -X utf8 development\agent-evaluation\agent_eval.py list --suite all
python.exe -X utf8 development\agent-evaluation\agent_eval.py next --suite core
python.exe -X utf8 development\agent-evaluation\agent_eval.py check --task returns-validated-error-accumulation
python.exe -X utf8 development\agent-evaluation\agent_eval.py report --suite all
```

真实权限验收与跨 owner 总评是显式入口：

```powershell
python.exe -X utf8 development\agent-evaluation\agent_eval.py sandbox-check --view machine
python.exe -X utf8 development\agent-evaluation\agent_eval.py assess --suite all --view machine
```

二者都不启动模型、不刷新路由 evidence、不执行 qualification、不安装题目依赖、也不 Publish；但首次建立 elevated sandbox 时，Codex 可能请求管理员批准并改变宿主 sandbox 配置，所以它们不属于日常 Validate/Publish 前置。`sandbox-check` 通过返回 0、真实 acceptance 失败返回 2、已知宿主前置条件未满足返回 3；`assess` 仍生成完整证据向量，把失败、阻塞和待补证据分别列出。

外部动作始终显式且一次只处理一题：

```powershell
python.exe -X utf8 development\agent-evaluation\agent_eval.py prepare --task returns-validated-error-accumulation
python.exe -X utf8 development\agent-evaluation\agent_eval.py oracle --task returns-validated-error-accumulation
python.exe -X utf8 development\agent-evaluation\agent_eval.py run --task returns-validated-error-accumulation --profile sol
python.exe -X utf8 development\agent-evaluation\agent_eval.py recover --attempt-id <attempt-id>
```

`prepare` 只克隆固定 DeepSWE task tree 与精确上游 base commit。`oracle` 不运行模型，但会在临时工作区安装题目依赖，并至少重复两次验证：未修改源码必须为 `0`，官方参考补丁必须为 `1`，各次依赖与 Verifier 运行工具身份必须一致。`run` 只接受当前 corpus/framework/task/dependency/verifier-runtime identity 的 qualification；Sol 固定 `medium`，Luna 固定 `max`。

`run`、`recover`、`sandbox-check` 与 `assess` 的 `--installed-codex-root` 默认取 `CODEX_HOME`，未设置时取 `%USERPROFILE%\.codex`；使用非默认安装根时必须在相关入口传入同一值。网络默认从默认 Codex 根的 `.env` 只投影 allowlist，descriptor 仅保存来源、键名、转换选项和整体 SHA-256，不保存代理值。该投影只供 Codex 服务连接；模型 shell 由生成配置过滤这些网络键以及 secret/control 类 ambient 变量，无模型 sandbox launcher 则从同一净化函数生成不含投影的进程环境。候选通过所选安装根中既有 `auth.json` 的临时 hardlink 使用认证，运行期间持有只读共享锁并在结束后删除链接；候选 profile 同时拒绝完整 state root 与原始安装根，认证内容和凭据不进入收据。固定 HTTP transport overlay 避免 WebSocket 反复重连，模型缓存只投影当前所选模型。

## 隔离、patch 与恢复

候选启动前，框架使用同一 `agentbase_candidate` elevated 权限 profile 运行无模型 preflight：

1. state root canary、项目根 `README.md` 与 staged/installed `auth.json` 必须不可读；
2. 框架从仓库 `skills/` 单向派生候选根 `.agents/skills/`，清单覆盖全部 `SKILL.md`、references、scripts 与 assets；child 必须逐文件核对集合、字节数和 SHA-256，并证明整个投影可读但不可写，候选仓库其他位置的独立写探针必须通过；
3. `TEMP`、`TMP` 与 `TMPDIR` 必须精确指向 denied state 内只为本 attempt 重开的 `runtime-temp`，`APPDATA` 与 `LOCALAPPDATA` 必须是其独立子目录；该目录与候选 workspace、项目和安装根互斥并在 preflight/运行结束后删除；
4. child 从 stdout 返回结果，由 launcher 校验并持久化；决定 `blocked-precondition` 的副本由 launcher 在模型启动前写入 denied state，候选可写的 workspace 副本不拥有尝试分类权；
5. 框架把模型前已经冻结的基础工具绝对路径、可执行文件 SHA-256 和版本参数写入 workspace 内的哈希固定清单；sandbox child 先验证清单，再验证并按精确路径执行 `srcq`、`rg`、`fd`、`scc`、`hyperfine`、`ast-grep`、Git、PowerShell、Python、Node；
6. 每次候选再把该题实际依赖运行时加入同一清单：Python 题使用 workspace venv Python，Node 题使用实际 npm 或 pnpm；
7. `srcq doctor` 与 `srcq query scc doctor` 使用清单中已验证哈希的同一 `srcq` 路径；随后以隔离语料实际完成 AST 查询及 cache info/remove、三页 `@next` 续读、fd machine tree、scc machine languages 和原生 artifact/machine envelope 往返。doctor 只证明环境可用，不能替代这些候选必需工作流。

完整 skill 投影和两份清单是每次 attempt 从项目真源重建的派生物，唯一消费者是候选启动前的权限验收与随后同一候选 Codex；它们由 Git exclude 隐藏且始终排除于候选 patch、项目提交和发布 payload。候选 prompt 对 Python 题明确使用已准备且身份固定的 `.agentbase-venv\Scripts\python.exe`，对 Node 题明确使用 corpus 固定的 npm/pnpm scripts，避免公开检查意外使用另一套依赖。候选可以用 shell、`apply_patch` 和公开测试修改题目 workspace，但这些以及自定义 subagent 的真实行为只有显式候选模型运行才能证明；无模型 preflight 只证明配置、身份、权限与确定性 CLI 工作流。需要 host/thread 服务、MCP、hooks 或插件安装的 skill 能力继续由相应组件 owner 单独验证。

候选 prompt 同时直接投影该题的 `allowed_patch_paths`。因此 Bandit 的 `setup.cfg` 或 Meriyah 的特定 snapshot 等合法解法不会被通用禁令误伤；清单外的测试、依赖与 lockfile 仍禁止，最终 patch 继续由同一 corpus 范围机械门禁。

候选 patch 最多 100 个文件、8 MiB，拒绝 symlink/submodule，并按题目只允许真实解法范围，例如 Bandit 仅允许 `bandit/**` 与官方解法确实使用的 `setup.cfg`。测试、runner、lockfile、`.agentbase` 和未列入该题解法范围的依赖 manifest 不会进入 patch。Verifier 在应用 patch 前从原始提交安装第三方依赖；题目确需在 patch 后刷新 build/codegen/可编辑包元数据时，只在 network-disabled Verifier profile 中执行并记入检查记录。

固定上游 patch 先按原始 SHA-256 验证，再经过唯一的保守归一化器：只在 unified hunk 声明范围内给缺失前缀的空 context 行补一个空格，其他字节不改。Verifier 收据同时记录源 patch、实际应用字节的 SHA-256 和补齐计数；这解决 SQL Formatter 上游参考补丁的 20 个 permissive 空行，同时不改变其解法内容。

尝试在模型进程前登记。有效 reward `0` 与 `1` 都是不可重采样的终态；候选越界形成终态 `0`。缺少当前 qualification 是不消耗重试额度的前置条件。基础设施失败在身份不变时最多重试一次，并要求 `--retry-reason`；如果已有 `candidate-finished` 或 `patch-captured` 产物，`run` 会阻止重新调用模型并要求 `recover --attempt-id`。`recover` 重新核对冻结身份和 patch，优先复用已经落盘的不可变候选/Verifier 收据，只在缺少 Verifier 收据时重建 Verifier。进程死亡留下的单题锁可按 PID 只回收已证明失活的 owner；终态工作区默认清理，显式 `--retain-workspace` 才保留。

## 计分与完成边界

Python 使用 pytest JUnit；Jest 使用内建 JSON 的 `fullName`；Vitest 使用内建 JUnit 并转换为与上游 `junit-to-ctrf --use-suite-name` 相同的 `<classname>: <name>`。适配器将这些报告路径写入任务原始 `config.json` 的派生副本，再调用每题字节一致、SHA-256 固定的 DeepSWE `grader.py grade`。grader 仍按原始 P2P/F2P node ids、missing-as-failed、worst-status-wins 和二值 reward 计分。

Windows 命令适配、报告转换与环境已经改变，所以结果只能说明 AgentBase Windows SWE 语境下的仓库级泛化能力。`report` 保留资格状态、每题 reward、覆盖、耗时、能力合同与基础设施健康；`assess` 再组合部署 `Validate` 的 Windows 原生合同、真实 candidate isolation preflight、当前路由 evidence 和所选 SWE 报告，形成 `windows-native-contract`、`candidate-verifier-isolation`、`routing-behavior`、`external-generalization-reward`、`cost-and-time`、`infrastructure-health` 六个独立维度。`failed`、`blocked` 与 `pending` 分开，`composite_score` 固定为空，不以一个任意总分掩盖缺题或未验证范围。

新 clone 中九题默认都是 `pending`。只有真实 Windows no-op/reference qualification 完成后该题才可被 `next` 或 `run` 使用；确定性单元测试只证明框架合同，不证明任一真实题已完成资格验证。

## 确定性验证

```powershell
& (Join-Path (Get-Location).Path 'development\agent-evaluation\test_agent_evaluation_infrastructure.ps1') -ProjectRoot (Get-Location).Path
```

该入口设置 `AGENTBASE_AGENT_EVALUATOR_DISABLED=1`，只运行静态语料校验与单元测试。部署 `Validate` 和真实 `Publish` 前置消费它，但不会克隆外部源码、安装任务依赖、运行 oracle、启动模型或执行真实候选 Verifier。
