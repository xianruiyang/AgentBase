# 代码搜索收益基准

本目录是项目内唯一的源码查询基准 owner。`analyze.py` 保留局部工具路径的模型可见 Token 后处理；`experiment.py` 负责真实 Codex 对照的身份冻结、平衡调度、外部监控、事件归档和 detached audit capsule。两者不实现查询语义，也不进入 srcq 或 Codex 发布 payload。

正式语料在 `corpus/`；`v10.json` 是绑定 srcq 直觉入口、同预算自动闭环、权威范围、普通续页、规则审查非触发和当前源码路径的现行六类语料，`v1.json` 至 `v9.json` 只服务引用它们的已完成历史结果复核。真实对照先由独立配置生成 experiment，预检环境差异只包含 allowlist 后才运行；candidate-only 迭代同样冻结完整环境和 experiment identity，不能与不同身份拼成精确 A/B：

```powershell
python -X utf8 development\code-search-benchmark\experiment.py prepare --config <config.json> --output <new-output-dir>
python -X utf8 development\code-search-benchmark\experiment.py run --experiment <new-output-dir>\experiment.json
python -X utf8 development\code-search-benchmark\experiment.py capsule --experiment <new-output-dir>\experiment.json
```

隔离 home 由 `development/source-query-gateway/prepare_benchmark_homes.py` 创建，并应放在 `%LOCALAPPDATA%\AgentBase\benchmark-homes\<run-id>` 等稳定隔离根；入口会拒绝 `%TEMP%` 下的目标，因为 Codex 会拒绝在临时 home 建立命令 helper，使 subject 处于降级状态。每个正式工作区通过重复的 `--trusted-project` 在两侧配置中预登记，避免首次访问自动写入 trust 造成冻结身份漂移。默认只复制该对照的因果 skill 集：迁移前 control 保留三个旧查询 skill，迁移后环境保留 `source-query`，两侧共同保留 PowerShell 与符号编辑职责；`.system` skill 仍按 CLI 要求复制。这样避免大型无关知识 skill 触发扫描上限或给 subject 注入额外上下文。只有专门研究完整安装态时才显式使用 `--full-installed-skills`。候选二进制在复制前必须通过真实 `srcq rg <native argv...>` 探针，仅版本号相同但入口陈旧的 release 会被拒绝。

每个 subject 都由新的 `codex exec --json --ephemeral --sandbox danger-full-access` 进程执行，并强制 `approval_policy = "never"`、正常速度 `service_tier = "default"`。full access 只解除 Codex 路由层对真实查询命令的误拦截，不改变 prompt 的只读合同；运行前后的身份读回负责发现越界修改。Fast/Priority、其他 sandbox 或不匹配的 Codex 可执行文件都不属于正式基准，prepare 与 run 会拒绝对应 manifest。

`prepare` 先绑定 Codex 可执行文件的绝对路径、版本、大小与 SHA-256，再分别用 control/candidate 的完整正式参数执行一次低成本能力预检：新 CLI 必须实际运行各环境 PATH 中的 `srcq.exe --version`（迁移前无 srcq 时为 `rg.exe --version`），成功产生工具事件和完整 usage。该预检既完成首次 home 初始化，也在正式调度前暴露认证、sandbox、PATH、CLI 身份、skill 扫描或模型命令执行故障；原始 JSONL、stderr、Token 与价格等价量单独归档，`summary.json` 同时给出 subject-only、setup-only 和 including-setup 三组汇总，不把准备成本藏起来。

monitor 只捕获 stdout JSONL、stderr、退出、wall time、工具项和最后一个 `turn.completed.usage`；超时会终止该次进程树并保留失败，不静默重试。运行前后都重算 corpus、声明范围内的工作区 Git 快照和最小 Codex home 环境树身份。`workspaces.<role>.identity_paths` 可把大型工作区限定到语料与规则实际依赖的相对路径；未指定时仍冻结整个仓库，任何范围都保留该范围内 tracked patch 与全部 untracked 内容哈希。凭据不得复制进实验目录或环境树，只能通过既有安全环境提供。

`summary.json` 同时保留原始 usage、逐 run 规范化分项和按环境汇总：普通输入、缓存读取、缓存写入（事件提供时）、输入、可见输出、推理输出、输出与 `input + output` 总量。推理输出是 output 子集，缓存读取/写入是 input 分类，均不得重复相加。若事件没有缓存写入量，报告保留可计量总 Token，但普通输入和价格只给上下界，不把缺失字段静默当成零。

当前 GPT-5.6 价格系数随 experiment identity 冻结。以“短上下文普通输入 Token = 1”为基准，短上下文为 `普通输入 1 / 缓存读取 0.1 / 缓存写入 1.25 / 输出（含推理）6`；单次请求输入超过 272K 时，整次请求对应 `2 / 0.2 / 2.5 / 9`。subject 的 `turn.completed` 是聚合用量，不能证明其中每次模型请求是否越过阈值，因此报告分别给出全短、全长和总边界，单位是相对价格等价量而非美元。Fast 与 Standard 的绝对价格不同，但当前 GPT-5.6 的这些相对系数相同。

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
