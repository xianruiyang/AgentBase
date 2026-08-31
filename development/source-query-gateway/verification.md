# 统一源码查询网关验证记录

## 1. 记录边界

本文件只汇总本分支候选的可重复验证结果。命令输出、测试代码、语料和独立评估原始文件仍由各自项目入口或项目外 capsule 承担；这里不复制大日志，也不把局部验证扩张为端到端模型收益。

`candidate-skill/`、`build_routing_capsule.py`、`verify_candidate_payload.py` 与 `routing-cases.json` 只冻结 P9/P10 的历史评估输入和复算入口，不是当前发布 payload、运行时消费者或需要随 P13 合同迁移的派生真源。当前模型消费入口是仓库根 `skills/source-query/`，当前路由评估由 `development/skill-routing/` 维护。

## 2. 已完成验证

下表中的“当前”均指 P0—P10 各自冻结身份；P11 的新身份和证据单独列在表后，不用后继源码反向改写历史运行数字。

| 范围 | 入口 | 结果 |
| --- | --- | --- |
| P0 backend 合同 | `backend-contract/tests` | 6 项通过；版本、模式表、fixture、语义分类与原生 no-match oracle 一致 |
| AST 精确版本 | P0 ast-grep 0.41.1/0.42.0/0.44.1 矩阵 | 30 项通过 |
| P9 srcq Rust workspace 门禁 | `cargo ci-test`、`cargo ci-build`、`cargo lint`、`cargo fmt-check` | `srcq 0.3.1` 的全部 workspace、all-targets、all-features 非 ignored 测试、构建、Clippy `-D warnings` 与格式检查通过；真实引擎发现的 machine 消费者遗漏修正后做了定向复验 |
| P9 真实 ast-grep 0.44.1 | `SRCQ_AST_GREP=<native exe>`、`SRCQ_AST_GREP_EXPECTED_VERSION='ast-grep 0.44.1'` 后运行受影响 ignored 套件 | CLI 3 项、core profile 1 项、integration workflow 4 项通过；默认 model 与显式 machine 消费边界已覆盖 |
| P9 rg/fd 定向单元 | `cargo test -p srcq-cli --lib` | 37 项通过；覆盖原生 token 不被 wrapper 抢占、有序路径树、前缀重入回退、cursor 与模式分类 |
| P9 rg/fd 真实集成 | `cargo test -p srcq-cli --test query_gateway_real` | 25 项通过；除直接入口、表示选择、预算、续页和三输出面外，覆盖同预算小结果闭环、宽多文件保持分页、rg 15.2、未来版本、变化协议安全降级、machine 转换错误和副作用不重放 |
| P9 srcq-cli 静态质量 | `cargo clippy -p srcq-cli --all-targets --all-features -- -D warnings`、`cargo fmt --all -- --check` | 通过 |
| P9 release helper | `cargo test -p srcq-release`、当时的 `build-release.ps1` | 4 项通过；生成绑定源码快照的 `srcq 0.3.1` Windows x86_64 MSVC manifest、SBOM、许可证和受校验归档；归档 SHA-256 为 `2ce4c7351ca7d7e469f66b473852e3a6b97c52e1935fe5e4544042df602b2915` |
| P9 backend 候选矩阵 | `backend-contract/verify_candidate.py --srcq <srcq.exe>` | 当时直接/显式入口下 29 个模式样本、7 个原生 oracle 通过 |
| P9 AST 候选非回退 | `ast-baseline/compare_ast_baseline.py --expected-version 0.3.1` | 通过；比较器只剔除新增 rg/fd/query 行，不改写历史 AST 期望 |
| 候选 skill | skill-creator `quick_validate.py` | 有效 |
| 候选 payload | `verify_candidate_payload.py` | 5 个允许文件，无二进制、私有运行时或开发资产泄漏 |
| Windows 安装生命周期 | `tools/srcq/scripts/test-install-srcq.ps1`，0.3.0 → 0.3.1 | 当前归档安装、幂等、完整性读回、受管漂移修复、新进程 PATH、失败回滚、恶意包/篡改拒绝、真实升级、doctor、卸载边界、并发 PATH、配置/cache 保留与显式清理通过 |
| 完整短查询按需 snapshot 机制 | 同一 release 查询、25 个唯一 argv、A-B-B-A，本机进程总耗时 | 旧实现 4115.9/3918.1 ms 且每轮落 25 个 snapshot；当前实现 3870.5/3875.3 ms 且 0 snapshot，均值少 144.1 ms（3.59%） |
| 正式 Skill 静态校验 | skill-creator `quick_validate.py` | `source-query` 与 `symbol-structure-workflow` 均有效；前者恰为 5 个协议文件 |
| 当前 detached 路由 | `development/skill-routing/evidence/current.json` | 69/69 首次路由、69/69 行为策略、13/13 治理引用由三个不同的 `gpt-5.6-sol`/medium/default 运行通过；当前候选 bundle 为 `E721424A…A63DEB`，各评估器均声明未访问仓库或隐藏期望 |
| 原生 LSP 渐进路径 | `evidence/lsp-progressive-v1.json` | no-LSP、单项与多阶段三案均按预期只调用 0/2/3 个 MCP 能力，质量通过、usage 完整；独立审计结论为 `pass_with_execution_caveat` |
| 当前正式部署合同 | `manage_agentbase.ps1 -Action Validate` | 当前候选、11 个 Skill、`source-query`、portable settings、MCP、69-case 路由证据与直接兼容 payload 通过只读发布前验证；未执行 Publish |
| 插件 payload 边界 | 隔离 `build_plugin.ps1 -SkipOfficialValidation` 与当前静态合同 | 11 个 Skill；`source-query` 恰为 5 文件且无 `.exe`；正式发布构建仍须在获得本次发布授权后执行 |
| benchmark owner 定向回归 | `development/code-search-benchmark/tests` 与 `source-query-gateway/tests` | 27 项 benchmark owner 和 11 项环境准备/路由测试通过；受影响 case、调度、回答合同、identity、capsule 与外部文件哈希、正常速度门禁、超时保留及 Token 分项/价格边界可重复 |
| Token 与价格报告合同 | `experiment.py` usage v2、GPT-5.6 当前官方系数 | 原始 usage、普通/缓存读/缓存写、可见/推理输出、实际总量和环境汇总已分离；短上下文 `1/0.1/1.25/6`、长上下文 `2/0.2/2.5/9` 随 experiment identity 冻结，缺失缓存写入或请求级上下文档位时只报边界，不伪造精确账单 |
| 当前 corpus | `corpus/v10.json`、`validate_corpus.py` | 6 项 oracle 与 AgentBase/GptProjectTest 绑定源码逐项验证通过；当前版本同时冻结同预算闭环、权威范围、续页和仅审查规则时的高级 skill 非触发边界 |
| 当前 candidate-only 全量审计 | `evidence/audit-result-v12.json` | 12 次中 11 次 usage 完整，完整 run 合计 1,004,033 Token；1 次 TLS 超时原样保留，无 control |
| 上一冻结身份 Codex 对照 | `evidence/audit-result-v13.json` | 24/24 运行正常退出且 usage 完整；两边质量 12/12；candidate 相对 control 总 Token `6,115,095 → 4,208,028`（`-31.186%`），耗时 `1,174,966 → 938,489 ms`（`-20.126%`）；不覆盖本轮直接入口和自适应输出 identity |
| 关系 case 受影响审计 | `evidence/relation-audit-v1.json`、`evidence/relation-audit-v2.json` | 保留规则取得全部源码证据；更强规则增加 Token 而未改善 prompt 必答内容，已退出 |
| 回答合同适用性审计 | `evidence/oracle-audit-v1.json` | 两次答案均满足 prompt 最小合同；未复述 supporting mapping type 不构成 core fail |
| 历史隔离模型审计 | `evidence/audit-result-v11.json` | 旧候选核心与严格语义 12/12、格式与严格整体 11/12；不覆盖当前候选 |
| 历史端到端成本 | `development/code-search-benchmark/experiment.py` monitor | 旧候选实际总 Token 1,146,601、404.603 s；不覆盖当前候选 |
| P9 最终候选 | `evidence/audit-result-v15.json`、`evidence/capsule-verification-v15.json` | identity `e32871ba…`；12/12 语义与可见行限通过，1,150,528 Token、363.163 s、48 次命令无失败；作为 P10 当前可比较的同质量参照 |
| P10 最终候选 | `evidence/audit-result-p10-v21.json`、`evidence/capsule-verification-p10-v21.json` | identity `0cfb8919…59d5`；12/12 required、12/12 行限与 12/12 evidence complete，通过 45 次成功命令、1,066,470 Token、480.739 s；detached auditor 复算身份、usage、环境差异和逐案质量后通过 |

