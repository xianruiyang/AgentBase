# 统一源码查询网关分支实施计划

## 1. 文档职责

本文件只安排 [requirements.md](requirements.md)、[user-design.md](user-design.md) 与 [design.md](design.md) 已定义的源码查询工作，不创建总体项目需求。P0—P15 的实现、正式 `srcq` 身份、消费者迁移、LSP 渐进入口、同身份收益证据、最小证据闭环和六位临时续页句柄已经闭环；2026-08-30 因用户新增低延迟、多语言源码关系目标重开 P16。Codex 发布仍须逐次另行同意，当前安装状态由部署入口读回，不在计划中维护第二份状态。

## 2. 推进原则

- 先保证原生语义、答案质量、授权、安全和可维护性，再降低端到端 Token，最后比较速度。
- AST 以迁移时冻结并由 `srcq` 继承的 sgy 可观察行为为兼容基线；rg/fd 与后续 backend 不得把 AST 迁入另一套命令、profile、cache 或 process 设计。
- 每个 backend 先闭环一条真实命令、结果与 oracle，再扩展完整命令矩阵。
- 只抽取已证明相同的内部职责；公共抽象导致 AST 行为变化或 backend 语义丢失时立即回退设计。
- 受影响模块先做定向验证；公共协议、发布合同或正式分发范围改变时才扩大。
- 历史结果按 [benchmark-protocol.md](benchmark-protocol.md) 的身份边界冻结复用；不能证明同一 experiment identity 时只作为现实依据，不拼接为新对照。
- 正式产品与唯一命令为 Source Query Gateway / `srcq.exe`；`sgy` 只是迁移前实现和历史证据名称，安装发布前原子迁移且不保留兼容别名。
- srcq 作为独立 Windows CLI 只安装一份；先验证安装态并让消费者改用 PATH 入口，再退出 skill 内置运行时，不保留双版本 fallback。
- LSP 完整工具注册表可作为协议真源，但不能因此全量常驻模型上下文；当前保持渐进发现，只有 Codex 原生延迟发现不再成立时才重开 `srcq lsp` 只读降级路线。
- 优化对象是模型取得充分证据并形成可靠结论的完整决策链，不是单条 stdout、单次调用或局部预算；减少回合不得以丢失范围、位置、完整性、失败语义或最终限定为代价。
- 一次只改变一个有直接证据支持的机制，先过质量门禁，再比较总 Token 与价格系数，前两者不退化时才比较速度；低成本但质量、隔离或身份无效的运行不得成为数值目标。
- 常驻规则只表达稳定的职责、升级和停止边界，不固化命令配方；问题应在实际 owner 修正，只有跨任务重复且可归纳的机制才进入长期公共规则。

## 3. 现实依据

### 3.1 局部工具路径只证明机制

同一真实 TypeScript 文件上的三次重复观察显示，精确 AST 投影在 warm 或同文件复用时能减少模型可见 Token，但冷启动更贵且更慢：

| 场景 | 路径 | 含首次 skill 的 Token | warm Token | 中位耗时 |
| --- | --- | ---: | ---: | ---: |
| 单个 76 行方法 | rg 定位 + 固定后读 | 2,550 | 1,238 | 191.28 ms |
| 单个 76 行方法 | rg 定位 + sgy containing | 5,843 | 1,148 | 418.58 ms |
| 同文件三个方法 | rg 定位 + 三次固定后读 | 4,529 | 3,217 | 204.44 ms |
| 同文件三个方法 | 一次 cache + 三次 sgy containing | 7,157 | 2,462 | 548.24 ms |

这组数据支持“按任务形状动态选择”，不证明 AST 或包装器总体更省。局部输出和首次 skill 估算只用于解释机制，不能代替真实 Codex 总 Token。

### 3.2 首轮真实 Codex A/B

2026-08-14 使用六类只读源码查找任务、每环境每项两次、A-B-B-A 顺序，固定 `gpt-5.6-sol`、`medium` reasoning、`default` service tier 和 `project_doc_max_bytes=65536`。独立审计复算 24 个 `turn.completed.usage` 后得到：

| 指标 | 当时安装态 | 首轮候选 | 候选变化 |
| --- | ---: | ---: | ---: |
| Input Token | 1,751,898 | 2,178,931 | +24.4% |
| cached input（Input 子集） | 1,443,328 | 1,754,624 | +21.6% |
| Output Token | 13,324 | 14,612 | +9.7% |
| reasoning output（Output 子集） | 5,043 | 4,605 | -8.7% |
| 实际总 Token | **1,765,222** | **2,193,543** | **+24.264%** |
| 总耗时 | 835.899 s | 777.845 s | -6.945% |
| shell/MCP 调用 | 56 | 63 | +7 |

严格语义质量两边均为 11/12，核心语义均为 12/12；候选虽然更快，却以更多 Token 换取速度，不满足本分支优先级。增量主要来自额外 skill、失败回退和无增量工具回合，不是 reasoning output。

### 3.3 收紧后的候选与五-skill 消融

第二轮保持模型、配置、项目、其他 skill、插件、MCP 和底层工具相同，只从消融环境移除 `rg-token-safe`、`fd-usage`、`ast-grep-token-safe`、`symbol-structure-workflow` 与 `powershell-usage`，继续使用六类任务、两次重复和 A-B-B-A：

| 指标 | 收紧后的候选 | 五-skill 消融 | 候选变化 |
| --- | ---: | ---: | ---: |
| Input Token | 1,372,957 | 1,149,926 | +19.4% |
| cached input（Input 子集） | 1,046,016 | 802,816 | +30.3% |
| Output Token | 10,057 | 7,185 | +40.0% |
| reasoning output（Output 子集） | 3,717 | 2,692 | +38.1% |
| 实际总 Token | **1,383,014** | **1,157,111** | **+19.5%** |
| 总耗时 | 582.805 s | 508.509 s | +14.6% |
| shell/MCP 调用 | 40 | 29 | +11 |

核心语义两边均为 12/12，保守严格口径均为 11/12。六项中五项候选更贵，只有 C++ 完整函数边界任务比消融低 16.5%，说明结构化能力有条件收益，但五个 skill 的固定加载与额外回合尚未被多数任务抵消。完全裸 Codex 的 1,082,040 Token 同时移除了其他规则、skill 和配置，只是理论下界，不作为主对照。

### 3.4 历史收敛实验与已撤销裁决

候选只运行受影响环境，每轮都固定同一语料、模型、推理深度、工具版本和冻结 control home，并保留完整失败与独立审计。下表中的严格结果包含语义与格式；低成本不能覆盖质量下降。

| 候选 | 实际总 Token | 耗时 | 工具/失败 | 核心 | 严格整体 | 裁决 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| v6：全局显式点名 skill、AST 协议不足 | 2,042,093 | 657.213 s | 58 / 7 | 12/12 | 10/12 | 退出：固定加载与 AST 试错 |
| v7：已知实现降回文本，但 selector 仍宽 | 1,833,415 | 595.602 s | 53 / 7 | 11/12 | 9/12 | 退出：Pak 副本与 AST 零结果 |
| v8：高级协议才触发 skill | 1,021,894 | 386.693 s | 26 / 0 | 11/12 | 10/12 | 退出：成本最低但正式范围不完整 |
| v9：强化权威源码根 | 1,131,369 | 423.106 s | 30 / 1 | 12/12 | 9/12 | 收紧：关系端点与行数格式不稳 |
| v10：回答约束仍埋在长路由末尾 | 1,081,530 | 401.757 s | 26 / 0 | 12/12 | 9/12 | 收紧：规则显著性不足 |
| v11：拆分查询与回答规则 | **1,146,601** | **404.603 s** | **31 / 0** | **12/12** | **11/12** | 保留：质量不低于历史且成本更低 |

冻结五-skill 消融记录为 `1,157,111` Token、`508.509 s`、核心 12/12、严格整体 11/12。v11 曾方向性减少 `10,510` Token（`0.91%`）和 `103.906 s`（`20.43%`）；历史 identity 不完整且用户要求不重跑，因此该差额不作严格因果声明。v8/v10 虽更低成本，但违反质量优先顺序，不采用。稀疏回执、语义投影、按需 snapshot 和版本真源随后发生变化，v11 不再是当前候选身份，“已达收益边缘”的裁决已经撤销。

candidate-only 全量运行的 11 次完整 usage、一次 TLS 超时和关系 case 补测继续作为历史机制证据。它们推动 corpus 显式区分 prompt 必答内容与 supporting oracle facts，但不参与当前相对收益聚合。

### 3.5 P8 同身份完成对照

用户允许后，从同一当前安装态构建 control/candidate，只让全局查询路由、旧查询 skills 退出、正式查询 skills 与 candidate 私有 `srcq.exe` 构成本次迁移差异。corpus `2026-08-15.3` 的六类任务各运行两次 A-B-B-A，共 24 次新鲜隔离 Codex；全部正常退出且 usage 完整。独立审计结果如下：

| 指标 | control | candidate | 候选变化 |
| --- | ---: | ---: | ---: |
| 实际总 Token | 6,115,095 | 4,208,028 | -31.186% |
| 总耗时 | 1,174,966 ms | 938,489 ms | -20.126% |
| 工具调用 | 268 | 167 | -101 |
| 必需/核心语义 | 24/24 | 24/24 | 持平 |

六个 case 的两次聚合均同时降低 Token 与耗时，因此按质量、Token、速度顺序保留候选。单对仍受运行波动影响，不把 31.186% 外推到其他身份，也不为追逐单次波动继续增加规则或针对语料调优。

