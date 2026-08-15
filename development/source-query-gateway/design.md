# 统一源码查询网关分支设计

## 1. 文档职责与状态

本文件定义满足 [requirements.md](requirements.md) 和 [user-design.md](user-design.md) 的候选模型设计，状态为 `implementation_revision`。历史候选完成过 backend、skill、payload、独立路由与受监控模型实验，但后续实现变化和新反例已经使“收益边缘已验证”的结论失效；当前仍只属于本分支，不改变 AgentBase 总体需求、正式 skill 或 Codex 安装态。

## 2. 设计结论

扩展现有 `tools/sgy`，用同一个 Windows 原生二进制承载 AST、rg 与 fd，但以现有 AST 设计为锚点：AST 的公开命令和行为合同保持不变，rg/fd 作为新的并列命令域接入。内部只抽取已经能证明相同的进程、预算、完整性、产物和发布职责，不要求三个 backend 共享同一种表面命令或结果记录。

该网关只是满足 `REQ-SQG-001` 的候选手段。所有接口统一、兼容矩阵和结构优化最终都必须证明模型先取得正确且充分的内容，再降低完整查找链的总 Token，并在前两项不退化时降低耗时；否则不能以工具实现完整代替根本需求达成。

| 命令域 | 原生 owner | 公开入口 |
| --- | --- | --- |
| AST | ast-grep | 保持 `sgy exec/defaults/cache/process/schema/capabilities/doctor` 现有合同 |
| rg | ripgrep | 新增 `sgy rg <exec|defaults|doctor> ... -- <rg argv...>` |
| fd | fd | 新增 `sgy fd <exec|defaults|doctor> ... -- <fd argv...>` |

LSP 继续由 `vscode-lsp-mcp` 负责真实符号身份、类型、精确引用、层级、诊断和安全重命名。PowerShell 继续负责 Windows 命令语言。sgy 不替模型选择查询语义，不签发副作用授权，也不判断任务完成。

## 3. 职责与接口

## DES-SQG-001 AST 设计是稳定基线

- 满足: AC-SQG-001, UDES-SQG-002, UDES-SQG-005, UDES-SQG-006

AST 继续使用当前强制 `--` argv 边界、透明参数数组、默认 JSON stream 注入、Token-Safe YAML、profile、cache、fingerprint、后处理、rewrite 安全边界、TTY/LSP、artifact、诊断退出码和发布来源。现有命令不是待淘汰兼容入口，而是 AST 的正式入口。

内部重构必须以当前 CLI、schema、退出状态、缓存身份、位置投影和写入证据为冻结 oracle。除修复已独立确认的 AST 缺陷外，不允许为了 backend 对称、统一 envelope 或减少实现行数改变这些可观察行为。

## DES-SQG-002 公共内核只抽取真实共同职责

- 满足: AC-SQG-001, AC-SQG-002, UDES-SQG-001, UDES-SQG-005

`tools/sgy` 维护一个内部公共执行包络，可包含引擎发现、cwd、参数数组、stdin/TTY、stdout/stderr 捕获、超时、退出状态、结果 spool、查询身份、上下文预算、诊断、artifact 和发布来源。每项抽取都必须先证明三个命令域具有相同生命周期和失败语义；否则留在 backend 内。

公共 Rust 类型不等于公共序列化格式。AST 继续输出现有 `_sgy` 和结果 schema；rg/fd 可以复用相同字段语义，但由各自 serializer 保留文本匹配、路径和 AST 节点的差异。

## DES-SQG-003 原生命令透明边界

- 满足: AC-SQG-001, UDES-SQG-002, UDES-SQG-005

所有 `--` 后 token 均以参数数组保留值、顺序和重复项，不经 shell 拼接。AST 沿用现有 `sgy defaults`；rg/fd 的 `defaults` 只展示原始 argv、为机器读取追加的参数、抑制原因和最终 argv，不启动底层引擎。

每个受支持精确版本维护完整命令矩阵，并把公开模式分为：可安全结构化、只可有界文本、应写显式产物、必须原样透传。不能结构化不等于不兼容；显式原生选项优先，包装只追加已证明不改变查询或副作用集合的机器输出选项。

## DES-SQG-004 最短充分输出规划

- 满足: AC-SQG-001, AC-SQG-002, UDES-SQG-003