### P11 scc 指标与 hyperfine 主机能力

| 范围 | 结果 |
| --- | --- |
| srcq 0.4.0 | `cargo ci-test` 全 workspace 通过；受影响定向 lib 51/51、真实 query gateway 33/33；`cargo ci-build`、`cargo lint`、`cargo fmt-check` 与 release helper 6/6 通过 |
| 后端与 AST | backend 合同 6/6、36 个 rg/fd/scc 模式、9 个原生 oracle 通过；0.4.0 AST baseline 通过；ast-grep 0.44.1 受影响真实套件此前为 CLI 3/3、core 1/1、integration 4/4 |
| 主机与发布消费者 | bootstrap 回归和后继当前只读 Check 通过，8 个工具全部 supported，读回 scc 3.7.0 与 hyperfine 1.20.0；portable config/agent/lifecycle、插件构建及部署 scc doctor 解析烟测通过 |
| 模型读取面 | AgentBase 16 种语言、1165 文件；o200k languages `1008→457`，files 原生 json2 `126325→25997`（-79.4205%），同快照旧扁平候选 `43836→25997`（-40.6949%）；cl100k 旧候选 `43723→25922`（-40.7131%）。v2 benchmark 绑定双方二进制和输出 SHA-256，只证明完整静态投影 |
| release/install | 源码快照 `008117d7…67a3`；两次 clean build 均得到 2730989-byte、SHA-256 `b43ad3f1…ba6f` 的 0.4.0 ZIP；manifest 含 scc 3.7.0；0.3.1→0.4.0 隔离生命周期及最终 release AST/scc doctor、rg/fd、files tree、hotspots flat 烟测通过 |
| 路由 | 静态 96 cases、55 strict routing、10 strict references、11/11 skills 及后继独立 Routing/Policy/References 96/96/26 已通过；本次未改变路由输入，不重复调用 evaluator |

