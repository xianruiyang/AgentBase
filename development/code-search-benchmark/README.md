# 代码搜索收益基准

本目录是项目内唯一的源码查询基准 owner。`analyze.py` 保留局部工具路径的模型可见 Token 后处理；`experiment.py` 负责真实 Codex 对照的身份冻结、平衡调度、外部监控、事件归档和 detached audit capsule，并消费 `development/common/codex_runtime.py` 的共享脱敏 launcher 环境与 `development/common/codex_shell_environment_policy.json` 的模型 shell 合同。两者不实现查询语义，也不进入 srcq 或 Codex 发布 payload。

正式语料在 `corpus/`；`v21.json` 是当前候选，沿用 `v20.json` 的完整文件身份与实现范围合同，并把 C++ 题面中已评分的空/非空分支及下游转发关系显式化；同一完整文件身份下可分组列出多个位置，避免重复路径同时保持跨文件边界。完整实现范围包含声明行和适用语言的闭合分隔符所在行；嵌套实体与包围实体分别计算，不含前置注释、属性或相邻实体。调用、分支、清理、消息边界、位置准确性和静态边界合同不变，旧版本只服务引用它们的历史结果复核。真实对照先由独立配置生成 experiment，预检环境差异只包含 allowlist 后才运行；candidate-only 迭代同样冻结完整环境和 experiment identity，不能与不同身份拼成精确 A/B：

```powershell
python -X utf8 development\code-search-benchmark\experiment.py prepare --config <config.json> --output <new-output-dir>
python -X utf8 development\code-search-benchmark\experiment.py run --experiment <new-output-dir>\experiment.json
python -X utf8 development\code-search-benchmark\experiment.py capsule --experiment <new-output-dir>\experiment.json
```

隔离 home 由 `development/source-query-gateway/prepare_benchmark_homes.py` 创建，并应放在 `%LOCALAPPDATA%\AgentBase\benchmark-homes\<run-id>` 等稳定隔离根；入口会拒绝 `%TEMP%` 下的目标，因为 Codex 会拒绝在临时 home 建立命令 helper，使 subject 处于降级状态。每个正式工作区通过重复的 `--trusted-project` 在两侧配置中预登记，避免首次访问自动写入 trust 造成冻结身份漂移。迁移对照默认只复制因果 skill 集；专门研究用户定义的完整 Control 时使用 `--baseline-mode current-control --codex-exe <current-codex.exe>`：入口精确复制当前 `AGENTS.md`、全部用户 skills 和当前 remote-plugin cache，快照当前启用插件的 marketplace 内容，以官方 `codex plugin add` 安装并读回全部插件，再由完成后的 Control 克隆 Candidate。共享插件快照由两侧相同的依赖收据引用，其逐文件哈希与 `plugins/cache` 实际安装内容都并入环境树；不能只复制 `~/.codex/skills` 或只写 `plugins.*.enabled=true`。候选二进制在复制前必须通过真实 `srcq rg <native argv...>` 探针，仅版本号相同但入口陈旧的 release 会被拒绝。

每个 subject 都由新的 Codex 进程执行，并强制 `approval_policy = "never"`、`ephemeral = true`、`sandbox = "danger-full-access"` 和正常速度 `service_tier = "default"`。正式新实验把 `codex.client_protocol` 冻结为 `app-server-v2`，由公开 App Server JSON-RPC 启动单个 thread/turn；旧档案的 `exec-json` 仅保留兼容读取，不能提供逐请求缓存证据。每个隔离 home 还必须显式设置 `features.multi_agent = false`；runner 会把只读与不得创建子代理写入公共 prompt 前缀，并把该执行合同、实际模型与 reasoning effort 一并冻结到 experiment identity。config 还必须把 `codex.transport` 明确冻结为 `websocket` 或 `http-only`；前者使用内置 ChatGPT provider，后者使用 runner 内建且同样绑定 ChatGPT OAuth endpoint 的 HTTP-only provider。full access 只解除 Codex 路由层对真实查询命令的误拦截，不改变 prompt 的只读合同；运行前后的身份读回负责发现越界修改。Fast/Priority、隐式 client protocol/transport、其他 sandbox 或不匹配的 Codex 可执行文件都不属于正式基准，prepare 与 run 会拒绝对应 manifest。