backend 先形成 `EvidenceSignature`，明确当前表示必须保留的路径、类型、位置、正文、捕获、规则、诊断、顺序和完整性。规划器先按所选证据视图建立该视图自己的结果单元，再对这些单元分页：文件视图按去重后的匹配文件，位置视图按匹配位置，正文视图按匹配与上下文记录，摘要视图按完整聚合结果。不得先对另一种底层事件分页再投影，否则空页、重复对象和错误总量会把局部结果伪装成完整证据。规划器只比较签名相同的候选表示，并使用随二进制发布的确定性 Token 估算器选择预计成本最低者；真实 Codex 的 `input + output` Token 用于发布收益判断。

模型可见结果只携带当前判断所需的证据回执：总量与结果、展示、正文三类完整性固定显式返回；非零退出、分页身份和分页计数按状态出现。backend、引擎版本、mode、view、字节数和完整查询身份继续由内部快照持有，只有诊断或机器消费者显式请求时进入输出。稀疏展示不得删除内部校验事实，也不得用字段缺失隐含“完整”或“成功”。

AST 现有 profile 及其选择语义保持不变，不迁入新的 `auto` 规则。rg/fd 可提供 `auto` 与显式 view；不适用的 view 返回局部输入错误，不静默删除原生命令要求的信息。

## DES-SQG-005 结果完整性与分页快照

- 满足: AC-SQG-001, AC-SQG-002, UDES-SQG-003

每个 backend 的结构化结果都能表达引擎版本、查询身份、原生退出、总量、展示量、省略量、结果完整性、正文完整性和诊断，但“能够表达”不要求每次重复展示。默认回执使用自描述的稀疏版本，完整诊断回执使用显式入口；两者共享同一内部事实。查询先在内存中完成有界捕获和投影；只有结果需要续页或调用方显式请求完整诊断回执时才持久化不可变快照并返回其身份，已经完整且不暴露续页身份的默认结果不得留下无法使用的持久快照。游标绑定查询、快照和实际 view，分页不缩小底层查询范围。

AST 继续使用现有 cache 与 fingerprint 合同，不迁移到 rg/fd 的分页身份。内部可以复用 spool 和 cursor 原语，但不能制造第二套 AST 缓存或弱化源码变化检测。

## DES-SQG-006 fd 可逆目录树

- 满足: AC-SQG-001, AC-SQG-002, UDES-SQG-003, UDES-SQG-004

fd 优先取得无歧义的 NUL 分隔路径，为每个显式根分配稳定短别名，并按词法相对路径建立 trie。名称采用可逆转义，文件、目录和其他已识别类型可区分；多根、绝对路径和根外结果不合并成虚假共同根，重复项遵循原生命令语义。

同一结果生成 flat 与 tree 候选并比较预计 Token，tree 只有更短时才选中。预算不足时报告省略量与不完整状态；结构化省略节点不得与真实路径混淆。目录树是可逆表示，不是采样器。

## DES-SQG-007 rg 结果适配

- 满足: AC-SQG-001, AC-SQG-002, UDES-SQG-002, UDES-SQG-003

普通 batch 搜索使用 ripgrep 原生 JSON 事件，区分 match、context、begin/end、summary 与错误，并按 EvidenceSignature 选择分组正文、位置或文件视图。count、文件列表、replace 展示、passthru、preprocessor、显式 JSON、help/version 和特殊报告分别进入命令矩阵，不以启发式输出 flag 黑名单猜测。

无匹配、原生错误、转换错误和结果省略分别保持。只有完整消费底层结果才能声明查询集合完整；N+1 只能证明当前展示窗口是否还有下一项。

## DES-SQG-008 Skill 与成本路由

- 满足: AC-SQG-002, AC-SQG-003, UDES-SQG-001

候选最终只保留一个精炼的高级源码查询 skill；普通文件、文本、全集、不存在证明和已知实现读取由全局短路由直接完成，只有 AST、高级 rg/fd 协议或参数诊断才加载 skill，rg/fd 与 AST 的详细协议继续按需读取。AST 部分以现有 `ast-grep-token-safe` 合同为语义来源，迁移只改变文档归属，不改变 sgy 用法和安全边界；只有独立路由与行为证据证明等价后才退出旧 skill。