## 3. 证据边界

冻结五-skill 历史记录为实际总 Token 1,157,111、508.509 s、核心 12/12、严格整体 11/12；按用户要求未重跑。当前候选的 1,150,528 Token 和 363.163 s 方向性分别低 0.57% 与 28.58%，独立审计按可见 prompt 判定 12/12；历史 identity 与 prompt 明示程度不同，因此不把差额声明为严格因果收益。

P10 最终候选没有命令失败、usage 缺失、超时、环境越界或 postflight 漂移。相对 P9 同质量参照，总 Token 少 `84,058`（`-7.31%`），命令少 3 次（`-6.25%`），但耗时多 `117.576 s`（`+32.38%`）。按质量、Token、速度的顺序，当前证据支持采纳 Token 收益，不支持宣称速度改善。

逐命令审计已经把工具同预算闭环、全局证据路由与最近项目修改前置阅读边界分配给各自 owner；8192 默认、固定操作配方和过宽高级 skill 均由反向 identity 退出。重复运行仍有正常路径波动，但没有共享失败、错误入口、截断或缺失能力支持另一项低风险高收益改动；P10 在当前 corpus、模型、项目快照与 Provider 条件内达到收益边缘。项目真源已完成，P9 曾于 2026-08-16 发布；本轮 P10 尚未获得新的逐次发布授权。

新的 advisory scan 未运行，因为当前授权环境未安装 `cargo-audit`；候选 release record 已明确记录该限制。

历史双环境实验只证明当时冻结的六类 corpus 与身份，不覆盖后续候选；其中 candidate 的 4 次 hard tool failure 与 control 的 2 次只作为历史可靠性观察保留。P10 使用只运行新候选的完整 identity，并以 P9 同质量候选作方向明确的当前参照；它不伪装成同 identity A/B 因果实验。LSP 三案仍直接支持未改动的渐进能力裁决。

## 4. 新模型输出设计的验证状态

SOL-SQG-010 已实现：rg/fd 普通调用只传原生 argv，显式控制进入 `srcq query`；renderer 在真实结果后比较单行、heading 与保持顺序的路径树；内部预算按完整证据单元分页；全局规则、source-query、CLI 文档和 backend verifier 已迁移。用户已审查并认可单一命中、同文件多命中、共享目录多文件、fd 树、无匹配和错误恢复的真实默认输出；最终 identity 已由本轮 candidate-only 运行、确定性验真和独立语义审计共同冻结。

