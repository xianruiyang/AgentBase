# 统一源码查询网关分支设计

## 1. 文档职责与状态

本文件定义满足 [requirements.md](requirements.md) 和 [user-design.md](user-design.md) 的模型设计，状态为 `reopened_for_model_output_projection`。srcq 运行时、安装生命周期、正式 Skill、消费者退出和原生 LSP 渐进入口已经闭环；既有同身份收益证据只覆盖上一输出身份。新确认的模型输出收敛设计尚未实现或重新验收，项目变化也不表示 Codex 安装态已经发布。

## 2. 设计结论

由迁移前 `tools/sgy` 演化的 `tools/srcq` 用同一个 Windows 原生二进制承载 AST、rg 与 fd，并以既有 AST 设计为锚点：AST 的公开命令和行为合同保持不变，rg/fd 作为并列命令域接入。正式产品名为 `Source Query Gateway`、唯一命令为 `srcq.exe`；`sgy` 只标识迁移前实现、历史证据和为读取旧产物保留的数据协议。内部只抽取已经能证明相同的进程、预算、完整性、产物和发布职责，不要求各 backend 共享同一种表面命令或结果记录。

该网关只是满足 `REQ-SQG-001` 的候选手段。所有接口统一、兼容矩阵和结构优化最终都必须证明模型先取得正确且充分的内容，再降低完整查找链的总 Token，并在前两项不退化时降低耗时；否则不能以工具实现完整代替根本需求达成。

| 命令域 | 原生 owner | 当前入口 |
| --- | --- | --- |
| AST | ast-grep | `srcq exec/defaults/cache/process/schema/capabilities/doctor`，数据协议保持迁移前合同 |
| rg | ripgrep | `srcq rg <exec|defaults|doctor> ... -- <rg argv...>` |
| fd | fd | `srcq fd <exec|defaults|doctor> ... -- <fd argv...>` |

VS Code companion 与 Language Provider 继续拥有真实符号身份、类型、精确引用、层级和诊断事实；模型侧已由真实三案裁决采用 Codex 原生延迟 MCP 发现，不新增 `srcq lsp`。安全重命名、Code Action、格式化、命令执行和调试控制不属于 Source Query Gateway。PowerShell 继续负责 Windows 命令语言。网关不替模型选择查询语义，不签发副作用授权，也不判断任务完成。

## 3. 职责与接口

## DES-SQG-001 AST 设计是稳定基线

- 满足: AC-SQG-001, UDES-SQG-002, UDES-SQG-005, UDES-SQG-006

AST 继续使用当前强制 `--` argv 边界、透明参数数组、默认 JSON stream 注入、profile、cache、fingerprint、后处理、rewrite 安全边界、TTY/LSP、artifact、诊断退出码和发布来源。Token-Safe YAML 继续承担显式机器兼容与既有产物协议，但不强制成为每次模型查询的默认序列化。现有 AST 命令结构不是待淘汰兼容设计；TSQG-043 只将产品与命令前缀从 `sgy` 原子替换为 `srcq`，不将 AST 迁入另一套子命令或协议。

内部重构必须以当前 CLI、显式机器 schema、退出状态、缓存身份、位置投影和写入证据为冻结 oracle。允许新增或替换模型默认投影，但必须证明 AST 结果集合、源码范围、顺序、位置、缓存与写入语义不变；不得为了 backend 对称、统一 envelope 或减少实现行数改变这些语义。

## DES-SQG-002 公共内核只抽取真实共同职责

- 满足: AC-SQG-001, AC-SQG-002, UDES-SQG-001, UDES-SQG-005

`tools/srcq` 维护一个内部公共执行包络，可包含引擎发现、cwd、参数数组、stdin/TTY、stdout/stderr 捕获、超时、退出状态、结果 spool、查询身份、上下文预算、诊断、artifact 和发布来源。每项抽取都必须先证明三个命令域具有相同生命周期和失败语义；否则留在 backend 内。

公共 Rust 类型不等于公共序列化格式。AST 继续输出现有 `_sgy` 和结果 schema；rg/fd 可以复用相同字段语义，但由各自 serializer 保留文本匹配、路径和 AST 节点的差异。

## DES-SQG-003 原生命令透明边界