正式 config 必须提供 `runtime_environment.dotenv_path` 和非空 `runtime_environment.required_keys`。共享 runtime owner 只从该文件投影 `ALL_PROXY`、`HTTP_PROXY`、`HTTPS_PROXY`、`NO_PROXY`、`CODEX_CA_CERTIFICATE`、`SSL_CERT_FILE`；启动 subject 前先清除父 shell 中未冻结的网络别名、OpenAI/Codex 凭据、常见 token、Git/SSH/语言注入与工作目录控制键，再注入冻结投影和当前 subject 自己的 `CODEX_HOME`。这些键只服务 Codex 连接：每次 preflight/subject 的 CLI 参数同时固定 `development/common/codex_shell_environment_policy.json`，从模型 shell 过滤 proxy、OpenAI/Codex、Git/SSH、云/包管理器凭据命名空间及语言注入变量，策略 SHA-256 进入 experiment identity，`extra_config` 不得覆盖。SOCKS 环境可显式用 `proxy_dns = "remote"` 把 `socks5` 规范化为 `socks5h`，并用 `all_proxy_fanout = "http-and-https"` 在原文件没有专用键时把有效 ALL_PROXY 投影到 HTTP/HTTPS 客户端；两项都进入实验身份，不作隐式猜测。`.env` 本身及变量值不复制进隔离 home、experiment、日志或 capsule；manifest 只保存来源、键名、转换选项和整体投影 SHA-256。prepare 后有效投影或共享 shell policy 变化会使 run 在启动 subject 前拒绝。当前 Codex 使用代理时，配置应显式指向当前安全 Codex home 的 `.env`，不能假设启动 shell 已经加载它。

control/candidate home 的 `config.toml` 不得再定义 `shell_environment_policy`；prepare 会在模型前拒绝第二 owner。两侧差异继续由 home tree identity 维护；`environment-dependencies.json` 声明的冻结目录也作为带命名空间的环境树成员在 prepare 与 postflight 重算，模型 shell 过滤只由共享 policy 决定。

```json
{
  "network_policy": "configured",
  "codex": {"transport": "websocket", "client_protocol": "app-server-v2"},
  "runtime_environment": {
    "dotenv_path": "%USERPROFILE%\\.codex\\.env",
    "required_keys": ["ALL_PROXY"],
    "proxy_dns": "remote",
    "all_proxy_fanout": "http-and-https"
  }
}
```

`prepare` 先绑定 Codex 可执行文件的绝对路径、版本、大小与 SHA-256，再对实际 `run_environments` 用完整正式参数各执行一次能力预检：含 srcq 的环境必须在同一个 Codex 中分别成功运行 `srcq.exe --version` 与 `srcq query scc doctor`（迁移前无 srcq 时为 `rg.exe --version`），从真实 command event stdout 取得预期输出和完整 usage。预检在已经由 home preparer 同时登记到两侧的正式工作区运行；多工作区配置可用 `preflight_workspace_role` 指定角色。runner 在预检前后比较所有声明 workspace identity，任何改动都会拒绝 prepare；不得创建只登记到被预检一侧的临时工作区，否则 Codex 自动写入 trust 会破坏环境等价。candidate-only 迭代不额外启动 control 预检；完整 A/B 仍预检两侧。preflight 与 subject 的 JSONL/stderr 都结构化统计 WebSocket 连接失败、sampling retry 和 HTTP fallback；预检出现任一项即拒绝 prepare，subject 出现则写入 `postflight_failures`，不得进入有效聚合。

monitor 捕获 App Server stdout JSONL、stderr、退出、wall time、工具项、`thread/tokenUsage/updated` 的逐请求 `last` 与累计 `total`，并以累计值去重；逐请求之和无法与最终累计量严格对齐时，理想缓存指标标记不可用。`exec-json` 旧档只保留最后一个 `turn.completed.usage`。超时会终止该次进程树并保留失败，不静默重试。run 还会核对 runner 源码 SHA-256 与 Python 完整版本，防止 prepare 后用另一套实现消费旧 manifest。运行前后都重算 corpus、声明范围内的工作区 Git 快照和最小 Codex home 环境树身份。`workspaces.<role>.identity_paths` 可把大型工作区限定到语料与规则实际依赖的相对路径；未指定时仍冻结整个仓库，任何范围都保留该范围内 tracked patch 与全部 untracked 内容哈希。凭据和 `.env` 不得复制进实验目录或环境树，只能通过既有安全环境提供。