### 3.6 P9 前直觉入口身份的反向结果

2026-08-16 在同一 `gpt-5.6-sol`、medium reasoning、default service tier、full access 和冻结 identity 下完成 24 次 A-B-B-A。candidate 必需/核心语义为 12/12，control 为 11/12；但 subject Token 从 `1,526,268` 增至 `2,845,522`（`+86.437%`），同 tier 耗时从 `504,290 ms` 增至 `830,366 ms`（`+64.660%`），工具调用从 75 增至 126。12 对中 10 对 candidate Token 更高；35 个 candidate 非零工具退出中，17 个为 rg 15.2.0 被精确版本门禁拒绝，另有普通文件入口猜测和已知函数上的 AST 无匹配试探。输入增量 `1,306,000` 远高于输出增量 `13,254`，证明当前首要问题是失败回合与上下文重放，不是继续压缩正常结果正文。

该结果不推翻已完成的自适应 renderer、分页或三输出面；它推翻“当前候选可直接进入采纳”的判断。用户已经裁决后端版本不得形成运行限制，并继续选择外部适配；P9 先修正兼容准入、最小语法和 AST 升级边界，机制不变时不重跑。

### 3.7 对本计划的约束

- 统一包装必须减少完整模型路径，而不只是缩短 stdout；固定 skill 成本、失败和回退全部计入。
- 简单文件/文本任务必须保留低固定成本路径；结构和 LSP 只在改变质量或能由复用抵消成本时升级。
- 后端精确版本只标识测试证据，不形成运行许可；兼容由本次命令的实际能力、退出和输出合同裁决。
- 常驻规则必须给出 `srcq fd` 与 `srcq rg` 两个普通入口的最小语法，不用一次 help、doctor 或 skill 加载换取省下的少量规则 Token。
- “完整定义”不触发 AST；只有文本定位和有界读取仍不能充分证明边界或关系时升级，无新语法证据不得连续试探 pattern。
- 不用首轮安装态、第二轮候选和消融之间的跨快照差额推导单一机制因果；它们只限定当前改进方向。
- 新候选必须通过 [benchmark-protocol.md](benchmark-protocol.md) 的隔离、监控和独立审计流程；旧数据不因缺少完整 identity 被伪装成可逐字复现实验。

### 3.8 2026-08-16 P10 实践证据与总体计划复核

本节保存 2026-08-16 完成的 P10 实践所形成的可复用证据；逐调用事实、候选身份和审计结果仍以 [round-trip-audit-p10.md](evidence/round-trip-audit-p10.md)、各版 [iteration audit](evidence/) 与 [completion-audit-p10.md](evidence/completion-audit-p10.md) 为证据真源，本计划不复制原始运行日志。

| 实践阶段 | 直接观察 | 计划裁决 |
| --- | --- | --- |
| P9 同质量基线 | 12/12 质量，`1,150,528` Token，48 次命令，`363.163 s` | 作为 P10 当时最近的同质量参照，不把更早的跨身份记录当硬门槛 |
| v1—v3 | Token 从 `748,591` 降至 `542,658`，但 required 最多 5/6，且 v3 存在定位、快照与 benchmark 污染 | 低 Token 不覆盖质量或实验有效性；无效低成本样本不得成为目标 |
| v4—v5 | 细化同次调用、全部锚点等命令配方后升至 `720,707` Token；8192 默认预算与宽触发后升至 `823,177` Token | 删除微观操作配方和高默认预算；固定加载、预读与失败回合必须计入总成本 |
| v7—v8 | 同一 2048 总预算内的闭环和收窄触发降低误触发；一条职责链把 v8 降至 `556,677` Token，但范围和最终限定仍失败 | 保留简洁决策边界，不以输出压缩替代证据完整性和答案限定 |
| v19—v20 | v19 完整运行 `1,340,388` Token、51 次命令；命令链证明纯只读定位误用了项目“修改前读 README”规则。修正该 owner 后，相同受影响六次由 `778,895` 降至 `528,450` Token、20 次命令，且不再读取根 README | 先按可观察命令链区分项目规则、候选规则、工具能力和模型选择；在真实 owner 修正，不向全局规则或工具添加补偿特例 |
| v21 完整验收 | 12/12 required、行限与 evidence complete，45 次命令无失败，`1,066,470` Token、`480.739 s`；相对 P9 Token `-7.31%`、命令 `-6.25%`、耗时 `+32.38%` | 按质量、Token、速度顺序采纳；只声明质量与 Token 改善，不声明速度改善 |

这次实践验证了三项职责修正：`srcq` 只在既有 2048 总预算内机械返回可证明完整的有界结果；全局路由只负责权威范围、已知文件直读、按证据缺口升级 AST/LSP 和停止；最近项目规则只约束其实际适用动作，纯只读定位不得被“修改前”规则扩大。错误 oracle 也必须先修正，不能把符合实现的结果归为产品失败。

总体计划复核结论：根本需求、用户设计和三层 owner 划分仍成立，P0—P10 已完成，不因本次总结创建 P11 或新的运行入口。后续比较使用“最近的、同质量、同环境且 identity 可比”的已验证结果；五-skill 消融和早期运行只作方向性背景。只有出现新的适用失败、后端或协议变化、新消费者，或跨任务可重复且现有 owner 无法提供必要证据的共享机制时才重开；单次波动、局部 stdout 更短或仅能降低某个 case 的技巧不足以重开。

### 3.9 2026-09-01 代码读取交互轮次机制复核

[Token 机制与优化线索审计](evidence/code-reading-token-clues-v1.md)把最终 TypeScript 探针与早先 C++/TypeScript 配对的 command 链、一次性工具正文和聚合 usage 对账。三个 case 都出现 candidate 工具正文更少而 input 更高；最终 TypeScript 中 command `2→6`、一次性工具正文 `18,225→8,450` Token，但实际总 Token `74,114→150,278`。skill 正文只解释约 2.735% 的增量，更多成本随额外模型交互轮次产生；由于事件流没有逐采样 usage，这只证明当前身份中的结构性机制，不形成“每次调用固定增加多少 Token”的通用系数。

后续候选先裁决能否减少完整模型决策链：已知文件、锚点和有界范围可实验一次批取；skill、symbol、AST 或 LSP 只有能替代后续查询、正文读取、失败或回退时才可能取得净收益；任务内 `--help` 应由稳定的最小语法或正式模板消除。一次性 stdout、command 数和 skill 字节只解释机制，采纳仍逐 case 先过完整质量，再比较 aggregate usage 的 ordinary/cached/output 分项与短、长价格场景，最后才看速度。本节不重开已关闭阶段，也不授权新增 runner 或工具入口。

前三次单 case 配对进一步限定该原则，结构化结果见 [第一轮交互审计](evidence/audit-result-interaction-rounds-v1.json)：静态单阶段规则没有减少 command；静态两阶段规则在 `srcq` 默认 80 单元页上扩成 6 次续页与其他补查，工具正文更少但价格近乎翻倍；显式 `--limit 1000` 与 `--model-token-budget 12000` 能机械消除分页，但 candidate 仍有 argv 错形和 required 缺项。这些结果把“交互轮次”保留为强成本机制而非单指标，并把目标正文量、ordinary/cache/output、失败恢复纳入同一决策链。

按停止条件重开后，先通过 `v12`/`v13` 向前校准题面与 required，再加入不合并明确枚举项的通用回答闭环和 srcq 最小语法澄清；完整身份与 detached 结果见 [第二轮交互审计](evidence/audit-result-interaction-rounds-v2.json)。TypeScript、C++ candidate 分别达到 6/6、7/7 required 且短长价格均下降，C++ 速度变慢但合同允许；扩到 `v14` C# 后 candidate 达到 8/8 且无失败命令，短/长价格却由 `40342.0/74072.0` 升至 `57144.8/107179.6`，成为停止反例。raw command 在三个 candidate 中都增加，进一步证明它不能替代 sampling 或价格证据。

`srcq 0.7.0` 对相同 TypeScript 大页 argv 的无模型探针已完整返回且无续页标记；自动删除重复 backend 又会与合法原生搜索 pattern 歧义，因此本轮不改工具。当前继续保持正式 `global/AGENTS.md`、`source-query` skill 与生产读取策略不变，只保留新 corpus 和审计证据。只有出现能解释并消除 C# 价格反例的新机制或 runner 取得逐请求 usage 时才以新 identity 重开，不重采样现有输入期待不同结果。

### 3.10 2026-09-02 完整 Control 校准

用户随后确认 Control 不是缩减因果 skill 集，而是当前 Codex 完整 `AGENTS.md` 链和 skill 环境；测试项是在该 Control 上的唯一变化。benchmark preparer 因此新增 `current-control`：冻结全部安装 skills 与当前启用插件，以当前 Codex CLI 完成插件安装读回，再克隆 Candidate，并把共享插件快照纳入环境哈希。旧实验因 Control 身份不足统一降为参考，不据其数值采纳新策略。

固定的 C#、C++ 与 TypeScript 三道题均在最终完整 Control 上各运行两次，required 分别为 `7/8、7/8`、`7/7、6/7`、`6/6、6/6`，总计 `39/42`。C# 两次共同遗漏排序语义，C++ 第二次遗漏一个定义行，TypeScript 两次完整；C# 与 TypeScript 的两次查询路线分别在裸 `rg` 与 `srcq` 间切换，C++ 第二次还有一次错误 argv 后恢复。六次正式运行合计 `856,159` Token、`342.504 s`，短/长价格边界 `$0.06058192—$0.11398244`，证明完整 Control 本身质量与路径均不稳定。