- 满足: AC-SQG-001, UDES-SQG-002, UDES-SQG-005

所有 `--` 后 token 均以参数数组保留值、顺序和重复项，不经 shell 拼接。AST 沿用迁移前 `defaults` 行为并由 `srcq defaults` 提供；rg/fd 的 `defaults` 只展示原始 argv、为机器读取追加的参数、抑制原因和最终 argv，不启动底层引擎。

每个受支持精确版本维护完整命令矩阵，并把公开模式分为：可安全结构化、只可有界文本、应写显式产物、必须原样透传。不能结构化不等于不兼容；显式原生选项优先，包装只追加已证明不改变查询或副作用集合的机器输出选项。

## DES-SQG-004 最短充分输出规划

- 满足: AC-SQG-001, AC-SQG-002, UDES-SQG-003

backend 先形成完整 `EvidenceSignature`，明确路径、类型、位置、正文、捕获、规则、诊断、顺序、范围和完整性；内部事实的充分性不由最终文字长短决定。规划器先按所选证据视图建立结果单元，再对这些单元分页：文件视图按去重文件，位置视图按匹配位置，正文视图按匹配与必要上下文，摘要视图按完整聚合。不得先对另一底层事件分页再投影。

同一事实对象提供三个互不混用的输出面：

| 输出面 | 默认使用方 | 合同 |
| --- | --- | --- |
| model | Codex/模型证据查询 | 干净的证据正文；只保留会改变当前判断、定位、继续查询或失败恢复的内容 |
| machine | 显式解析、诊断、round-trip 与兼容消费者 | 稳定 JSON/YAML schema，可表达全部内部事实 |
| native/artifact | 原生协议、二进制、TTY、LSP 与文件产物 | 保持原生字节、退出和副作用语义，不作为普通模型回执展开 |

模型默认视图使用固定协议语义与异常式回执：正常、完整、成功只输出证据正文，不添加总量、完成标记、schema 或容器；调用参数、进程退出状态和固定协议已经能证明的事实不在正文重复。仅当发生省略、正文截断、续页、错误或歧义时增加 shown/omitted、相关完整性、snapshot/cursor、原因与恢复动作。只展示所选证据视图存在的完整性维度；例如文件列表不输出无意义的 `content:false`。backend、引擎版本、mode、view、字节数、重复 argv、完整查询身份、空集合、固定 schema 与转义说明留在内部或显式 machine/diagnostic 视图。

所有能进入模型上下文的输出族——rg、fd、AST、doctor、defaults、schema/capabilities、cache/process、artifact 与错误——都必须逐项通过字段准入审查，不能只优化主查询 stdout。每个字段必须说明它改变哪项模型动作；无法说明则不进入默认模型视图。候选成本比较使用实际渲染后的模型字符串，而不是把内部对象重新序列化成 JSON/YAML 后估算。真实 Codex 的 `input + output` Token 仍用于最终收益判断。

AST 现有 profile、结果选择、缓存和写入语义保持不变；模型投影可以把文件/范围/源码正文只表达一次，并只在当前证据需要时展示 metavariable 捕获。rg/fd 可提供 `auto` 与显式 view；不适用的 view 返回局部输入错误，不静默删除原生命令要求的信息。

## DES-SQG-005 结果完整性与分页快照

- 满足: AC-SQG-001, AC-SQG-002, UDES-SQG-003

每个 backend 的内部结果都能表达引擎版本、查询身份、原生退出、总量、展示量、省略量、结果完整性、正文完整性和诊断；machine 视图可完整序列化这些事实，model 视图只投影当前相关差异。固定 model 协议把普通成功与完整结束作为无回执默认；无匹配优先由原生退出状态和空正文表达，只有宿主不能可靠保留退出语义时才使用一个最短标记。只有偏离默认状态时才显式报告差异，真正未知不得借省略伪装成默认。查询先在内存中完成有界捕获和投影；只有结果需要续页或调用方显式请求完整诊断回执时才持久化不可变快照并返回其身份，已经完整且不暴露续页身份的默认结果不得留下无法使用的持久快照。游标绑定查询、快照和实际 view，分页不缩小底层查询范围。