一次精确文件名发现、已知文件内少量文本定位或天然有界的直接读取继续使用受限原生快路径；全集、不存在证明、大结果压缩和目录树使用 PATH 中的 sgy rg/fd，但不因此加载 skill。只有实际需要 AST、缓存、分页、产物或特殊模式时才承担 skill 成本。LSP 只在真实符号语义会改变结论时升级。

## DES-SQG-009 安全与故障边界

- 满足: AC-SQG-001, UDES-SQG-002, UDES-SQG-005

网关不是 sandbox 或授权系统。rg preprocessor、fd exec/batch 与 ast-grep rewrite/apply 继续使用当前用户权限和上位授权。网关只对缺少解释必需输入、可能混用快照、二进制输出缺少产物目标或转换会破坏原生字节设置局部可恢复门禁；其他特殊模式透传或落产物并给诊断。

原生退出与 wrapper 错误分通道记录。转换失败不得输出成功空结果；stderr 不混入结构化 stdout，源码正文和秘密不进入 telemetry/meta。

## DES-SQG-010 受监控隔离基准是唯一收益入口

- 满足: AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-004, CON-SQG-003, UDES-SQG-007, UDES-SQG-008

[benchmark-protocol.md](benchmark-protocol.md) 定义本分支的语料、环境身份、隔离、监控、计量、审计和历史复用合同。分支获准实施后，由现有 `development/code-search-benchmark` 扩展为唯一 runner/monitor 与汇总 owner；其当前只分析记录的入口继续作为后处理子职责，不在本目录另写第二套执行器。分支目录只维护候选协议和版本化语料。

benchmark owner、语料、测试代码、fixtures、原始事件和审计结果全部留在 `development/` 或明确的项目外测试产物目录。发布 payload 只消费通过审计得到的设计裁决和运行时实现，不复制 benchmark 文件；共享 payload 合同负责让 Plugin 与 DirectCompatibility 两条发布路径执行同一排除规则，并在直接兼容发布时删除受管理 skill 下的旧测试副本。

每条 run 使用新鲜 `codex exec --json --ephemeral` 进程或能提供等价隔离与完整 usage 事件的正式入口。monitor 位于被测 agent 外部，只启动、观察、限时、归档和终止，不改变 prompt、补救答案或共享另一环境信息。subject、monitor 和 audit 的输入/输出单向流动；独立 audit 只能读取冻结 capsule，不读取候选实现讨论或历史结论。

实验 manifest 固定语料版本、项目快照、Codex/模型/推理/service tier、环境树 hash、允许差异、工具与 MCP 可用集、运行顺序种子、超时和网络策略。原始 JSONL、stderr、退出状态、最终答案、工具调用和最后一个 `turn.completed.usage` 一并保存。`total_tokens = input_tokens + output_tokens`；cached input 与 reasoning output 只作子项，不重复相加。质量先用结构化事实关系 oracle，再由独立审计处理语言等价和 oracle 缺陷。

历史结果按 experiment identity 只读登记。相同身份可直接复用，不为期待不同结果而重跑；候选实现或唯一差异改变时只运行受影响对照。身份不等或存在额外环境差异时，结果只能作为方向性现实依据，不能拼成因果结论。

## DES-SQG-011 sgy 是独立安装的唯一 Windows 运行时

- 满足: AC-SQG-001, UDES-SQG-001, UDES-SQG-005, UDES-SQG-009, CON-SQG-002

`tools/sgy` 是源码、构建、测试、安装器和发布来源的唯一 owner；正式 release 以受校验的 Windows x86_64 归档安装到 `%LOCALAPPDATA%\Programs\sgy\current`，由安装器维护唯一用户 `PATH` 项。PowerShell、统一查询 skill 和其他消费者只通过 `sgy.exe` 调用同一运行时，不从项目 `target/`、Codex 根目录、插件缓存或其他 skill 目录寻找二进制。

同一生命周期入口提供 `Install`、`Status`、以新归档执行的可恢复升级以及 `Uninstall`。安装和升级在提交前验证归档校验和、成员集合、目标架构、逐文件 hash 与实际 `sgy --version`；升级采用 staging 和失败恢复。卸载依据安装状态只删除受管文件和由安装器增加的 `PATH` 项，配置与 cache 默认保留，只有显式请求才删除 cache。新增 PATH 只保证后续进程可见，部署和文档必须要求重启 Codex 或重新打开终端。