当前组件证据覆盖 argv 冲突、模式分类、原生 oracle、输出选择、顺序回退、分页/cursor、同预算自动闭环、machine/raw/artifact、AST 非回退、Windows release 与安装生命周期。最终真实隔离候选再覆盖模型质量、总 Token 和耗时；detached auditor 做语义、结构、环境与 usage 裁决，确定性入口重算密码学身份和外部原始文件。两者共同关闭 AC-SQG-002、AC-SQG-003、GAP-SQG-007 与 GAP-SQG-008。

## 5. 最终逐项审计

以下表格与结论冻结 P10 身份；P11 的增量完成结论见第 6 节。

| 状态 | 条目 | 当前证据边界 |
| --- | --- | --- |
| 已证明 | REQ-SQG-001；AC-SQG-001 至 AC-SQG-008；CON-SQG-001 至 CON-SQG-003 | 组件、release/install、路由、LSP 渐进三案、P10 12-run usage、独立语义审计和确定性 capsule 校验共同覆盖 |
| 已证明 | UDES-SQG-001 至 UDES-SQG-014 | 唯一 srcq 入口、原生兼容、自动最低充分输出、同预算闭环、AST 基线、Windows 生命周期、分层触发、benchmark 隔离与源码升级授权边界均有直接实现或验证 |
| 已执行 | P9 实际 Codex 安装 | 2026-08-16 已通过正式增量入口发布 DirectCompatibility 与 `srcq 0.3.1`；该状态只覆盖已验证的 P9 identity，不授权或证明 P10 |
| 项目已完成、待发布授权 | GAP-SQG-008 / P10 | v21 以 12/12 质量和 `-7.31%` 总 Token 关闭缺口；项目真源已实现，Codex 安装态仍是 P9，不能把项目验证外推为已发布 |

因此 requirements 与 user-design 的项目实现和证据已经完成；P10 的真实模型收益由 v21 而不是方案文档证明。当前唯一未执行的是需要逐次单独授权的 Codex 发布，它不属于项目真源完成证据。

## 6. P11 增量完成边界

P11 的源码、唯一 owner、直接与间接消费者、确定性验证、真实 scc、真实 tokenizer、release manifest、可复现归档和安装生命周期已经闭合；后继 files 目录树差距也已按同一交付链关闭，没有已知适用失败或开放实施项。当前独立路由 evidence 已由后继增量计划刷新，且本次路由输入未变；目录树的静态 Token 收益仍不冒充端到端模型行为。实际用户安装仍为 srcq 0.3.1，本轮也未获真实 Publish 的逐次授权，因此不得把 0.4.0 项目完成外推为已安装或已发布。

## 7. P13 query model 可执行续页动作

| 范围 | 结果 |
| --- | --- |
| srcq 0.4.1 | `cargo ci-build`、`cargo ci-test`、`cargo lint`、`cargo fmt-check` 全部通过；query gateway 34/34，公共 query renderer 的 rg/fd/scc、machine、snapshot 与连续分页回归通过 |
| PowerShell 与无重扫 | 特殊 argv 覆盖空值、空白、美元、管道、双引号、反引号、单引号和换行；测试实际在新 PowerShell 7 进程执行 `@next`，第二页成功且 fixture scc invocation log 仍为 1 |
| skill 与部署消费者 | 静态合同 96 cases、55 strict routing、10 strict references、11/11 skills 通过；路由基础设施 6 suites/22 syntax files、0 evaluator runs；部署 `Validate` 通过 |
| independent Codex v6 | experiment `27ac16beea6ef195bd443057fc229b17af603d4d5c2aa7f54fcc31ca74ad20f5`；preflight 33.149 s，读回 `srcq 0.4.1` 与 scc `ok`；subject 27.522 s，直接执行 `@next`、第二页 exit 0，首项为 `D:/program/AgentBase/tools/srcq/crates/srcq-core/src/profile/paths.rs` |
| 环境与 capsule | preflight/subject 的 WebSocket failure、sampling retry、HTTP fallback 均为 0，postflight 无失败；capsule SHA-256 `fce108b55bce2871e2bb153e95725cebb5dd04d2530806aa28c07d31a6257926`，4 个原始文件和 2 个环境文件验真通过 |