AST 继续使用现有 cache 与 fingerprint 合同，不迁移到 rg/fd 的分页身份。内部可以复用 spool 和 cursor 原语，但不能制造第二套 AST 缓存或弱化源码变化检测。

## DES-SQG-006 fd 可逆目录树

- 满足: AC-SQG-001, AC-SQG-002, UDES-SQG-003, UDES-SQG-004

fd 优先取得无歧义的 NUL 分隔路径，为每个显式根按需分配稳定短别名，并按词法相对路径建立紧凑基数树。model 视图把无分叉单子链用 `/` 合并，只在分叉处换行缩进；根只输出一次，查询已限定文件或目录时不逐项重复类型，只有混合类型或非默认对象才添加最小类型标记。空 `unmapped`、固定 escape 说明和 JSON 容器不进入正常 model 结果；转义由协议定义，多根或根外结果才出现短根标记。machine 视图继续提供完整可逆结构。

单根查询已由调用参数给出根时，model 输出只写相对路径；一条无分叉路径写成 `A/A0`，共享分支写成 `A/` 后用两空格缩进 `A0`、`A1/F1`、`A2`，另一条无分叉路径可直接写成 `B/B0/B1`。换行、缩进、`/` 和转义是协议字符而非装饰；若混合类型、根外路径或名称转义使该形式不再最短且无歧义，则选择 flat model 或显式 machine 视图，不为坚持树形引入大量标记。

同一结果生成 flat、紧凑 tree 与必要的 machine 候选，并按实际渲染文本比较成本；只在 EvidenceSignature 相同且更短时选择 tree。预算不足时报告省略量与不完整状态；省略标记不得与真实路径混淆。目录树是可逆表示，不是采样器。

## DES-SQG-007 rg 结果适配

- 满足: AC-SQG-001, AC-SQG-002, UDES-SQG-002, UDES-SQG-003

普通 batch 搜索使用 ripgrep 原生 JSON 事件，区分 match、context、begin/end、summary 与错误，并按 EvidenceSignature 选择分组正文、位置或文件视图。model 正文视图把路径只写一次、记录写为最短行号/正文形式，只有存在上下文时才增加上下文标记；位置视图只给路径、行和必要列范围；文件视图复用 fd 的紧凑路径表示；count 写为路径与数量。`type=match`、absolute offset、submatches、native 副本和重复 summary 只在当前证据或 machine 视图需要时出现。count、文件列表、replace 展示、passthru、preprocessor、显式 JSON、help/version 和特殊报告分别进入命令矩阵，不以启发式输出 flag 黑名单猜测。

无匹配、原生错误、转换错误和结果省略分别保持。只有完整消费底层结果才能声明查询集合完整；N+1 只能证明当前展示窗口是否还有下一项。

## DES-SQG-008 Skill 与成本路由

- 满足: AC-SQG-002, AC-SQG-003, UDES-SQG-001

候选最终只保留一个精炼的高级源码查询 skill；普通文件、文本、全集、不存在证明和已知实现读取由全局短路由直接完成，只有 AST、高级 rg/fd 协议或参数诊断才加载 skill，rg/fd 与 AST 的详细协议继续按需读取。AST 部分以现有 `ast-grep-token-safe` 合同为语义来源，迁移只改变文档归属和正式命令前缀，不改变 AST 命令结构、用法和安全边界；只有独立路由与行为证据证明等价后才退出旧 skill。

一次精确文件名发现、已知文件内少量文本定位或天然有界的直接读取继续使用受限原生快路径；全集、不存在证明、大结果压缩和目录树在迁移完成后使用 PATH 中的 srcq rg/fd，但不因此加载 skill。只有实际需要 AST、缓存、分页、产物或特殊模式时才承担 skill 成本。LSP 只在真实符号语义会改变结论时升级。

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

## DES-SQG-011 srcq 是独立安装的唯一 Windows 运行时

- 满足: AC-SQG-001, UDES-SQG-001, UDES-SQG-005, UDES-SQG-009, UDES-SQG-010, CON-SQG-002