候选转正时先安装并验证主机 CLI，再让消费者改用 `sgy.exe`，最后从 skill payload 删除内置二进制、runtime manifest、来源和许可副本。缺失、版本不受支持或命令身份无法确认时返回安装或升级恢复动作，不保留 skill 私有副本作为 fallback；否则会重新形成两个版本源并破坏穿透式更新。

## 4. 版本与迁移边界

首个候选以 ripgrep 15.1.0、fd 10.4.2 和当前 sgy 已验证的 ast-grep 0.41.1、0.42.0、0.44.1 建立 Windows 精确版本矩阵，不外推连续版本范围。完整兼容表示该精确版本所有公开模式都可通过相应命令域调用并保持原生语义，不表示所有模式都能结构化压缩。sgy workspace package version 是候选版本的唯一默认来源；构建参数只允许显式制作另一个已声明版本，不能长期用覆盖值掩盖源码、README、SBOM、release helper 与运行时版本不一致。

| 当前对象 | 分支目标 |
| --- | --- |
| `tools/sgy` | 保持 AST 正式入口并增加 rg/fd 命令域；作为独立 Windows CLI 的唯一源码、安装器和发布 owner |
| `rg_receipt.py` | rg 命令域完成真实替代后删除 |
| `rg-token-safe`、`fd-usage` | 消费者与路由证据闭环后由统一 skill 取代 |
| `ast-grep-token-safe` | 语义原样迁入按需 AST 引用后退出；sgy 命令不迁移 |
| `symbol-structure-workflow` | 保留，只维护查询与 LSP 的升级边界 |
| sgy Windows 运行时 | 通过正式安装器在用户级位置只安装一份并进入 `PATH`；消费者接入后退出 skill 内置副本 |
| `development/code-search-benchmark` | 分支实施后扩展为唯一隔离运行、监控、汇总和复核入口；不复制临时 runner |
| Codex Plugin/DirectCompatibility payload | 只接收运行时规则、skill 与工具；测试、benchmark 和审计资产始终排除 |

## 5. 主要风险与控制

| 风险 | 控制 |
| --- | --- |
| 表面统一破坏成熟 AST 合同 | AST 公开行为冻结；rg/fd 适配它的质量标准，不要求命令对称 |
| 公共抽象吞掉 backend 特有语义 | 先证明共同生命周期；serializer、cache 和写入边界允许独立 |
| 完整兼容退化为不完整 parser | 精确版本命令矩阵、argv 透明传递、透传/产物退路和真实引擎测试 |
| 更短输出丢失必要证据 | 先固定 EvidenceSignature，只比较语义等价表示 |
| fd tree 路径歧义 | 根别名、可逆转义、类型标记和 round-trip 性质测试 |
| 简单查询承担固定成本 | 保留适用范围不同的原生快路径，以端到端 Token 验证触发边界 |
| 基准 agent 受对照输出或协调方干预 | 新鲜 subject、单向监控、冻结 capsule 与独立 audit |
| 环境差异被误归因给候选 | 环境树 hash、允许差异清单、只读项目快照和身份不等即降级结论 |
| 测试资产增加 Codex 运行时体积或 Token | 测试 owner 固定在 development，共享 payload 过滤并清理旧受管理副本 |
| PATH 中的 sgy 缺失、被同名程序遮蔽或版本漂移 | 安装状态、`sgy --version`、`sgy doctor` 与发布身份读回；不回退到 skill 私有副本，PATH 变化后重启消费者进程 |

## 6. 设计完成判定

设计完成仍要求 rg/fd 全部公开模式有持久分类，各视图按自身语义单元给出正确总量、分页与完整性，fd tree 可逆，AST 现有 CLI、profile、cache、fingerprint、process、rewrite、TTY/LSP、诊断和发布合同逐项未退化；sgy 的安装、状态、升级、卸载、PATH、身份读回和旧内置运行时退出形成单一生命周期；并由当前候选身份下的独立路由与隔离模型证据按 `AC-SQG-001`、`AC-SQG-002`、`AC-SQG-003` 顺序证明达到收益边缘。当前已完成实现反例修正、供应链重建、独立路由和 candidate-only 影响验证，并修正了 benchmark 回答合同与 capsule 哈希；同 identity control/candidate 收益证据仍受用户冻结 control 的既有决定约束，因此不得进入 `validated_pending_user_adoption`。消费者迁移、旧同责入口退出、总体项目接入与 Codex 发布仍必须等待用户明确采纳和当次发布授权。