前置诊断同时发现 v14 漏记真实 `Test:58 -> Read` 调用、旧环境树漏算插件安装 cache，均已由 v15 与 runner 向前修正。此前以首个 C# 失败截断整个 Control 是错误的阶段裁决，已由完整 v3 审计替代；后续测试项必须克隆完整 Control，并在同一三题各两次合同下重新运行 Candidate 后比较，不得把 Control 自身波动归因给测试项，也不修改生产规则、skill 或 srcq 来迎合单次结果。

## 4. 阶段与任务

### P0 固定分支合同和 AST 基线

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| TSQG-001 | 审核根本需求、用户设计与模型设计中的接口未决项 | — | 经用户确认的分支合同 | 根目标保持“质量 → 总 Token → 速度”；统一包装、完整兼容、fd tree 与 AST 基线只作为服务该目标的设计约束 |
| TSQG-002 | 冻结 rg/fd/ast-grep 精确版本、help/schema 与真实行为 oracle | TSQG-001 | 三个 backend 的命令清单和原生语料 | 每个公开模式有唯一 ID、原生 argv、退出与输出分类 |
| TSQG-003 | 冻结当前 sgy AST 可观察合同 | TSQG-002 | CLI/schema/cache/process/rewrite/TTY/LSP/release 基线 | 当前定向、集成和真实引擎用例可重复，结果或结构等价边界明确 |
| TSQG-004 | 登记历史 Token 基线及其身份和证据上限 | TSQG-001 | 只读历史结果索引、审计 hash 与不可直接比较边界 | 数值可从原始 usage 复算；未记录源码快照和环境混杂明确可见 |
| TSQG-005 | 从 `benchmark-corpus-seed.json` 生成绑定只读源码快照的正式 corpus 与结构化语义 oracle | TSQG-004 | corpus/schema、工作区角色、快照绑定和 oracle fixtures | 六个旧 prompt 可追溯；逐项复核历史事实，不再用词面正则替代关系，源码变化产生新版本 |
| TSQG-006 | 在 `development/code-search-benchmark` 内扩展隔离 runner/monitor 和 audit capsule owner | TSQG-005 | 仅项目可用的环境构建、allowlist diff、平衡调度、事件归档、汇总和 detached capsule | 新鲜 agent、只读快照、完整 usage、超时失败保留、角色单向隔离均有定向测试；Plugin/DirectCompatibility payload 清单中无 benchmark 资产 |

P0 闭环：能逐项回答要兼容什么、AST 什么不能改变、原生事实是什么、如何证明没有漏模式，并能通过唯一入口重复运行受监控隔离 agent、复算总 Token 和独立审计质量。

### P1 在不改变 AST 的前提下建立公共内核

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| TSQG-010 | 识别 sgy 内部可真正跨 backend 复用的进程、spool、meta、退出、预算与 artifact 职责 | TSQG-003 | 候选公共边界和不应抽取清单 | 每项都有相同生命周期/失败语义证据，不能证明的留在 AST 内 |
| TSQG-011 | 提取内部执行原语并保持 AST serializer、cache 和命令层不变 | TSQG-010 | backend-neutral 内部接口 | P0 AST oracle 全部保持；公开 help/schema/exit 无非预期差异 |
| TSQG-012 | 建立 rg/fd 的 EvidenceSignature、完整性字段与 renderer 注册 | TSQG-011, TSQG-005 | 新 backend 公共语义接口 | 0/1/N/N+1、截断、转换失败和 native error 可独立表达 |
| TSQG-013 | 建立 rg/fd 的有界 spool、snapshot 和精确 cursor | TSQG-011, TSQG-012 | 查询快照与产物生命周期 | 跨页不混快照，未知 cursor 局部阻断，底层完整结果不进入模型上下文 |

P1 闭环：现有 AST 查询、缓存投影和 rewrite 行为不变，同时新 backend 已有可用而不绑死 AST 的内部承载边界。

### P2 fd 纵向闭环与完整矩阵

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| TSQG-020 | 实现 `sgy fd exec/defaults/doctor`、argv passthrough 和路径读取 | TSQG-002, TSQG-011 | fd 最小闭环 | 真实 fd 10.4.2 的文件、目录、0/1/N/N+1 和多根查询与原生 oracle 一致 |
| TSQG-021 | 实现根别名、可逆转义、trie 与 flat/tree renderer | TSQG-012, TSQG-020 | fd tree schema | Windows 路径、Unicode、空格、多根、同名目录、对象类型和 round-trip 性质测试通过 |
| TSQG-022 | 覆盖 fd 全部公开模式 | TSQG-002, TSQG-020 | fd 完整命令矩阵 | exec/batch、print0、absolute/base-directory、ignore/hidden、help/version 等均结构化或明确透传/产物 |
| TSQG-023 | 验证 fd 自适应表示 | TSQG-005, TSQG-021 | 深/宽/多根结果成本报告 | tree 只在预计 Token 更低时选中，全部路径与完整性可还原 |

P2 闭环：fd 常用发现得到更短且可逆的树，所有特殊命令仍保持原生能力，没有第二套简化查询语法。

### P3 rg 纵向闭环与完整矩阵

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| TSQG-030 | 实现 `sgy rg exec/defaults/doctor`、JSON event adapter 和文件分组 | TSQG-002, TSQG-011, TSQG-012 | rg 普通 batch 闭环 | 真实 ripgrep 15.1.0 的 fixed/regex、多 pattern、glob、上下文和 no-match 与原生 oracle 一致 |
| TSQG-031 | 实现按各 view 证据单元分页的 locations/files/grouped/summary/lossless/raw renderer | TSQG-005, TSQG-030 | rg backend schema 与 auto 规划 | files 按去重匹配文件、locations 按匹配位置、正文按事件、summary 按完整集合；长路径、长行、非 UTF-8、子匹配与文本截断状态独立 |
| TSQG-032 | 覆盖 rg 全部公开模式 | TSQG-002, TSQG-030 | rg 完整命令矩阵 | count/files/replace/passthru/pre/json/sort/help/version 与错误有真实分类，不用 option 黑名单猜测 |
| TSQG-033 | 删除 Python 回执机制依赖 | TSQG-030, TSQG-032 | rg 消费者候选差异 | 已知 argv 解析和输出前缀故障由接口结构消失，不靠新增特例规避 |

P3 闭环：rg 能完成全部位置与不存在证明，压缩重复路径且保持原生退出、完整性和特殊模式。

### P4 AST 不回退与跨 backend 收敛

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| TSQG-040 | 用 P0 oracle 复核 AST 当前公开入口 | TSQG-011, TSQG-023, TSQG-032 | AST 非回退差异报告 | `sgy exec/defaults/cache/process/schema/capabilities/doctor`、profile、TTY/LSP 与 rewrite 均无非预期变化 |
| TSQG-041 | 仅在序列化与行为等价时让 AST 复用公共内部原语 | TSQG-040 | 最小共享实现或保留独立的裁决 | 共享有证据；无法证明同责时不为减少代码强行合并 |
| TSQG-042 | 完成三命令域诊断、单一版本来源和 Windows CLI 生命周期 | TSQG-022, TSQG-032, TSQG-041 | capability/doctor、release 与安装生命周期证据 | workspace、README、metadata、helper、SBOM、manifest 与 srcq 运行时版本一致；全新安装、状态、幂等重装、可恢复升级、卸载、PATH 与新进程读回通过；缺失引擎、观察到的后端版本、输出不兼容和透传状态可区分，AST 现有诊断合同不变 |
| TSQG-043 | 将迁移前 sgy 产品身份原子迁移为 Source Query Gateway / `srcq.exe` | TSQG-042 | `tools/srcq`、`srcq.exe`、安装目录/状态、归档、包名、skill 调用、文档与证据的唯一正式身份 | 当前 sgy 行为 oracle 在新命令下等价；发布 payload、PATH 和安装状态不含 `sgy.exe` 别名、第二运行时或旧受管安装遗留 |

P4 闭环：同一 srcq 二进制在不改变已验证 sgy 行为合同的前提下完成 fd、rg 与 AST 真实任务；rg/fd 共享合适的基础设施，AST 继续使用原有设计和安全合同；正式产品身份、安装、升级、查询和卸载只剩 `srcq`，不存在 `sgy.exe` 双轨入口。