`summary.json` 同时保留原始 usage、逐请求 usage、逐 run 规范化分项和按环境汇总：普通输入、缓存读取、缓存写入（事件提供时）、输入、可见输出、推理输出、输出与 `input + output` 总量。推理输出是 output 子集，缓存读取/写入是 input 分类，均不得重复相加。逐请求字段完整时，`observed_request_price_report` 按每个请求自己的上下文长度计算实际精确价格；只有聚合 usage 时仍保留全短/全长边界，不把请求阈值或缺失字段静默猜成确定值。

`ideal_cache_report` 只能表达更窄的可证反事实：“保留 subject 启动时已经观察到的缓存状态，并在同一前缀 epoch 内不再驱逐已由 usage 证明写入的前缀”。首次请求沿用实际 cache read/write，后续请求只能消费此前已观察到的 retained prefix；`contextCompaction` 开启新 epoch。如果后续 cache hit 超过此前 usage 可证明保留的前缀，说明 App Server 没有给出完整写入历史，投影必须标记 `cache_write_accounting_inconsistent_with_later_hits`，不得把 `cacheWriteInputTokens = 0` 解释为没有发生有效写入。逐请求和累计量不一致、字段不完整或前缀无 compaction 回退也同样不可用。

“服务器在 subject 启动前也从未丢弃任何历史前缀”的全局最理想缓存量不能只由逐请求 Token 计数确定：协议未提供跨 subject 的 prefix identity、实际 breakpoint 或完整写入来源。旧 `exec-json` 档案连逐请求 usage 也没有，更不能在不重跑的情况下补算。报告在证据不足时保留 `unavailable`，不从聚合缓存率、输入增长或全输入上限反推一个伪精确值。

当前 GPT-5.6 价格系数与实验模型的标准处理单价随 experiment identity 冻结。以“短上下文普通输入 Token = 1”为基准，短上下文为 `普通输入 1 / 缓存读取 0.1 / 缓存写入 1.25 / 输出（含推理）6`；单次请求输入超过 272K 时，整次请求对应 `2 / 0.2 / 2.5 / 9`。聚合 actual usage 仍分别给出全短、全长和总边界；逐请求证据可用时，observed price 按每个请求自己的输入长度给出精确美元值。只有 cache-retention 投影本身可用时才计算对应反事实价格。2026-09-01 的 Luna standard 单价为 `$0.20 / 1M` 普通输入、`$0.02 / 1M` 缓存输入和 `$1.20 / 1M` 输出。Fast 不属于正式基准。

每个 manifest 使用 `agentbase.code-search-benchmark/v1`，`runs` 中每项记录：

- `caseId/route/language`：同一质量目标与实际路径；
- `temperature`：`cold` 或 `warm`；
- `elapsedMs`：从该路径开始到取得足够证据的总耗时，包含失败与回退；
- `evidenceComplete: true`：结果已覆盖同一验收目标；不完整窗口不得进入收益比较；
- `targetCount`：同一中间结果实际服务的目标数；
- `resultFiles`：按调用顺序保存的所有模型可见结果，包括失败结果；
- `skillFiles`：该路径首次需要加载的完整 skill/引用；同一文件在单项内只列一次；
- `command`：模型可见的实际命令或 MCP 参数文本。

文件路径相对 manifest，必须保持在该目录内，单文件上限 1 MiB。分析器使用 `o200k_base` 精确统计，输出每次运行及按 route 汇总的 Token、每目标 Token 和耗时中位数：

```powershell
python.exe -X utf8 development\code-search-benchmark\analyze.py <manifest.json>
```

至少覆盖 C++、Python、TypeScript 的短/中/长定义，单目标/同文件多目标、重载或嵌套项，以及 `rg` 的 0/1/N/N+1 和 LSP 的快/慢/空/失败状态。比较时先保证 `evidenceComplete` 和目标语义一致，再比较总 Token，最后比较耗时；不得用不完整固定窗口作为低成本胜者，也不得忽略首次 skill、失败或回退。