迁移完成后 `tools/srcq` 是源码、构建、测试、安装器和发布来源的唯一 owner；正式 release 以受校验的 Windows x86_64 归档安装到 `%LOCALAPPDATA%\Programs\srcq\current`，由安装器维护唯一用户 `PATH` 项。PowerShell、统一查询 skill 和其他消费者只通过 `srcq.exe` 调用同一运行时，不从项目 `target/`、Codex 根目录、插件缓存或其他 skill 目录寻找二进制。`tools/sgy` 只在原子迁移提交完成前作为旧实现位置，不与 `tools/srcq` 共同成为正式 owner。

同一生命周期入口提供 `Install`、`Status`、以新归档执行的可恢复升级以及 `Uninstall`。安装和升级在提交前验证归档校验和、成员集合、目标架构、逐文件 hash 与实际 `srcq --version`；升级采用 staging 和失败恢复。卸载依据安装状态只删除受管文件和由安装器增加的 `PATH` 项，配置与 cache 默认保留，只有显式请求才删除 cache。新增 PATH 只保证后续进程可见，部署和文档必须要求重启 Codex 或重新打开终端。

产品身份迁移、隔离安装验证、正式 Skill 消费者接入和私有运行时退出已经完成。正式发布前必须先验证目标主机的 PATH 安装态；缺失、版本不受支持或命令身份无法确认时返回安装、升级或开启新终端的恢复动作，不保留 `sgy.exe` 别名或 skill 私有副本作为 fallback；否则会重新形成两个版本源并破坏穿透式更新。

## DES-SQG-012 LSP 语义查询渐进暴露与 srcq 降级路线

- 满足: AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-005, UDES-SQG-011

`vscode-lsp-mcp` 当前可以继续维护完整的独立工具注册表、精确输入 Schema、读/预览/修改标注和各自的验证；这个协议真源不等于必须将全部工具注入模型上下文。模型侧首选 Codex 宿主已有的延迟工具发现：普通查询不展示 LSP Schema；进入真实符号身份路径时只加载当前缺失操作；新能力只在后续证据需要时继续展开。skill 只声明这个路由原则和按需参考入口，不复制全量 Schema，也不默认先调用 health/capabilities 了解工具。

不以动态 `tools/list_changed` 或单一弱类型 `lsp_call(operation, args)` 作为未验证的唯一基础。前者依赖客户端刷新、卸载和 Prompt Cache 行为，后者会丢失精确 Schema 和安全标注；使用完整 `oneOf` 又不能降低常驻成本。先以真实 Codex 对比验证“启用 MCP 但不使用 LSP”、“只用一项 LSP”和“多阶段 LSP”三种路径的活动工具定义、Input/Output Token、缓存输入、工具回合、耗时和质量。宿主延迟发现只有在未用 LSP 时不注入全量工具、单项查询不自动展开无关工具，且节省覆盖发现回合成本时才算成立。

若宿主能力不稳定或不能实际降低上下文，则将只读 LSP 查询作为正式降级路线合并到 `srcq lsp`：可包含 workspace 发现、文档符号、symbol info、精确引用、调用/类型层级和诊断读取。`srcq` 只是模型侧渐进入口，VS Code companion 和 Language Provider 仍是语义事实 owner；MCP 可作为其他客户端的可选适配器。CLI 与 MCP 必须复用同一传输无关服务合同、认证 IPC、输入验证和 Provider 观测，不分别实现 LSP 业务。重命名、Code Action、格式化、命令和调试保留在编辑器操作职责，不随只读查询迁入。

## 4. 版本与迁移边界

当前以 ripgrep 15.1.0、fd 10.4.2 和迁移前已验证的 ast-grep 0.41.1、0.42.0、0.44.1 建立 Windows 精确版本矩阵，不外推连续版本范围。完整兼容表示该精确版本所有公开模式都可通过相应命令域调用并保持原生语义，不表示所有模式都能结构化压缩。`tools/srcq/Cargo.toml` 的 workspace package version 是当前候选版本的唯一默认来源；构建参数只允许显式制作另一个已声明版本，不能长期用覆盖值掩盖源码、README、SBOM、release helper 与运行时版本不一致。