### P5 Skill、消费者与重复入口退出

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| TSQG-050 | 建立精炼的统一查询 skill 和按需 backend 引用 | TSQG-023, TSQG-033, TSQG-043 | 只调用 PATH 中 srcq.exe 的候选 skill | 简单快路径、完整性、tree、AST、LSP 边界和 PowerShell 非触发路由通过；srcq 缺失、安装身份错误或 PATH 尚未刷新时只给安装、升级或重启恢复动作 |
| TSQG-051 | 将现有 AST skill 语义原样迁入按需引用 | TSQG-050 | AST 规则等价映射 | 迁移前 sgy 命令结构、profile、cache、process、rewrite 和安全边界在 srcq 命令前缀下无丢项；独立行为证据等价 |
| TSQG-052 | 更新消费者并退出已被替代的 rg/fd wrapper、旧 skill 与内置 sgy | TSQG-050, TSQG-051 | 唯一职责与运行时方向 | 保留 AST 行为合同并统一为 srcq 命令；先验证 PATH 运行时再删除同责 Python wrapper、重复规则和 skill 内置 sgy，不存在私有 fallback 或悬空引用 |
| TSQG-053 | 更新分支内 srcq 发布与候选 payload 合同 | TSQG-052 | 独立 srcq Windows release、安装状态和不含二进制的 skill payload | 二进制 hash、源码 revision、archive、安装状态与真实运行读回一致；skill payload 不含 srcq/sgy、tests、fixtures、benchmark、runner、corpus、结果或 audit 资产，旧直接安装副本被移除 |
| TSQG-054 | 冻结 LSP 工具暴露基线和三类真实 Codex 语义查询样本 | TSQG-050 | 固定 18 工具公开定义尺寸、活动工具快照、无 LSP/单项 LSP/多阶段 LSP 对照语料 | 记录实际 Input/Output/cached Token、工具回合、耗时和质量；不以 UI 数量或序列化字符数替代端到端成本 |
| TSQG-055 | 验证并收敛 Codex 原生延迟 MCP 工具发现 | TSQG-054 | 宿主能力证据与最小 skill 路由 | 未使用 LSP 时不注入全量 Schema；单项查询不展开无关读取或修改工具；新增发现回合被总 Token 收益覆盖，质量不退化 |
| TSQG-056 | 裁决并闭环 LSP 渐进模型入口 | TSQG-055 | 通过的原生延迟 MCP 方案，或必要时的 `srcq lsp` 只读降级实现 | 原生方案达标时不新增 CLI LSP 入口；不达标时 `srcq lsp` 复用 VS Code companion、认证 IPC、协议验证和 Provider 事实，只覆盖工作区、符号信息、引用、层级和诊断读取，不迁入 rename/code action/format/command/debug 修改职责 |
| TSQG-066 | 强化 srcq 安装状态与 Codex 发布前置门禁 | TSQG-053 | 可证明的安装健康状态和真实发布前置检查 | Status 复核 manifest、受管文件、实际版本和唯一 PATH；同版本安装修复受管漂移；真实 Publish 在写入前复用 Status/doctor，测试沙箱不消费宿主安装 |

P5 闭环：查询规则只有一个低成本入口，AST 设计保持，重复的 rg/fd 包装职责退出；srcq 只由 Windows 安装器维护一份，skill 和插件不再复制运行时；安装状态可证明当前二进制与 PATH 健康，真实发布在写入前消费该前置证据；LSP 工具只在语义证据真实需要时渐进暴露，原生延迟发现达标时不为形式统一新增 `srcq lsp`，不达标时也只迁入只读查询。项目真源已经按用户后续完整实现请求采纳这些职责；实际 Codex 安装态仍须逐次发布授权。

### P6 质量、Token、速度与采纳裁决

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| TSQG-060 | 运行 backend 定向、公共契约、性质/fuzz 与真实版本矩阵 | TSQG-053, TSQG-056 | 质量验证结果 | 声称支持的版本和模式全部通过，AST 基线无回退，LSP 渐进入口未破坏 Provider 语义或授权边界 |
| TSQG-061 | 运行 detached skill 路由和行为评估 | TSQG-050, TSQG-052, TSQG-056 | 分支评估证据 | 首次路由、简单非触发、AST/LSP 边界、单项渐进发现和写入安全满足独立 oracle |
| TSQG-062 | 通过正式 monitor 运行真实 Codex 隔离对照 | TSQG-006, TSQG-060, TSQG-061 | 原始事件、环境差异、Input/cached/Output/reasoning/耗时/质量与 audit 结果 | identity 相同的历史基线直接复用；只运行受影响对照，短任务与多查询任务分别报告，失败与回退不丢弃 |
| TSQG-063 | 裁决保留、收紧或退出 | TSQG-062 | 收益边缘结论 | 质量先通过；固定成本无收益则收紧触发，压缩收益不抵成本则不宣称优化完成 |
| TSQG-065 | 逐项完成审计 | TSQG-062, TSQG-063 | 当前需求、用户设计、约束与证据边界的完成结论 | 逐项复核 24 个保护来源、当前结果、验证和未决项；不得用发布状态替代项目实现完成，也不得把项目完成当成发布授权 |
| TSQG-064 | 请求当次 Codex 发布授权 | TSQG-065 | 用户裁决 | 项目真源已实现；只有用户针对本次明确确认后才安装 PATH srcq 并增量发布，Git 按既有授权另行维护 |

P6 已对上一冻结身份闭环：供应链、独立路由、正式消费者、失败路径、oracle 边界和 24 次同身份对照均已复核；TSQG-063 当时按质量持平、Token 和耗时下降保留候选。用户随后确认“模型默认输出应只含干净、有用的工具证据”，使输出身份和验收合同发生变化；旧五-skill control 仍按要求只作历史依据，P6 数字也只作为新一轮 control 候选，不证明 P7 已完成。TSQG-064 继续只表示未来每次 Codex 发布均需单独授权。

### P7 模型可见输出收敛

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| TSQG-067 | 冻结全部输出族与字段准入合同 | — | rg/fd/AST/doctor/defaults/cache/process/artifact/error 的输出清单、使用方与模型动作映射 | 每个 model 字段能指出会改变的判断、定位、续页或恢复；无法指出则移出默认视图；machine/native 请求对象不被误删 |
| TSQG-068 | 建立共享 model/machine/native 输出边界 | TSQG-067 | 单一内部事实、payload-only model renderer、显式 machine renderer 与原生/产物通道 | 普通成功完整输出无 envelope/schema/receipt；异常仍可区分截断、分页、错误与快照，machine round-trip 和原生字节不退化 |
| TSQG-069 | 收敛 fd 与 rg 的模型投影 | TSQG-068 | fd 紧凑基数树，rg 正文/位置/文件/count 紧凑格式 | 单子链合并、根和路径不重复；结果集合、顺序、位置、类型和上下文按 EvidenceSignature 可还原；实际 renderer 成本低于适用旧视图才采用 |
| TSQG-070 | 收敛 AST 与辅助命令的模型投影 | TSQG-068 | AST payload 投影及 doctor/defaults/cache/process/artifact/error 的按需输出 | AST 正文不与重叠捕获重复，必要捕获仍可得；machine schema、cache、process、rewrite、TTY/LSP、诊断退出和 artifact 合同不退化 |
| TSQG-071 | 更新消费者与按需协议 | TSQG-069, TSQG-070 | source-query 引用、help 与迁移说明 | Skill 不要求模型解析旧 envelope；显式 machine/diagnostic 入口可发现但不常驻，旧默认格式消费者完成迁移或明确退出 |
| TSQG-072 | 运行影响范围验证与真实隔离对照 | TSQG-071 | 定向/性质/真实引擎结果与受影响 control/candidate audit | 先验收语义等价、round-trip、分页错误与 AST 非回退；只运行受输出身份影响的 corpus，质量持平后总 Token 下降，前两项不退化后耗时不恶化 |
| TSQG-073 | 完成审计与采纳裁决 | TSQG-072 | GAP-SQG-007 完成结论及发布前状态 | 全部输出族无已知低收益常驻字段，证据覆盖新 identity；未达标则收紧或退出，不以局部字符下降声称完成 |

P7 已完成 TSQG-067 至 TSQG-071，形成 model/machine/native 三输出面、干净默认正文、fd/rg/AST 与辅助命令投影及正式消费者迁移。用户检查真实输出后确认更上游的职责差距：普通调用仍要求模型预先编排 `exec`、argv 分隔、view、limit、heading 或预算，位置表示也尚未把 heading 与路径树作为统一结果后置候选。因此 TSQG-072 的旧输出 identity 对照暂停，已有原始运行只作调试输入，不进入完成裁决；TSQG-073 不启动，先进入 P8 重投影。

### P8 查询意图入口与结果后置自适应投影

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| TSQG-074 | 建立 srcq 统一接管的 rg/fd 原生直觉入口 | TSQG-071 | `srcq rg <rg argv...>`、`srcq fd <fd argv...>`、既有 srcq AST 入口与独立显式控制面 | 正式规则不再裸用 rg/fd/ast-grep；普通查询不需要 `exec`、`--`、view、limit、heading 或 receipt；原生 argv、退出和特殊模式不退化 |
| TSQG-075 | 实现真实结果后的自适应 renderer 规划 | TSQG-074 | 原生等效文本、单行、heading、分组正文、路径树、路径树位置 heading 与 machine/native 候选选择器 | 只在 EvidenceSignature 等价时按实际模型文本成本选择；裸输出无预设优先级，同文件、多文件共享目录和离散单位置分别选择最低充分结构 |
| TSQG-076 | 内化默认上下文预算与精确续页 | TSQG-075 | 无需模型预填 limit/text budget 的安全默认窗口、证据单元分页与 cursor | 短结果完整返回；大结果不拆坏证据单元，续页不混快照；显式预算仍可覆盖且资源硬上限不变 |
| TSQG-077 | 迁移消费者并冻结用户可见输出身份 | TSQG-075, TSQG-076 | 精简后的全局路由、source-query 引用、CLI 文档、裸工具与旧普通格式配方退出记录和真实输出审查 | 所有 rg/fd/ast-grep 模型查询指向 srcq；常驻规则和普通 skill 不教授 heading/tree/view/limit/receipt 配方；用户审查默认输出后冻结 identity |
| TSQG-072 | 运行新调用身份的影响验证与隔离对照 | TSQG-077 | 定向/性质/真实引擎结果与新 identity control/candidate audit | 先验收原生兼容、投影等价、分页、machine/native 与 AST 非回退；用户继续设置 Goal 后才恢复独立 Codex 测试 |
| TSQG-073 | 完成审计与采纳裁决 | TSQG-072 | GAP-SQG-007 完成结论及发布前状态 | 质量持平后总 Token 下降，前两项不退化后再比较耗时；失败和无收益样本完整保留 |

