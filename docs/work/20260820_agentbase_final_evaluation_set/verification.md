# 验证记录

## VER-001 确定性基础设施

- 状态: passed
- 覆盖: SOL-001—SOL-005, SOL-007—SOL-010

2026-08-21 运行：

```powershell
& (Join-Path (Get-Location).Path 'development\agent-evaluation\test_agent_evaluation_infrastructure.ps1') -ProjectRoot (Get-Location).Path
```

结果为 45 tests passed。除封闭语料、状态机、patch、报告和收据合同外，测试解析生成配置并证明候选 profile 不继承宽泛预设，具有 `:root = deny`、`:minimal = read`、`:tmpdir = write`、candidate root write、`.agents/skills/.git/.codex` read、project/state/installed-root 精确 deny和 network false；正式 `shell_environment_policy` 来自共享 JSON owner，Python/PowerShell 生成的全部 CLI overrides 字节一致，并启用默认 secret-name 排除、过滤 proxy、OpenAI/Codex、Git/SSH、云/包管理器与语言注入变量。PowerShell launcher 语法、根目录互斥、state 内 prompt/result、attempt tmpdir/appdata 和 sandbox-check 共享净化环境合同也通过；测试显式注入 ambient OpenAI/GitHub 凭据并证明它们不会进入 preflight launcher。完整 skill 投影测试覆盖全部文件集合与 manifest hash，并确认 `source-query` reference、`delivery-workflow` script 和 asset 确实进入派生树；候选 prompt 测试证明 Python/Node 分别使用已准备的 venv 与 corpus 固定 package manager，并证明 Bandit `setup.cfg`、Meriyah snapshot 等逐题合法路径直接来自同一 allowlist，清单外修改仍被提示与 patch 门禁拒绝。直接 preflight 测试按清单绝对 `.CMD` 路径执行全部基础工具 probe，以及真实 srcq AST/cache、三页 rg 续读、fd tree、scc machine 和 artifact 往返。基准无 sandbox 运行唯一预期失败为 `skill-projection-writable`，随后分别证明 skill manifest、工具 manifest、installed auth、项目 canary 与临时变量篡改形成结构化失败；真实 elevated profile 必须把 skill 写入拒绝后才能通过。测试同时证明只有 launcher 写入 denied state 的模型前失败结果能够形成 `blocked-precondition`，候选可写的 workspace 副本不能决定尝试分类。测试期间 `AGENTBASE_AGENT_EVALUATOR_DISABLED=1`，没有外部源码 clone、题目依赖安装、qualification、模型、真实 sandbox 或候选 Verifier。

额外无模型兼容探针使用当前用户 npm 原生 Codex CLI 读取共享 policy 的全部 33 个 `-c` overrides，`features list` 在临时空 Codex home 中返回 0；这直接证明当前 CLI 接受带通配符的 TOML dotted-key 参数。探针临时 home 已清理，没有读取认证、运行 evaluator、安装或发布。

## VER-002 共享与正式消费者

- 状态: passed
- 覆盖: SOL-005, SOL-009

2026-08-21 运行路由基础设施回归得到 `ready:true`、6 suites、22 个 PowerShell syntax files、0 次模型调用；`validate_contract.ps1` 通过 96 cases、55 个 strict routing、10 个 strict references 与 11/11 skills 正负触发覆盖。当前 Routing、Policy、References 三阶段计划均为 `reuse/visible_identity_and_oracle_valid`，`evaluation_count:0`，generation 保持 `4CE359AE0B4873D9D910ADB7371DF62E909678BE7C80CE6DD50167C5DD41E311`。

随后执行正式部署 `Validate`，再次消费 45 个评测基础设施测试并返回 `valid:true`。该入口没有执行 `Publish`；本轮也没有运行安装、真实 sandbox、qualification 或模型。安装状态未在本任务中重新核对，不能从 Validate 推断。

## VER-003 真实 Windows task qualification

- 状态: not-run
- 覆盖: SOL-006, GAP-003

本轮没有外部安装或 oracle 授权，九题均未运行 no-op/reference。基础设施完成不证明任何一题已经 qualified，也不证明 Windows 派生 reward 与官方 DeepSWE leaderboard 可比。

## VER-004 主机工具与权限外部证据

- 状态: passed-with-external-gaps
- 覆盖: SOL-006, SOL-008, GAP-003, GAP-006

只读 `check --suite all --view machine` 找到全部必需宿主工具且 `missing:[]`，其中真实 `ast-grep` 为 npm `ast-grep.cmd`；九个任务源码均为 `prepared:false`，入口没有安装或修改软件。最终 `report --suite all` 返回九题 qualification 全部 pending、18 个 task/profile 行全部 unqualified、0 个候选结果；能力合同 v4 保持 Sol medium、Luna max、elevated sandbox，列出 11 个完整 skill 投影、模型 shell secret 环境过滤、shell/`apply_patch`/公开测试等待模型行为、自定义 subagent 待显式模型证据，并分别声明宿主默认 deny、最小运行时 read、project/state/installed-root 精确 deny、attempt temp/appdata、skill 全树只读以及五项 srcq 工作流的真实探测责任。

本轮没有重新执行真实 `sandbox-check`：OBS-006 的最后一次真实无模型运行仍证明 elevated 初始化被 Windows 1223 取消，而 unelevated 拒绝所需 split policy；再次运行可能请求管理员批准并改变宿主配置，超出 CON-002。仓库内的阻塞分类、精确路径/哈希清单和受信结果链已有确定性覆盖，但真实权限 acceptance 仍是外部待补证据。