这些证据关闭 AC-SQG-009 与 GAP-SQG-009，范围只覆盖正常同一轮 query model 续页；压缩后恢复、cache/process offset 协议和完整端到端 A/B 收益没有改变也未被外推。正式 0.4.1 archive、真实用户 srcq 升级和 Codex Publish 未执行；后两者继续受用户暂停与逐次发布授权约束。

## 8. P16 快速源码关系 0.5.0 候选

| 范围 | 结果 |
| --- | --- |
| 组件门禁 | `cargo ci-test` 全 workspace 通过；`cargo ci-build`、`cargo lint` 与 `cargo fmt-check` 通过。随后新增 add/only/exclude 真实边界时发现无元数据临时 cwd 会把祖先普通 `.vscode` 误当项目根；移除该弱标记、只保留实际 compile database 后，当前候选的 70 项 srcq-cli lib、12 项关系集成、Clippy `-D warnings` 与格式检查通过。关系测试覆盖定义/声明、变量/字段/枚举、位置身份、同名调用点保持歧义、显式范围、引用角色、双向调用、循环、虚分派 unknown、多语言 adapter 与 26-language capability；既有 AST、rg/fd/scc、cache/process、release 与 stress 合同未退化 |
| 真实 UAI 只读可靠性 | 从 `UeAgentCustomModelingPrimitives.cpp:295:70` 唯一选择 `UUeAgentAddPrimitiveToolBuilder::CreateRampToolBuilder`；引用只返回生产 `UeAgentInterfaceModule.cpp:101:102`，不会把 `plan/evidence/artifacts/*.cpp` 证据副本当作调用者；outgoing 把 `NewObject` 保持为 `semantic-unknown`，incoming 返回真实 `GetExtensionTools`；`BuildTool` incoming 增加 `semantic-unknown:virtual-dispatch`；名称查询还能跨 GptProjectTest workspace 找到 UE `FPaths::ProjectDir` 定义与声明 |
| release 性能 | `srcq 0.5.0`、ripgrep 15.1.0、ast-grep 0.44.1、hyperfine 1.20.0；固定 cwd/输入、warmup 1、5 runs：definition `235.3±21.0 ms`，references `492.7±18.9 ms`，outgoing depth 2 `1.051±0.033 s`，incoming depth 2 `4.315±0.155 s`，UE external definition `5.076±0.160 s`。树内依赖解析收窄前同一 outgoing 曾为 17.417 s，该反例已由项目/显式根/当前定义文件的有界策略关闭 |
| model Token | 本机 Python 3.14、tiktoken 0.13.0、`o200k_base`：唯一定义连完整正文 146 Token；locator/`@body` 133；引用 53；outgoing depth 2 为 93；incoming depth 2 为 92；UE 外部定义/声明及范围边界 161。`--body auto` 在本例比强制 locator 更低成本，因为避免长绝对路径续读命令；这些是实际 stdout 静态 Token，不外推为完整 Codex 会话成本 |
| skill 与路由静态合同 | P16 原始验证时，`quick_validate.py` 在 `PYTHONUTF8=1` 下通过；skill/trigger 合同以当时 HEAD 全局规则的临时只读投影验证为 126 cases、84 strict routing、28 strict references、13/13 skills。当时 worktree 的 `global/AGENTS.md` 用户改动使规则预算多 10 bytes，因此没有用非当前全局 identity 写回 evaluator evidence；该 dirty 边界后续已退出当前 worktree。本轮未改变全局规则、skill 或路由合同，因而没有重跑静态合同或模型 evaluator |

这些证据直接覆盖当前 0.5.0 候选的 C++ 真实消费者，以及 Go、Python、Rust、JavaScript、TypeScript、TSX、Java、C 与 C# 共用的 generic relation engine。C/C# 通过语言节点表、最小 fixture、references、incoming/outgoing、深度展开与 capability 测试接入，没有新增第二套关系算法；候选关系不证明 C 原型/宏、C# overload/partial/extension method/alias/file-scoped namespace 等编译器语义，也不证明全部语言依赖图、关系大结果同快照续页或完整 Codex 端到端 Token 收益。GptProjectTest 只作为只读语料，没有执行写入、构建或 UE 生命周期操作。未制作 release、未安装、未 Publish。