| 当前对象 | 分支目标 |
| --- | --- |
| `sgy` 历史标识 | 只用于迁移前实现、冻结数据协议与历史证据；不再对应仓库运行时目录或可执行入口 |
| `tools/srcq` | 保持 AST 合同并承载 rg/fd 命令域；作为独立 Windows CLI 的唯一源码、安装器和发布 owner |
| `rg_receipt.py` | rg 命令域完成真实替代后删除 |
| `rg-token-safe`、`fd-usage` | 消费者与路由证据闭环后由统一 skill 取代 |
| `ast-grep-token-safe` | 语义原样迁入按需 AST 引用后退出；AST 命令结构不迁移，产品前缀按 TSQG-043 原子改为 srcq |
| `symbol-structure-workflow` | 转正前保留查询与 LSP 升级边界；统一 skill 只迁入已验证的渐进路由，不复制全量 Schema |
| `vscode-lsp-mcp` | 保持 VS Code companion、Provider 服务和完整 MCP 适配器；若宿主延迟发现失效，共享合同给 `srcq lsp` 只读入口 |
| srcq Windows 运行时 | 通过正式安装器在用户级位置只安装一份并进入 `PATH`；消费者接入后退出 skill 内置副本和 `sgy.exe` 别名 |
| `development/code-search-benchmark` | 分支实施后扩展为唯一隔离运行、监控、汇总和复核入口；不复制临时 runner |
| Codex Plugin/DirectCompatibility payload | 只接收运行时规则、skill 与工具；测试、benchmark 和审计资产始终排除 |

## 5. 主要风险与控制

| 风险 | 控制 |
| --- | --- |
| 表面统一破坏成熟 AST 合同 | AST 公开行为冻结；rg/fd 适配它的质量标准，不要求命令对称 |
| 公共抽象吞掉 backend 特有语义 | 先证明共同生命周期；serializer、cache 和写入边界允许独立 |
| 完整兼容退化为不完整 parser | 精确版本命令矩阵、argv 透明传递、透传/产物退路和真实引擎测试 |
| 更短输出丢失必要证据 | 先固定 EvidenceSignature，只比较语义等价表示 |
| fd tree 路径歧义 | 紧凑基数树、按需根/类型标记、可逆转义和 model/machine round-trip 性质测试 |
| 为机器稳定性把冗余 envelope 常驻给模型 | 三输出面分离、字段准入审查、默认语义与异常式回执；用实际 model renderer 计成本 |
| 简单查询承担固定成本 | 保留适用范围不同的原生快路径，以端到端 Token 验证触发边界 |
| 全量 LSP 工具 Schema 在无关任务中常驻 | 先验证 Codex 原生延迟发现；不成立时使用 `srcq lsp` 只读降级路线，以总 Token 与回合验收 |
| 为缩小 Schema 将 LSP 压成弱类型万能工具 | 保留完整协议注册和读/预览/应用标注；只改变模型侧暴露时机 |
| 基准 agent 受对照输出或协调方干预 | 新鲜 subject、单向监控、冻结 capsule 与独立 audit |
| 环境差异被误归因给候选 | 环境树 hash、允许差异清单、只读项目快照和身份不等即降级结论 |
| 测试资产增加 Codex 运行时体积或 Token | 测试 owner 固定在 development，共享 payload 过滤并清理旧受管理副本 |
| PATH 中的 srcq 缺失、被同名程序遮蔽或版本漂移 | 安装状态、`srcq --version`、`srcq doctor` 与发布身份读回；不回退到 skill 私有副本，PATH 变化后重启消费者进程 |

## 6. 设计完成判定

实现闭环要求 rg/fd 全部公开模式有持久分类，各视图按自身语义单元给出正确总量、分页与完整性，fd 紧凑树可逆；AST 现有 CLI、profile、cache、fingerprint、process、rewrite、TTY/LSP、machine schema、诊断和发布合同逐项未退化。所有模型可见输出族必须完成字段准入审查，model/machine/native 三面不混用，普通成功不重复机器 envelope，异常回执仍足以分页、判断截断和恢复；候选选择按实际 model 字符串，定向 round-trip、语义等价和真实 Codex 对照均通过。命名、安装生命周期、消费者退出和 LSP 渐进暴露的既有闭环继续有效。当前运行时尚未实现或验证新的模型投影，因此本设计重新打开，既有收益数字只作上一身份基线；Codex 发布仍须取得当次明确授权。