P8 按“所有底层搜索进入 srcq—调用只表达查询语义—工具取得真实结果—生成含原生等效文本在内的等价投影—选择最低充分表示—必要时精确续页”的单条纵向链推进。裸工具不是简单查询快路径，裸输出也只是内部 renderer 候选；路径树和 heading 同样不是模型必须选择的模式。显式控制只服务于调用方确实需要定向 model、machine、native 或 artifact 的场景。后端默认继续套壳调用已验证二进制；只有可重复的必要验收失败被定位到上游内部、外部适配方案已证明不足时，才暂停本链并形成源码升级建议，与用户讨论并取得该次明确同意后再按 DES-SQG-013 重投影，不预建休眠 fork 任务、提前拉取源码或以既有授权代替裁决。TSQG-072 保留原任务 ID，但其依赖和测试 identity 重投影到 TSQG-077 之后，不复用或拼接刚暂停的旧 candidate 运行。

P8 的组件与消费者实现已经形成，但首次新 identity 对照由 OBS-SQG-010 证明未达到端到端成本目标；TSQG-072 保留失败证据而不完成，进入 P9 修正最早失效机制。

### P9 版本无关兼容、最小语法与证据驱动升级

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| TSQG-078 | 以实际输出能力取代后端版本许可 | TSQG-077 | 无版本拒绝的 rg/fd/AST 执行、解析与安全降级合同 | rg 15.1/15.2、fd/AST 现有矩阵、未来版本字符串、结构变化、错误与副作用模式通过；doctor 不因版本不同失败，转换失败不伪装为空结果 |
| TSQG-079 | 固化普通查询最小语法和定向错误恢复 | TSQG-077 | 常驻 `srcq fd`/`srcq rg` 两个语法、无 skill 普通路径、CLI 一行修正 | 文件发现与文本定位无需 help/doctor/skill；错形一次获得唯一恢复，成功路径无新增元数据、别名或第二语法 |
| TSQG-080 | 把 AST/LSP 升级改为证据缺口驱动 | TSQG-077 | 精炼后的全局路由、source-query 触发与 AST 空结果恢复合同 | 唯一已知函数走文本闭环；边界不明、同名/重载、结构关系和截断场景才升级；AST 无匹配不发生无新证据重试 |
| TSQG-081 | 接入三项修正并冻结新 identity | TSQG-078, TSQG-079, TSQG-080 | 当前 srcq release 候选、正式规则/skill/文档、受影响 consumer 与 identity 清单 | 组件、真实后端、AST 基线、路由正反场景和发布 payload 影响闭合；用户审查普通成功与异常恢复输出后冻结 identity |
| TSQG-072 | 只对变化后的身份运行影响验证与隔离对照 | TSQG-081 | 新 identity 的定向结果、原始 usage 与独立 audit | 不复用失败 candidate；先质量，再总 Token，最后同 tier 耗时；按 case 报告失败、回退和配对分布 |
| TSQG-073 | 完成审计与采纳裁决 | TSQG-072 | GAP-SQG-007 完成结论及发布前状态 | 逐项复核版本无关兼容、普通低固定成本、证据驱动升级和端到端收益，未达标则继续收紧或退出 |

P9 沿三条可独立验证的根因链推进，最后只在 TSQG-081 汇合：运行时 owner 负责后端能力与安全降级，常驻规则只承担普通命令所需的最小语法，source-query skill 只承担高级证据升级。三者不互相复制决定，也不新增别名、源码 fork 或模型侧展示参数。优先完成 TSQG-078，先恢复真实 Codex 环境中的普通查询；TSQG-079 与 TSQG-080 可在不依赖其实现细节时并行设计，但冻结身份前必须共同接入并验证。

TSQG-078 至 TSQG-081 已完成版本无关执行、安全文本降级、唯一错形恢复、证据缺口升级、`srcq 0.3.1` Windows release、正式规则/skill、消费者和路由证据。TSQG-072 随后只运行变化后的 candidate，通过受影响小集合逐步消除权威源码副本污染、`srcq lsp` 猜测、隐藏行数 oracle 和普通文本任务的高级 skill 预加载，再冻结最终 identity `e32871ba9c0f8b19716e7b191260c29666939879215350baa4604d1bfd9c7ac4`。

最终六类任务各两次均通过：质量 12/12，总 Token `1,150,528`，耗时 `363.163 s`，48 次命令无失败；确定性 capsule 校验和 detached 语义审计均通过。相对未重跑的五-skill 历史记录只作方向性观察：Token `-0.57%`、耗时 `-28.58%`，当前严格质量由 11/12 提升为 12/12。剩余重复间成本波动没有共享错误或失败回退；TSQG-073 因此采纳 P9 并关闭 GAP-SQG-007。该 identity 随后已按用户逐次授权发布；P10 是新的优化周期，不回写 P9 完成结论，也不继承新的发布授权。

### P10 最小证据闭环与模型—工具轮次收敛

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| TSQG-082 | 审计高成本证据轮次并裁决最小修正层 | TSQG-073 | 三个上升任务 28 次调用的证据图、必要/可合并/重复/能力缺口分类、反事实闭环、DEC-SQG-001 裁决输入 | 数量与 Token 对账完整；每个拟合并回合证明输入当时已知、范围有界、证据等价和失败可恢复；不重跑冻结五-skill 历史，不预设新命令 |
| TSQG-083 | 接入最小证据闭环与普通首查边界 | TSQG-082 | 精炼的全局源码路由、`source-query` 触发和引用规则、受影响路由合同 | 不写入 benchmark 特例、命令配方或新入口；普通查询不预加载高级 skill/help，只有实际证据缺口才升级，所有 rg/fd/AST 仍经 srcq |
| TSQG-084 | 审计可观察决策链并运行 P10 受影响候选 | TSQG-083 | 既有运行的命令内容与因果归因、修订后的单一候选、6-run 原始 usage、工具轮次和质量审计；达标后才扩展 12-run | 先按直接证据区分项目规则、候选规则、工具能力、命令选择、实验污染与随机波动，再形成候选；先 6/6 质量，再比较 Token 和调用；没有机制变化不重跑，五-skill 与 P9 历史只读复用 |
| TSQG-085 | 完成 P10 与需求逐项审计 | TSQG-084 | GAP-SQG-008 结论、REQ/AC/CON/UDES 完成矩阵、最终发布前状态 | 每项由适用组件、真实模型、安装/发布边界或直接文档证据覆盖；未验证项不得用汇总通过代替 |

TSQG-082—TSQG-085 已闭环。28 次调用的逐项证据图和反事实下界见 [round-trip-audit-p10.md](evidence/round-trip-audit-p10.md)；v1—v21 的关键试错、直接观察与采纳边界已归纳到 [3.8](#38-2026-08-16-p10-实践证据与总体计划复核)，各候选原始事实仍由对应 iteration audit 保留。反事实下界只证明既有入口的表达能力，不证明模型能稳定、直觉且低成本地取得同等证据，也不得从总 Token 或调用数反推 owner。

最终 v21 identity `0cfb8919…59d5` 的 12-run 达到 required、行限与 evidence complete 12/12，45 次命令全部成功，总 Token `1,066,470`；detached audit、capsule 验真和 [completion audit](evidence/completion-audit-p10.md) 均通过。它相对 P9 同质量参照降低 Token，但耗时上升，因此仅按既定优先级采纳质量与 Token 收益。Codex 发布仍是独立授权动作。

#### P10 测试环境与因果归因

P10 保留真实运行所携带的目标项目 `AGENTS.md`，不为得到更好数字创建无项目规则的干净环境，也不重跑 P9 或五-skill 历史。项目规则产生的必要成本继续计入端到端总量，但它只是实验条件，不自动成为回归原因；若命令链直接证明项目规则适用边界错误，应修正该规则的项目 owner，而不是在全局规则或 `srcq` 中补偿。历史 P9 与五-skill 数据只作方向性参照，不与当前不同 identity 拼成精确因果结论。

每个既有或新增运行都按可观察决策链审计：记录调用前已经可见的事实、当时仍缺的必要事实、实际命令与参数、返回的正文/位置/截断/退出语义、下一次调用取得的新证据及最终答案。只读取真实事件中可见的模型消息、推理摘要、命令、工具结果和最终输出；不可见思维不得被补写为事实，必要推断必须标为推断。

每个调用及其 Token/时间后果只归入以下有直接证据覆盖的类别；证据不足时保留为未决，不以最像的解释代替原因：

- `project-required`：最近项目规则明确要求且对该任务实际适用；计入总成本，但不归咎当前候选。
- `project-rule-misapplied`：模型执行了项目规则并不要求的读取或动作；只有命令内容和规则适用范围能直接证明时成立。
- `candidate-rule-induced`：相同项目条件与任务输入下，变更规则可机械解释新增或消失的动作，并由配对运行或直接机制证据支持。
- `tool-capability/output`：必要后继调用由现有接口缺少定位、完整性、边界、续页或明确退出语义直接造成；“可以组合多个命令表达”不等于该类别不存在。
- `command-formulation/model-choice`：猜测不存在锚点、无依据放宽限定名、选择错误范围或窗口等当前调用选择造成，且工具已经提供所需能力。
- `benchmark-invalid`：读取 benchmark 资产、identity/环境不匹配、usage 缺失或 monitor 介入答案；不得进入采纳证据。
- `stochastic/inconclusive`：重复运行分歧且没有共享可证机制；只报告分布，不形成规则或工具改动。

归因同时标记调用是任务必要依赖、可同轮合并还是无新增证据。报告保留含项目规则在内的端到端总 Token、价格系数、耗时和质量，并另按“项目入口/政策、权威范围、源码定位、正文与行号、上游依赖、最终回答”拆分成本。拆分只帮助定位 owner，不从端到端总量中扣除成本或美化候选。

#### P10 执行顺序与采纳门槛

1. 冻结并只读复用五-skill、P9 与每个已完成 P10 identity；没有机制变化时不为期待不同结果重跑。
2. 依据真实命令、返回、后继动作和最终答案裁决 owner；工具只吸收其独占完整结果形状能机械证明的职责，规则和项目入口各自只修正适用边界。
3. 一次只形成一个可解释的最小候选；静态合同和代表性非触发先证明结构，受影响 6-run 只作机制筛选，不替代完整质量与收益验收。
4. 受影响结果必须先满足 required、行限、范围和实验隔离；出现 `benchmark-invalid`、最终限定丢失或共享新失败时停止扩大。只有候选机制变化才开启下一 identity。
5. v3 的 `542,658` 来自未通过封闭质量且含 benchmark 污染的身份，已撤销为数值门槛；无效低成本样本不能成为后续实现的硬目标。项目规则成本始终计入总量，分类只用于归属 owner。
6. 最终完整运行使用最近的同质量、同环境且 identity 可比的已验证结果为参照：P10 对应 P9 的 `1,150,528` Token；要求 required、行限与 evidence complete 全部通过、无固定失败或环境污染，并降低总 Token。速度只在质量和 Token 均不退化时参与选择；v21 达到前两级但耗时上升，按该边界采纳。
7. detached auditor 只读取指定 capsule，独立复算身份、usage、环境差异和逐案质量；完成审计还须确认没有会改变方案的共享明显改进点。当前 v21 已满足，只有新失败、协议变化、新消费者或可重复共享机制出现时重开。

任何 `inspect` 类命令仍不进入规则、skill、CLI help 或发布 payload。若详细审计证明最低充分能力确实缺失，应先修订需求、设计与 DEC-SQG-001，经职责裁决后再实现，而不是把预设结论写回工具。

### P11 scc 指标 backend 与主机工具接入

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| TSQG-086 | 冻结 scc/hyperfine 当前行为、用户合同和 owner | TSQG-085 | [P11 交付链](../../docs/work/20260819_source_metrics_and_benchmark_tooling/requirements.md)及职责设计 | 区分 scc 指标事实、srcq 输出治理、hyperfine benchmark 与 bootstrap 安装状态；不形成同责入口 |
| TSQG-087 | 实现 `srcq scc` 直接入口和高级控制面 | TSQG-086 | scc backend、稳定 machine schema、有界 model、native/artifact 与 doctor | 真实 scc 汇总/逐文件/大结果/错误/版本漂移通过；argv、退出、特殊格式和 rg/fd/AST 不退化 |
| TSQG-088 | 接入 Windows bootstrap 与部署消费者 | TSQG-086 | scc/hyperfine Check/Install、状态读回、静态部署校验和安装说明 | 精确 winget ID、缺失/过期、幂等安装、PATH 重启和发布 payload 边界通过测试 |
| TSQG-089 | 接入全局路由与 source-query 高级合同 | TSQG-087, TSQG-088 | 普通 `srcq scc`/`hyperfine` 选择、scc 按需引用及路由案例 | 普通任务不预加载 skill；高级控制能发现；静态 Routing/Policy/References 通过；本轮不启动独立 Codex |
| TSQG-090 | 完成受影响验证、release 候选和影响审计 | TSQG-087, TSQG-088, TSQG-089 | 定向/完整/真实工具/tokenizer/release/installer/部署结果与完成审计 | 无已知适用失败；独立 Codex 与真实 Publish 按用户约束保持未执行并明确证据上限 |
| TSQG-091 | 让 files 在适合时使用目录树 | TSQG-090 | 共享同行叶子路径树、scc 自适应候选、v2 tokenizer 基准与刷新 release | 可逆、保序、成本单调、分页和 machine 非回退；hotspots 保持排名；同快照真实 Token 降低 |

P11 只抽取已经由 rg/fd/scc 证明相同的执行、预算、快照和输出职责；scc 参数分类、指标记录和投影保留 backend 语义。hyperfine 不进入 srcq，也不成为完成裁判。用户明确限制当前单 turn 不运行独立 Codex，因此 TSQG-090 的本轮闭环只覆盖确定性与真实本地运行，后继模型采纳验证不得被静态证据替代。

P11 实施状态（2026-08-19）：TSQG-086 至 TSQG-090 的项目源码、消费者接入、release 和确定性验证均已完成，没有开放实施任务。独立路由 evidence 因当轮额度约束保持旧 bundle，正式 Validate 正确拒绝；真实 srcq 安装升级与 Codex Publish 也未获当次授权。这三项属于后继证据或外部状态转换，不以未完成源码掩盖，也不由 P11 自动授权。

P11 重开与再次闭合（2026-08-20）：真实 tokenizer 证明 files 扁平投影仍重复目录和字段名，满足重开条件。TSQG-091 已让同一规范化证据页按成本选择扁平标注、扁平表或可逆目录树，hotspots 和机器合同不变；workspace、真实 scc、同快照 tokenizer、可复现 release、backend smoke 与隔离升级均通过。当前路由 evidence 已由后继计划刷新且本次输入未变；真实安装升级继续暂停，未执行 Codex Publish，当前没有开放实施任务。

### P12 独立 Codex 评估运行时与 scc 续页观察

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| TSQG-092 | 裁决独立评估的网络、transport、sandbox 与真实工具边界 | TSQG-091 | [P12 交付链](../../docs/work/20260820_independent_codex_evaluation_runtime/requirements.md)、根因与 owner | 区分 runner 缺陷与 srcq 产品行为；不复制 `.env`、不修改真实 Codex 配置、不以 HTTP fallback 伪装网络健康 |
| TSQG-093 | 实现可审计且低重复的 evaluator runtime | TSQG-092 | experiment v3、脱敏网络投影、显式 transport、candidate-only 预检、真实 scc doctor、网络/runner 身份门禁 | 36 项 benchmark 测试、10 项 home 测试、Python 编译、失败迭代和最终零重连 preflight 通过 |
| TSQG-094 | 在修复后的边界验证正常同 turn scc 续页 | TSQG-093 | v5 identity、事件级命令链与负向友善度结论 | WebSocket + remote DNS + proxy fanout；preflight/subject 零 retry/fallback；第一页成功，第二条错误 `srcq scc --after` 直接可见 |

P12 的 runner 工作已经闭合，最终 experiment identity 为 `a37e3675d74dfca877f84fbccfc9814ff37cacc56fd796263c1335a3d31dc939`。它没有证明分页友善：第一页 `@more shown=80 omitted=97 after=<cursor>` 未提供可直接执行的续页入口，独立 Codex 把 cursor 传给直接 scc backend，原生 scc 以未知 `--after` 拒绝。该事实满足模型投影质量重开条件，但本轮只获评估框架修复授权；srcq 产品修正保持待用户裁决，不预建实现、不修改 release，也不继承 Publish 授权。

### P13 query model 可执行续页动作

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| TSQG-095 | 冻结 cursor + 完整 `@next` 用户合同与唯一 owner | TSQG-094 | [P13 交付链](../../docs/work/20260820_srcq_model_pagination_action/requirements.md)、AC-SQG-009、UDES-SQG-015、DES-SQG-015 | `@more` 只表达数量，`@next` 是 PowerShell 7 可执行完整命令；machine、cache/process 与 snapshot 状态不变 |
| TSQG-096 | 实现命令投影并迁移当前消费者 | TSQG-095 | 公共 query renderer、PowerShell argv 格式器、source-query 文档/静态合同和 0.4.1 候选 | rg/fd/scc 共享行为；特殊 argv 单行无损；续页沿 snapshot 且原生 scc 只扫描一次 |
| TSQG-097 | 运行有效独立 Codex 正常续页 | TSQG-096 | candidate-only experiment、事件级第二页命令与友善度结论 | preflight/subject 零网络降级、postflight 有效；模型执行 `@next`，第二页成功且 cursor/argv/扫描次数正确 |
| TSQG-098 | 完成消费者、验证与发布边界审计 | TSQG-097 | GAP-SQG-009 结论、P13 验证和项目状态 | 组件、skill、evaluator 与 Git 闭合；真实安装保持暂停，未获逐次授权不 Publish |

P13 只扩展现有 query model renderer，不增加 `srcq more`、offset/length、原生重扫或模型侧命令重建。若有效独立事件仍选择错误入口，先按实际可见输出裁决信息层级、命令歧义或 shell 表达机制；只有机制变化后才重跑，不用相同输入期待随机成功。

TSQG-095—TSQG-098 已闭环。`srcq 0.4.1` 的特殊 argv PowerShell 往返、snapshot fingerprint 与单次 scc 扫描回归通过；全 workspace build/test/lint/fmt、skill 静态合同、零模型 Token 路由基础设施和部署 Validate 通过。v6 identity `27ac16be…20f5` 中，独立 Codex 直接执行 `@next` 并成功取得第二页，preflight/subject 网络计数全零、postflight 无漂移，capsule `fce108b5…7926` 验真通过。GAP-SQG-009 因此关闭；真实 srcq 安装仍按用户要求暂停，本轮没有 Publish 授权也未执行 Publish。

### P14 query model 短句柄续页

2026-08-22 的真实使用反例满足 P13 的模型动作质量重开条件：完整命令虽然可执行，仍要求模型复制 32 位 snapshot cursor、控制面和全部原生 argv。用户确认改用短句柄，并针对本周期授权实现、正式 srcq release/安装与 Codex Publish；P13 历史证据保留，当前交付链仍在同一 [分页动作工作区](../../docs/work/20260820_srcq_model_pagination_action/requirements.md) 修订受保护目标。

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| TSQG-099 | 重裁模型续页 owner、machine 兼容与生命周期 | TSQG-098 | 短句柄需求、不可变 registry、并发/过期边界 | `@next` 只暴露 `srcq more q<number>`；无参数 last-query、offset/length 和 machine cursor 变更均排除 |
| TSQG-100 | 实现根级 more 与同 owner 原子状态 | TSQG-099 | 0.4.2 候选、进程间 spool lock、128 条有界句柄记录 | scc 纵向路径恢复特殊 argv并保持一次扫描；八进程句柄唯一；损坏/缺失拒绝且不启动后端 |
| TSQG-101 | 迁移模型交互面、skill 与全部确定性消费者 | TSQG-100 | srcq 文档、source-query 合同、路由静态检查与 workspace 证据 | rg/fd/scc model、machine cursor、snapshot、cache/process、release/安装合同均无回退 |
| TSQG-102 | 发布、安装、Codex Publish 与 Git 收口 | TSQG-101 | 私有 GitHub Release、真实安装读回、DirectCompatibility 发布和完成审计 | release checklist、下载/升级/doctor、路由 evidence、部署 Status、非强制远端同步全部有直接证据 |

P14 以 TSQG-100 的 scc 首屏—续页—单次扫描作为首个真实消费者；该路径成立后才扩到并发、全 workspace、release 与部署。句柄按十进制单调增长而不固定填充六位；受管保留周期内不复用，过期只返回重跑原查询，不误指其他 snapshot 或隐式重扫。

TSQG-099—TSQG-102 已闭环。`srcq 0.4.2` 以 revision `ef65946f…9c04` 生成两份 SHA-256 相同的 clean Windows archive，并经私有 GitHub Release 安装到真实 PATH；Status、AST/scc doctor 与已安装短句柄续页通过。source-query 路由合同、36 项 query gateway、workspace build/test/lint/fmt 和 release gates 通过；正式部署还暴露并修正了 Windows SWE 预检仍解析旧 `--after` 长命令的真实消费者缺口，聚焦测试后 Validate/Publish 各 67 项通过。DirectCompatibility + InstallPortableSettings 发布后 gap 为 0，P14 不再保留开放仓库实施项。

### P15 query model 六位循环句柄

2026-08-23 的实际 spool 复核满足 P14 的短句柄误用重开条件：记录和 snapshot 已分别有界为 128 条与 32 份，旧记录会淘汰，但可见编号仍跨任务单调增长。用户明确句柄不是持久引用，要求新编号最多六位并在上限后循环，不为淘汰记录永久保存历史身份。

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| TSQG-103 | 修订临时句柄生命周期与兼容边界 | TSQG-102 | REQ-002、AC-004/005、CON-004 与同 owner 环形设计 | `q1`—`q999999` 不补零；活动记录不覆盖；旧七位记录只读过渡；不增加永久 counter、tombstone 或第二状态源 |
| TSQG-104 | 实现六位环形分配和环形年龄淘汰 | TSQG-103 | 0.4.3 候选、回卷/窗口/旧记录单元测试 | `q999999` 后生成 `q1`；新 `q1` 保留、最旧高位记录淘汰、下一编号为 `q2`；既有并发、快照、argv 和 machine 合同不退化 |
| TSQG-105 | 完成组件验证、release、安装和 Codex 发布 | TSQG-104 | 私有 0.4.3 Release、真实 Upgrade/doctor、source-query 临时游标指引、DirectCompatibility 发布和完成审计 | release checklist、路由/部署合同、已安装真实续页、Status 与非强制远端同步均有直接证据 |

P15 不改变 `srcq more q<number>`、machine cursor、snapshot schema、记录 payload 或 cache/process 分页。现存记录的文件集合仍是分配与淘汰唯一状态；新编号持锁环形查找空闲值，写入后以该值为原点按环形年龄删除最旧记录。七位以上句柄只作为 0.4.2 升级兼容输入保留，在后续写入中优先自然淘汰。

TSQG-103—TSQG-105 已闭环。0.4.3 候选与完整组件门禁覆盖六位环形句柄；全量性质测试同时发现并闭合 YAML emitter 的独立真实反例。revision `f4e3570…5087` 的两次 clean archive SHA-256 相同，私有 `srcq-v0.4.3` Release、真实 Upgrade/doctor、已安装 `q921 → q922` 续页、路由 evidence、DirectCompatibility Publish 与发布后 Status 均通过，P15 不再保留开放仓库实施项。

### P16 低延迟多语言源码关系

用户要求新增一组内部组合 rg 与 AST 的定义、引用和有界调用树工具，覆盖变量、函数等实际符号种类，并尽可能覆盖 ast-grep 已适配语言。[P16 分析](evidence/analysis-p16-fast-symbol-relations.md) 已证明 C++ 代表闭环具备速度收益，同时证明不同语言的函数、调用和局部变量 AST 节点没有统一合同；GptProjectTest 的编译数据库、嵌套响应文件和 UE 外部源码根还证明当前目录或单一 workspace 不能定义完整查询范围。P16 因而沿用 Source Query Gateway 现有 owner，但不能复用 C++/UE 特例、把语法候选称为精确 LSP 结果，或以无界外部目录扫描掩盖源码宇宙未解析。

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| TSQG-106 | 冻结位置身份、关系证据等级和语言 capability 合同 | DEC-SQG-001, DES-SQG-016, DES-SQG-017 | P16 已确认设计、命令候选与 machine/model 语义 | 名称歧义、局部遮蔽、无调用概念、未适配和解析失败均有不同结果；扫描完整不提升为身份完整 |
| TSQG-107 | 以外部 rg + ast-grep outline/run 完成多语言适配探针 | TSQG-106, DES-SQG-013 | 适配器协议、外部能力/版本降级证据和不应共享的语法机制 | C++、Python、TypeScript、Rust、Go、Java 覆盖六类已证节点差异；其余语言按独立 grammar/capability 机制扩展，不机械复制完整矩阵 |
| TSQG-112 | 实现跨 workspace 的 SourceUniverse、默认范围与显式目录组合 | TSQG-106, DES-SQG-019, DES-SQG-020 | anchor/cwd 默认 resolver，auto/augment/exact/exclude 组合，workspace 多根、compile database/response file 与语言依赖 resolver；可重建根缓存和范围诊断 | 不填目录即可在普通项目和无元数据目录完成查询；显式追加/替换/排除语义稳定；GptProjectTest 从项目编译项恢复 UE 外部源码根；嵌套/缺失/循环/陈旧响应文件、无源码依赖和重复库版本可区分；不扫描整盘或默认启动构建系统 |
| TSQG-108 | 实现首个位置到定义、引用与深度调用树的正式纵向消费者 | TSQG-107, TSQG-112 | `srcq` 候选命令、稳定图模型和 UAI C++ 真实结果 | 同一 UAI 符号跨项目与 UE 源码根完成定义、引用、outgoing/incoming 和深度展开；虚调用反例返回 unknown；候选与 LSP 可比部分一致且快速路径显著更快 |
| TSQG-109 | 扩展全部 ast-grep 内置语言的显式 capability 与适用适配 | TSQG-108 | 语言注册表、适配规则和逐语言最小 smoke | 每种内置语言均为 supported、candidate-only、not-applicable 或明确失败；函数/变量/类型等按适用能力验证，不用空集合掩盖缺口 |
| TSQG-110 | 接入模型投影、续页、source-query 路由与精确语义升级 | TSQG-109 | model/machine 输出、短句柄续页、skill 消费和 LSP 后备边界 | 普通模型不手工串底层命令；歧义才升级；树、引用和候选可渐进恢复且不复制 Provider 决策 |
| TSQG-111 | 完成组件、语言机制、真实消费者与发布边界验证 | TSQG-110 | P16 验证、版本与完成审计 | 先定向后公共合同验证；候选稳定前不跑完整发布验证；未获当次明确同意不制作正式 Codex Publish |
| TSQG-113 | 建立共享 typed relation 骨架并闭合 TypeScript 首个消费者 | TSQG-109, TSQG-112, DES-SQG-021, SOL-SQG-017 | 共享调用/绑定/scope 中间表示、TypeScript adapter、正反例 fixture | 显式类型或构造证据收窄同名 outgoing/incoming；块越界、冲突和复杂动态形式保持 unknown；C++/C# 不退化 |
| TSQG-114 | 完成 JavaScript/TypeScript 项目与语言差异适配 | TSQG-113 | TS/TSX/JS callable owner、构造与当前类型候选、tsconfig/jsconfig/package 本地范围 resolver | 两语言分别有类型或构造收窄正例、动态属性反例和本地 project/reference 范围正反例；不启动 TypeScript/Node 服务 |
| TSQG-115 | 完成 Python 语言与项目适配 | TSQG-113 | annotation/构造/self/cls/callable adapter、pyproject/package source resolver | 参数/局部/成员类型正例与动态属性/装饰器或 monkey-patch 反例分离；本地源码范围可恢复，运行时 import 保持 incomplete |
| TSQG-116 | 完成 Go 语言与 module/workspace 适配 | TSQG-113 | 参数/局部/字段/receiver/复合字面量 adapter、go.mod/go.work 本地 resolver | 直接与 typed member 候选按 package/type 收窄；interface、build tag、generate 和未解析依赖保持 unknown/incomplete |
| TSQG-117 | 完成 Rust 语言与 workspace/module 适配 | TSQG-113 | 参数/局部/self/impl/路径调用 adapter、Cargo workspace/path dependency resolver | inherent impl 与显式类型候选收窄；trait object、宏、closure/function value 和生成源码保持 unknown/incomplete |
| TSQG-118 | 收口五语言 capability、组件回归与候选文档 | TSQG-114, TSQG-115, TSQG-116, TSQG-117 | capability/source scope 状态、语言正反例、C++/C# 回归、组件门禁和正式状态说明 | 定向行为与受影响组件验证通过，输出不越过证据边界；不运行无关完整评测，不制作 Release、安装或 Codex Publish |

0.5.0 已经闭合 TSQG-106、TSQG-107、TSQG-108 与 TSQG-109：`srcq symbol` 公开 definition/references/calls/capabilities，位置与名称身份分离，model/machine 分面和有界调用树已实现；26 种 ast-grep 语言均有显式 capability，实际适配语言按结构机制验证，未适配与不适用不会返回伪空集合。用户于 2026-08-31 重开 TSQG-109 的常用语言范围后，C 与 C# 已和 Go、Python、Rust、JavaScript、TypeScript、TSX、Java 一样接入语言节点表驱动的 generic relation engine；扩展只增加 grammar 描述、fixture 与能力/关系边界测试，不复制搜索、图展开或输出算法。TSQG-112 已实现 anchor/cwd、workspace、C++ compile database/MSVC response file 及 add/only/exclude 组合，并在 GptProjectTest 恢复 UE 外部定义；0.6.0 进一步实现 C# `.sln`/`.csproj` 静态 Compile resolver，以及 TypeScript/TSX/JavaScript、Rust、Go、Python 的本地项目元数据 resolver。Java 等其余非 C++ 语言仍保持 `explicit-or-project` 边界。TSQG-110 已接入紧凑 model/machine 输出与 source-query 渐进路由，但关系大结果仍以明确截断和重跑预算恢复，尚未接入同快照短句柄。TSQG-111 的完整组件门禁、真实 UAI 可靠性、release 性能、静态 Token、ast-grep 0.44.1 单一活动矩阵、可复现归档、安装生命周期与 GitHub Release 均已完成；`srcq-v0.5.0` 指向 `ae465953a838b168fe9485ca9e9e6546ad14ba74`，后继 `srcq-v0.6.0` 指向 `9bee175a1005485f6591fffa9ea3bdf0862d0c84`。用户默认安装仍为 0.5.0，Codex Publish 未执行；这些状态不影响 0.6.0 正式 Release，但不得把已发布候选外推为全部语言依赖全集或 LSP 精确语义。

2026-09-01 的 0.6.0 来源继续在 TSQG-109/112 内闭合 C# 无 LSP 可用性：C# 专用 adapter 以词法作用域内有效的显式源码类型收窄同名成员调用，支持 partial 唯一成员、短属性链与源码静态类型；incoming 复用已知根定义、批量扫描候选文件且只解析命中调用，不再重复解析所有同名定义或整段调用关系。VMTSingleMachine 的 4/3 个同名 `GetStatusAsync` caller 和 10 个 `_services.Vmt.MeasureOnceAsync` caller 均在默认预算内完成。C# scope 改为 `project-compile-aware`，静态解析 `.sln`/SDK `.csproj` 的 Compile 与 ProjectReference；空 Compile 集保持完整空集，无项目、多入口、祖先 Directory.Build、外部 wildcard item 或其他未知 MSBuild 输入明确降级。该能力已随 `srcq-v0.6.0` 发布；它不改变 Provider 的精确语义 owner，也未解决重载、扩展方法、动态分派、block-scoped/multiple namespace 限定名、其余语言依赖 resolver 或关系同快照续页。

用户于 2026-09-01 进一步要求 Go、Python、Rust、JavaScript、TypeScript 尽量达到 C++ 的解析效果，现由 UDES-SQG-020、AC-SQG-016、DES-SQG-021 与 SOL-SQG-017 重开并闭合 TSQG-113—118：TypeScript 首个纵向消费者先证明共享 typed relation 骨架，随后 JavaScript、Python、Go、Rust 接入各自 grammar；`SourceUniverse` 同时接入 Node、Cargo、Go 与 Python 的本地项目元数据 resolver。定向集成覆盖限定定义、outgoing、incoming、callable owner、词法越界和动态 unknown，既有 C++/C# 用例同跑；完整 srcq test/build/lint/fmt、skill routing contract 和独立只读复核均通过。“对齐 C++”只表示语言等价的项目范围、显式类型或限定候选、唯一调用递归和 callable owner，不包含编译器重载、动态分派、宏/生成代码或运行时绑定。用户随后明确授权本次 srcq GitHub Release，0.6.0 已发布并完成真实认证下载回验；用户默认安装与 AgentBase Codex Publish 未执行。

后续代码读取 skill 策略实验未达到用户确认的逐 case 晋级门槛，裁决与恢复身份见 [OBS-SQG-032](current-state.md#obs-sqg-032-代码读取-skill-候选未满足逐实验质量与价格门槛) 和 [审计证据](evidence/audit-result-code-reading-strategy-v1.json)。仓库 skill 已回到 `aafefc62187dae845944649a68750f16fe67073e` 的已用策略，`tools/srcq` 的 P16/P17 产品能力与 Release 保持不变。该策略工作不保留开放实施项；只有未来同身份配对 A/B 在每个冻结代表 case 上完整通过质量合同且短、长价格等价场景均严格下降时才重开，首个反例继续熔断余下矩阵。

## 5. 停止与重开条件

- AST 现有 CLI、profile、cache、fingerprint、process、rewrite、TTY/LSP、诊断或 release gate 任一发生非必要变化时，停止并回到设计裁决。
- 原生命令不能在不改变语义的情况下结构化时使用透传、产物或安全降级；不得用版本字符串拒绝可执行后端，仍有会误报成功、重复副作用或丢失原生语义的模式时停止兼容声明。
- 公共抽象迫使 backend 复制、丢失特有语义或新增第二状态源时，保留独立实现，不以形式统一为完成目标。
- fd tree 不能机械还原路径或预计 Token 不低于 flat 时不选 tree。
- 正常成功完整的 model 输出重新出现 envelope、schema、固定 receipt、重复事实或不能说明模型动作收益的字段时，重开 P7；不得用 machine 兼容需求迫使这些内容常驻模型上下文。
- 普通 rg/fd 查询重新要求模型先掌握 `exec`、argv 分隔、heading、tree、view、limit、receipt 或正文预算，或 renderer 在取得真实结果前按猜测固定格式时，重开 P8。
- 常驻规则不再给出 `srcq fd` 与 `srcq rg` 的最小语法，简单查询需要加载 skill/help/doctor，或 CLI 错形重新落入 AST 分隔错误、别名或 backend 猜测时，重开 P9。
- 已知名称再次仅因“完整定义”等请求措辞升级 AST，或 AST 无匹配后没有新增实际语法证据仍连续改写 pattern 时，重开 P9。
- 正式规则、skill 或文档重新允许模型裸用 rg、fd、ast-grep，或因查询简单直接绕过 srcq 时，重开 P8；原生等效输出必须由 srcq 在真实候选比较后选择。
- 外部适配遇到困难时先记录直接反例、根因和已排除方案；未满足 DES-SQG-013 的技术门槛不得提出源码升级，满足后也必须暂停、先与用户讨论并取得针对该次升级的明确同意，未获同意不得拉取、复制、内嵌或分叉源码，也不得继续堆叠 wrapper 特例或静默切换后端真源。
- 真实 Codex 质量退化时先修正质量；质量相同但总 Token 高于最近的同质量、同环境且 identity 可比参照，并且没有新增必要证据收益时，继续收紧或退出，不以速度补偿。五-skill 消融仅作方向性背景。
- control/candidate 出现 allowlist 外环境差异、subject 接触对照信息、monitor 干预答案、usage 缺失或 audit capsule 不完整时，该实验停止且不得进入收益聚合。
- Plugin 或 DirectCompatibility 候选 payload 中出现测试、fixture、benchmark、runner、corpus、原始结果或审计资产时停止发布，不以它们位于 skill 子目录为理由保留。
- `sgy` 到 `srcq` 未完成全部正式身份的原子迁移，srcq 未通过正式安装、状态、升级、卸载与新进程 PATH 读回，或任一消费者仍依赖 skill 内置副本时，停止运行时迁移与发布，不增加命令别名或双版本 fallback。
- LSP 渐进方案不能证明未用 LSP 时全量 Schema 未进入活动上下文，或发现回合使总 Token 不降反升时，不宣称渐进暴露已完成；进入 `srcq lsp` 降级设计后不得顺带迁入编辑器修改和执行职责。
- 不新增 `inspect`、批量证据包或自然语言规划入口，除非新的跨任务重复证据证明现有 owner 无法提供必要证据，并先修订需求、设计和 DEC-SQG-001 完成职责裁决；减少回合会丢失正式范围、完整正文、位置、顺序、截断或失败恢复语义时，停止合并并保留必要顺序查询。
