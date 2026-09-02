# 统一源码查询网关分支设计

## 1. 文档职责与状态

本文件定义满足 [requirements.md](requirements.md) 和 [user-design.md](user-design.md) 的模型设计。P0—P15 已实现并验证；用户于 2026-08-30 新增低延迟、多语言源码关系目标，当前状态为 `reopened_for_p16_design`。既有 srcq 运行时、安装生命周期、正式 Skill、消费者退出、原生 LSP 渐进入口、rg/fd 直觉入口、结果后置投影、同预算自动闭环和分层路由继续作为已验证基线；P16 的 proposed 设计不得反向把未实现能力写成当前状态。后续发布仍须取得当次明确同意。

## 2. 设计结论

由迁移前 `tools/sgy` 演化的 `tools/srcq` 用同一个 Windows 原生二进制承载 AST、rg 与 fd，并以既有 AST 设计为锚点：AST 的公开命令和行为合同保持不变，rg/fd 作为并列命令域接入。正式产品名为 `Source Query Gateway`、唯一命令为 `srcq.exe`；`sgy` 只标识迁移前实现、历史证据和为读取旧产物保留的数据协议。内部只抽取已经能证明相同的进程、预算、完整性、产物和发布职责，不要求各 backend 共享同一种表面命令或结果记录。

该网关只是满足 `REQ-SQG-001` 的候选手段。所有接口统一、兼容矩阵和结构优化最终都必须证明模型先取得正确且充分的内容，再降低完整查找链的总 Token，并在前两项不退化时降低耗时；否则不能以工具实现完整代替根本需求达成。

| 命令域 | 原生 owner | 目标普通模型入口 |
| --- | --- | --- |
| AST | ast-grep | `srcq exec/defaults/cache/process/schema/capabilities/doctor`，数据协议保持迁移前合同 |
| rg | ripgrep | `srcq rg <rg argv...>`；网关定向控制只在显式控制面出现 |
| fd | fd | `srcq fd <fd argv...>`；网关定向控制只在显式控制面出现 |

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

AST 的 `--` 后 token 继续以参数数组保留值、顺序和重复项，不经 shell 拼接。rg/fd 的普通入口把 backend 后全部 token 直接视为原生 argv，使模型可按原生命令直觉调用；网关的 machine/native、定向投影和预算覆盖必须放在 backend 之前的独立控制面或其他无冲突入口，不抢占原生 flag。AST 沿用迁移前 `defaults` 行为并由 `srcq defaults` 提供；rg/fd 的显式 defaults/diagnostic 入口只展示原始 argv、为机器读取追加的参数、抑制原因和最终 argv，不启动底层引擎。

命令矩阵按公开模式和实际输出能力维护，并以测试时观察到的精确后端身份标注证据范围；版本字符串不参与运行准入。公开模式分为：可安全结构化、只可有界文本、应写显式产物、必须原样透传。不能结构化不等于不兼容；显式原生选项优先，包装只追加已证明不改变查询或副作用集合的机器输出选项。

## DES-SQG-004 最短充分输出规划

- 满足: AC-SQG-001, AC-SQG-002, UDES-SQG-003

普通调用只定义查询语义，不定义展示算法。backend 先取得真实结果并形成完整 `EvidenceSignature`，明确路径、类型、位置、正文、捕获、规则、诊断、顺序、范围和完整性；内部事实的充分性不由最终文字长短决定。规划器随后生成单行 locator、文件 heading、分组正文、紧凑路径树、路径树与位置 heading 组合等适用候选，先证明结果集合、顺序、关系、范围、正文和完整性语义相同，再按实际模型文本成本选择最低充分表示。模型不需要在结果未知时预先提供 heading、view、limit 或正文预算。

规划器按候选证据单元分页：文件表示按去重文件，位置表示按匹配位置，正文表示按匹配与必要上下文，摘要表示按完整聚合。默认模型上下文预算由工具安全持有；取得完整事实后先判断整个结果能否在相同总预算和硬单元上限内闭环，能完整容纳才越过初始项数限制。单一来源正文可以在总预算不增加时提高单行完整度，多来源、过大或不能证明完整容纳的结果保持较小初始页，并在不拆坏证据单元的边界上产生可续页快照。不得先按另一底层事件或模型猜测的固定数量分页再投影，也不得为降低一次输出成本制造更昂贵的同文件重复查询。调用方明确选择 machine、native、artifact 或定向证据表示时跳过自动选择并精确保留其 limit、正文和预算语义，但仍不削弱资源硬上限、退出和完整性合同。

同一事实对象提供三个互不混用的输出面：

| 输出面 | 默认使用方 | 合同 |
| --- | --- | --- |
| model | Codex/模型证据查询 | 干净的证据正文；只保留会改变当前判断、定位、继续查询或失败恢复的内容 |
| machine | 显式解析、诊断、round-trip 与兼容消费者 | 稳定 JSON/YAML schema，可表达全部内部事实 |
| native/artifact | 原生协议、二进制、TTY、LSP 与文件产物 | 保持原生字节、退出和副作用语义，不作为普通模型回执展开 |

模型默认视图使用固定协议语义与异常式回执：正常、完整、成功只输出证据正文，不添加总量、完成标记、schema 或容器；调用参数、进程退出状态和固定协议已经能证明的事实不在正文重复。仅当发生省略、正文截断、续页、错误或歧义时增加 shown/omitted、相关完整性、snapshot/cursor、原因与恢复动作。只展示所选证据视图存在的完整性维度；例如文件列表不输出无意义的 `content:false`。backend、引擎版本、mode、view、字节数、重复 argv、完整查询身份、空集合、固定 schema 与转义说明留在内部或显式 machine/diagnostic 视图。

所有能进入模型上下文的输出族——rg、fd、AST、doctor、defaults、schema/capabilities、cache/process、artifact 与错误——都必须逐项通过字段准入审查，不能只优化主查询 stdout。每个字段必须说明它改变哪项模型动作；无法说明则不进入默认模型视图。候选成本比较使用实际渲染后的模型字符串，而不是把内部对象重新序列化成 JSON/YAML 后估算。真实 Codex 的 `input + output` Token 仍用于最终收益判断。

AST 现有 profile、结果选择、缓存和写入语义保持不变；模型投影可以把文件/范围/源码正文只表达一次，并只在当前证据需要时展示 metavariable 捕获。rg/fd 的普通调用隐式采用 auto，显式 view 只作为可选定向控制；不适用的 view 返回局部输入错误，不静默删除原生命令要求的信息。

## DES-SQG-005 结果完整性与分页快照

- 满足: AC-SQG-001, AC-SQG-002, UDES-SQG-003

每个 backend 的内部结果都能表达引擎版本、查询身份、原生退出、总量、展示量、省略量、结果完整性、正文完整性和诊断；machine 视图可完整序列化这些事实，model 视图只投影当前相关差异。固定 model 协议把普通成功与完整结束作为无回执默认；无匹配优先由原生退出状态和空正文表达，只有宿主不能可靠保留退出语义时才使用一个最短标记。只有偏离默认状态时才显式报告差异，真正未知不得借省略伪装成默认。查询先在内存中完成有界捕获和投影；只有结果需要续页或调用方显式请求完整诊断回执时才持久化不可变快照并返回其身份，已经完整且不暴露续页身份的默认结果不得留下无法使用的持久快照。游标绑定查询、快照和实际 view，分页不缩小底层查询范围。

AST 继续使用现有 cache 与 fingerprint 合同，不迁移到 rg/fd 的分页身份。内部可以复用 spool 和 cursor 原语，但不能制造第二套 AST 缓存或弱化源码变化检测。

## DES-SQG-006 fd 可逆目录树

- 满足: AC-SQG-001, AC-SQG-002, UDES-SQG-003, UDES-SQG-004

fd 优先取得无歧义的 NUL 分隔路径，为每个显式根按需分配稳定短别名，并按词法相对路径建立紧凑基数树。model 视图把无分叉单子链用 `/` 合并，只在分叉处换行缩进；根只输出一次，查询已限定文件或目录时不逐项重复类型，只有混合类型或非默认对象才添加最小类型标记。空 `unmapped`、固定 escape 说明和 JSON 容器不进入正常 model 结果；转义由协议定义，多根或根外结果才出现短根标记。machine 视图继续提供完整可逆结构。

单根查询已由调用参数给出根时，model 输出只写相对路径；一条无分叉路径写成 `A/A0`，共享分支写成 `A/` 后用两空格缩进 `A0`、`A1/F1`、`A2`，另一条无分叉路径可直接写成 `B/B0/B1`。换行、缩进、`/` 和转义是协议字符而非装饰；若混合类型、根外路径或名称转义使该形式不再最短且无歧义，则选择 flat model 或显式 machine 视图，不为坚持树形引入大量标记。

同一结果生成 flat、紧凑 tree 与必要的 machine 候选，并按实际渲染文本比较成本；只在 EvidenceSignature 相同且更短时选择 tree。tree renderer 同时供 rg 的文件与位置结果使用：目录节点压缩公共前缀，文件叶子只有一个位置时可直接承载 locator，同文件多个位置时作为 heading 并缩进位置叶子。预算不足时报告省略量与不完整状态；省略标记不得与真实路径混淆。目录树是可逆表示，不是采样器，也不是模型必须请求的 view。

## DES-SQG-007 rg 结果适配

- 满足: AC-SQG-001, AC-SQG-002, UDES-SQG-002, UDES-SQG-003

普通 batch 搜索使用 ripgrep 原生 JSON 事件，区分 match、context、begin/end、summary 与错误。工具先依据原生命令语义确定必须保留的证据维度，再按真实结果形状在等价 renderer 中选择：离散单位置可用单行 locator，同文件多位置用一次路径 heading，多文件共享长目录用路径树，路径树文件叶子可继续承载位置 heading；正文结果按文件分组并把路径只写一次，只有存在上下文时才增加上下文标记；文件结果复用 fd 的紧凑路径表示；count 写为路径与数量。是否使用这些形式不要求模型预先传 `--heading`、`--view` 或 `--limit`。

`type=match`、absolute offset、submatches、native 副本和重复 summary 只在当前证据或 machine 视图需要时出现。原生 heading/no-heading、vimgrep、JSON 等显式格式意图由命令矩阵映射到定向 model、machine 或 native 行为；调用方明确要求原生字节时不得再自动改写。count、文件列表、replace 展示、passthru、preprocessor、help/version 和特殊报告分别进入命令矩阵，不以启发式输出 flag 黑名单猜测。

无匹配、原生错误、转换错误和结果省略分别保持。只有完整消费底层结果才能声明查询集合完整；N+1 只能证明当前展示窗口是否还有下一项。

普通查询不预检或限制 ripgrep 版本。adapter 先按实际事件和字段合同解析；解析成功才进入自适应投影。实际输出不满足结构合同但命令可执行时，不得把版本差异升级为拒绝：无副作用且可确定重放的只读模式可在同一 `srcq` 调用内降级为原生文本，可能启动外部程序、写入或改变状态的模式必须在执行前进入 native/artifact，禁止为降级重复执行。任何降级都保留真实退出与错误，不能把转换失败解释为空集合。

## DES-SQG-008 Skill 与成本路由

- 满足: AC-SQG-002, AC-SQG-003, UDES-SQG-001

候选最终只保留一个精炼的高级源码查询 skill；已知文件正文可以直接有界读取，所有需要 rg、fd 或 ast-grep 的模型查询统一调用 PATH 中的 srcq，不保留裸工具快路径。常驻规则只提供完成普通任务不可再省的两个正式语法：文件发现使用 `srcq fd <fd argv...>`，文本查询使用 `srcq rg <rg argv...>`；普通调用不加载 skill，也不要求 heading、tree、view、limit、receipt 或预算。只有 AST、缓存、显式 machine/native、特殊模式或参数诊断才读取详细协议。CLI 对 `srcq files`、`srcq --files` 等可识别错形只返回指向上述唯一入口的最短修正，不新增别名或第二查询语法。AST 部分以现有 `ast-grep-token-safe` 合同为语义来源，迁移只改变文档归属和正式命令前缀，不改变 AST 命令结构、用法和安全边界；只有独立路由与行为证据证明等价后才退出旧 skill。

已知文件正文的天然有界读取可继续直接完成；文件发现、文本定位、全集、不存在证明、结果压缩、目录树和 AST 全部使用 PATH 中的 srcq。已知名称先经文本定位和有界源码读取闭环；“完整定义”只是验收结果，不单独触发 AST。限定源码范围内由一次完整文本结果即可证明的唯一名称定义与直接调用、显式接口/字段/类型映射也不加载高级 skill。只有已经取得文本证据仍不能可靠确定语法边界、候选存在歧义、目标读取被截断，或任务确需结构关系、控制流、rule/rewrite 时才升级 AST；真实符号身份、重载、类型或精确引用会改变结论时才升级 LSP。AST 无匹配后不得仅改写 pattern 连续试探，必须先从实际源码取得会改变下一次查询的新证据，或返回文本路径。简单查询由 srcq 内部走最低充分执行与 renderer，不因结果少就绕过网关。

## DES-SQG-009 安全与故障边界

- 满足: AC-SQG-001, UDES-SQG-002, UDES-SQG-005

网关不是 sandbox 或授权系统。rg preprocessor、fd exec/batch 与 ast-grep rewrite/apply 继续使用当前用户权限和上位授权。网关只对缺少解释必需输入、可能混用快照、二进制输出缺少产物目标或转换会破坏原生字节设置局部可恢复门禁；其他特殊模式透传或落产物并给诊断。

原生退出与 wrapper 错误分通道记录。转换失败不得输出成功空结果；无副作用降级只可在同一调用内进行，不能把需要模型运行 doctor、help 或改写命令的恢复当作普通成功路径。stderr 不混入结构化 stdout，源码正文和秘密不进入 telemetry/meta。

## DES-SQG-010 受监控隔离基准是唯一收益入口

- 满足: AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-004, CON-SQG-003, UDES-SQG-007, UDES-SQG-008

[benchmark-protocol.md](benchmark-protocol.md) 定义本分支的语料、环境身份、隔离、监控、计量、审计和历史复用合同。分支获准实施后，由现有 `development/code-search-benchmark` 扩展为唯一 runner/monitor 与汇总 owner；其当前只分析记录的入口继续作为后处理子职责，不在本目录另写第二套执行器。分支目录只维护候选协议和版本化语料。

benchmark owner、语料、测试代码、fixtures、原始事件和审计结果全部留在 `development/` 或明确的项目外测试产物目录。发布 payload 只消费通过审计得到的设计裁决和运行时实现，不复制 benchmark 文件；共享 payload 合同负责让 Plugin 与 DirectCompatibility 两条发布路径执行同一排除规则，并在直接兼容发布时删除受管理 skill 下的旧测试副本。

每条 run 使用新鲜 `codex exec --json --ephemeral` 进程或能提供等价隔离与完整 usage 事件的正式入口。monitor 位于被测 agent 外部，只启动、观察、限时、归档和终止，不改变 prompt、补救答案或共享另一环境信息。subject、monitor 和 audit 的输入/输出单向流动；独立 audit 只能读取冻结 capsule，不读取候选实现讨论或历史结论。确定性 `verify-capsule` 负责重算 canonical capsule、experiment identity、原始流和环境文件哈希，独立模型只裁决 prompt、answer contract、oracle 与结构完整性，不要求模型心算密码学摘要。

实验 manifest 固定语料版本、项目快照、Codex/模型/推理/service tier、环境树 hash、允许差异、工具与 MCP 可用集、运行顺序种子、超时和网络策略。原始 JSONL、stderr、退出状态、最终答案、工具调用和最后一个 `turn.completed.usage` 一并保存。`total_tokens = input_tokens + output_tokens`；cached input 与 reasoning output 只作子项，不重复相加。质量先用结构化事实关系 oracle，再由独立审计处理语言等价和 oracle 缺陷。

历史结果按 experiment identity 只读登记。相同身份可直接复用，不为期待不同结果而重跑；候选实现或唯一差异改变时只运行受影响对照。身份不等或存在额外环境差异时，结果只能作为方向性现实依据，不能拼成因果结论。

## DES-SQG-011 srcq 是独立安装的唯一 Windows 运行时

- 满足: AC-SQG-001, UDES-SQG-001, UDES-SQG-005, UDES-SQG-009, UDES-SQG-010, CON-SQG-002

迁移完成后 `tools/srcq` 是源码、构建、测试、安装器和发布来源的唯一 owner；正式 release 以受校验的 Windows x86_64 归档安装到 `%LOCALAPPDATA%\Programs\srcq\current`，由安装器维护唯一用户 `PATH` 项。PowerShell、统一查询 skill 和其他消费者只通过 `srcq.exe` 调用同一运行时，不从项目 `target/`、Codex 根目录、插件缓存或其他 skill 目录寻找二进制。`tools/sgy` 只在原子迁移提交完成前作为旧实现位置，不与 `tools/srcq` 共同成为正式 owner。

同一生命周期入口提供 `Install`、`Status`、以新归档执行的可恢复升级以及 `Uninstall`。安装和升级在提交前验证归档校验和、成员集合、目标架构、逐文件 hash 与实际 `srcq --version`；升级采用 staging 和失败恢复。卸载依据安装状态只删除受管文件和由安装器增加的 `PATH` 项，配置与 cache 默认保留，只有显式请求才删除 cache。新增 PATH 只保证后续进程可见，部署和文档必须要求重启 Codex 或重新打开终端。

产品身份迁移、隔离安装验证、正式 Skill 消费者接入和私有运行时退出已经完成。正式发布前必须先验证目标主机的 PATH 安装态；缺少 `srcq.exe`、受管安装损坏、srcq 命令身份不符或 PATH 尚未刷新时返回安装、升级或开启新终端的恢复动作。rg、fd 或 ast-grep 的版本差异不触发 srcq 安装恢复，也不保留 `sgy.exe` 别名或 skill 私有副本作为 fallback；否则会重新形成两个版本源并破坏穿透式更新。

## DES-SQG-012 LSP 语义查询渐进暴露与 srcq 降级路线

- 满足: AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-005, UDES-SQG-011

`vscode-lsp-mcp` 当前可以继续维护完整的独立工具注册表、精确输入 Schema、读/预览/修改标注和各自的验证；这个协议真源不等于必须将全部工具注入模型上下文。模型侧首选 Codex 宿主已有的延迟工具发现：普通查询不展示 LSP Schema；进入真实符号身份路径时只加载当前缺失操作；新能力只在后续证据需要时继续展开。skill 只声明这个路由原则和按需参考入口，不复制全量 Schema，也不默认先调用 health/capabilities 了解工具。

不以动态 `tools/list_changed` 或单一弱类型 `lsp_call(operation, args)` 作为未验证的唯一基础。前者依赖客户端刷新、卸载和 Prompt Cache 行为，后者会丢失精确 Schema 和安全标注；使用完整 `oneOf` 又不能降低常驻成本。先以真实 Codex 对比验证“启用 MCP 但不使用 LSP”、“只用一项 LSP”和“多阶段 LSP”三种路径的活动工具定义、Input/Output Token、缓存输入、工具回合、耗时和质量。宿主延迟发现只有在未用 LSP 时不注入全量工具、单项查询不自动展开无关工具，且节省覆盖发现回合成本时才算成立。

若宿主能力不稳定或不能实际降低上下文，则将只读 LSP 查询作为正式降级路线合并到 `srcq lsp`：可包含 workspace 发现、文档符号、symbol info、精确引用、调用/类型层级和诊断读取。`srcq` 只是模型侧渐进入口，VS Code companion 和 Language Provider 仍是语义事实 owner；MCP 可作为其他客户端的可选适配器。CLI 与 MCP 必须复用同一传输无关服务合同、认证 IPC、输入验证和 Provider 观测，不分别实现 LSP 业务。重命名、Code Action、格式化、命令和调试保留在编辑器操作职责，不随只读查询迁入。

## DES-SQG-013 后端实现采用外部适配优先、源码改造有证据升级

- 满足: AC-SQG-001, AC-SQG-002, AC-SQG-003, UDES-SQG-005, UDES-SQG-014

rg、fd 与 ast-grep 默认继续作为外部执行后端：srcq 负责 argv、进程、基于实际输出能力的事件或文本协议、证据签名、投影和分页，上游负责搜索语义。运行时不以精确版本名单限制后端；测试仍冻结观察到的版本身份与行为上限，使上游升级和 srcq 输出策略可以分别验证。这个边界能直接复用成熟引擎并降低自有维护面，当前没有足以触发源码分叉的证据，不预先下载、复制或内嵌上游实现。

只有可重复反例证明某项必要验收无法由公开 argv、输出协议、原生模式、产物通道或 srcq 后处理实现，且根因已定位到上游内部时，才建立升级裁决。裁决输入必须包含失败语义与影响、最小复现、根因位置、已尝试的有界外部方案、为何不能满足目标、目标上游 revision，以及许可证、安全、构建体积、编译时间、更新频率和漏洞响应成本。该裁决只形成向用户讨论的建议；必须取得用户针对该次源码升级的明确同意后，才能拉取、复制、内嵌或分叉上游源码。证据不足或用户未同意时继续适配、收紧声明或保持阻塞，不以“做起来困难”代替根因，也不自行越过授权边界。

若裁决通过，改造代码作为 srcq 后端的受管 Windows 构建依赖，不成为新的公开命令。修改保持最小、可审查并尽量可向上游提交；版本、补丁集、来源 hash、许可证和产物 hash 进入同一 release manifest。每次上游升级重放行为矩阵、补丁适用性、供应链与性能验证；上游已提供等价能力、维护成本超过收益或补丁无法安全续用时，退出分叉并回到外部后端。禁止同时维护无期限的系统版、内嵌版和 wrapper 特例来决定同一行为。

## DES-SQG-014 查询按最小证据闭环组织

- 满足: AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-007, UDES-SQG-002, UDES-SQG-003, UDES-SQG-012, UDES-SQG-013

源码查询围绕当前结论仍缺的最小直接证据组织。模型从最近项目正式来源确定权威源码范围和真实依赖，选择能够直接补足缺口的最低充分入口；文件已知或唯一定位后按命中范围直接有界读取正文，不再用搜索重读；证据已足够就停止，截断、候选歧义或语义身份确实未决才提高工具层级。项目的修改前置阅读规则不得外推到纯只读源码定位。规则不规定每层调用次数、首查锚点组合或固定阅读顺序，也不以减少命令数替代来源、位置、关系、正文完整性、失败和恢复语义。

`srcq fd`、`srcq rg`、现有 AST 与渐进 LSP 继续是正式查询入口。模型负责查询语义和证据裁决；srcq 负责自己可见的完整结果形状、等价表示、机械有界闭环和分页，不解析自然语言、猜测项目权威或建立第二套任务规划器。只有受监控记录反复证明某类必要闭环无法由现有入口以可维护方式表达，且新增能力在质量不退化时显著降低总 Token 或失败率，才允许扩展现有 srcq owner。优先增强现有命令域和投影；只有其原生兼容职责无法承载时，才讨论新的高层命令。

## DES-SQG-015 query model renderer 持有可执行续页动作

- 状态: confirmed
- 关联: REQ-SQG-001, AC-SQG-007, AC-SQG-009, UDES-SQG-015

公共 `query_gateway` 已同时持有 backend、wrapper 状态、原生 argv、snapshot 与 cursor，因此由它唯一生成 `@more shown=<N> omitted=<N>` 和紧随其后的 `@next <PowerShell command>`。命令重放显式 engine/cwd、影响分页的非默认 wrapper 值、精确 cursor 与全部原生 argv；安全 token 裸写，其他值按 PowerShell 7 单行字面量无损转义。machine `next_cursor`、snapshot 身份、cache/process 分页和 native backend 保持现有 owner；模型或 skill 不维护第二份续页语法。

## DEC-SQG-001 是否建立高层源码关系命令

- 状态: confirmed
- 关联: REQ-SQG-002, UDES-SQG-016, DES-SQG-014

现有 rg、AST 与 LSP 分步入口无法以一次可维护调用表达反复出现的定义候选、引用候选和调用树闭环；UAI 代表探针已证明同一组合能在保持歧义边界的同时显著降低冷路径耗时。P16 因此允许扩展 `srcq` 现有 owner，建立明确的只读源码关系命令域。该决定不授权自然语言规划入口、不把候选升级为精确语义，也不迁入编辑器修改职责；正式命令名称与参数仍由 P16 的位置身份和输出合同裁决。

## DES-SQG-016 源码关系由分层证据而非伪语义统一

- 状态: confirmed
- 满足: REQ-SQG-002, AC-SQG-010, AC-SQG-011, AC-SQG-012, AC-SQG-013, AC-SQG-014, AC-SQG-015, UDES-SQG-016, UDES-SQG-017, UDES-SQG-018, UDES-SQG-019

`tools/srcq` 作为唯一公开 owner 组合现有外部 rg 与 ast-grep：源码宇宙解析器先形成有来源和完整性边界的根集合，rg 在其中完整生成词面候选；AST run/outline 和语言适配器归一化声明、定义、作用域、引用角色、调用与外层 owner；同一查询 owner 负责批处理、缓存复用、图遍历、完整性、分页和 model/machine 投影。VS Code Companion 与实际 Language Provider 继续拥有精确符号身份、类型和动态语义，srcq 不复制 Provider 业务。

关系证据至少区分 `syntax-direct`、`qualified-candidate`、`lexical-candidate`、`ambiguous` 与 `semantic-unknown`。扫描范围完整性、AST 分类确定性和符号身份确定性分别持有；任一项未知都不得借另一个维度的完成状态隐式提升。快速路径足够支撑当前模型判断时停止，只有歧义会改变动作或结论时才按需升级 LSP 或领域工具。

## DES-SQG-017 位置身份、能力注册与语言适配

- 状态: confirmed
- 满足: AC-SQG-010, AC-SQG-012, UDES-SQG-017

源码位置是关系查询的规范符号输入，名称查询只返回候选。内部 `LanguageCapability` 注册表按实际外部引擎能力声明 parse、outline、scope、definition、reference-role、direct-call、import-binding 和 semantic-exact 等独立能力；语言适配器只维护 Tree-sitter grammar 差异，不复制 rg 扫描、图遍历、分页或输出策略。所有 ast-grep 内置语言都由 capability owner 显式登记，关系不适用、仅候选、未适配和解析失败使用不同结果。

定义候选优先适配 ast-grep outline 的结构化 JSON，但该能力自 0.44.0 起仍为 alpha，必须通过功能探测、结构验证和受测版本证据使用，不按版本字符串直接准入。局部变量、参数、遮蔽和调用节点由按独立语法机制组织的适配规则补足；不能可靠外部适配时先收紧能力，不自行内嵌或分叉 ast-grep。

## DES-SQG-018 有界关系图不递归放大歧义

- 状态: confirmed
- 满足: AC-SQG-011, AC-SQG-013

调用树以稳定的文件、范围、语言、符号种类和签名候选组成节点，以调用位置、方向和证据等级组成边。遍历按层批量生成 frontier 候选并复用同文件 AST，只递归展开身份唯一的边；歧义、虚分派、宏、模板、函数值、动态绑定和跨语言生成关系作为带原因的叶子保留。循环检测、节点/边预算和现有续页 owner 控制工作量与模型上下文，不能把预算耗尽、未适配或未展开表示为没有关系。

## DES-SQG-019 SourceUniverse 持有跨工作区源码范围

- 状态: confirmed
- 满足: AC-SQG-001, AC-SQG-007, AC-SQG-014, UDES-SQG-018

关系查询内部建立可重建的 `SourceUniverse`，但不建立新的人工配置真源。它以查询目标的位置和语言为锚点，合并调用方显式根、现有编辑器多根配置、编译数据库、编译器响应文件、项目/模块清单与语言依赖元数据；每个根保留 canonical path、稳定别名、来源、相对路径解析基准、模块/依赖/版本身份、源码/生成/系统分类、适用语言与 freshness。机器面保存完整绝对路径和诊断，model 面正常只用 `project:`、`ue:`、`dep:` 等本次稳定别名表示命中；只有范围不完整会改变判断时才投影缺失来源和最短恢复动作。

C/C++ 适配器至少能从 `compile_commands.json` 读取 source、directory 和 command/arguments，按 MSVC 规则有界递归展开 `@response-file` 并检测缺失、循环和陈旧输入，再将相对 include/source 路径按真实基准规范化；UE 只作为该通用机制的消费者，不在 srcq 中硬编码引擎路径或 UBT 语法。其他语言由各自适配器消费已经存在的项目与依赖元数据，例如 TypeScript/JavaScript project/package、Python project/environment/import、Rust workspace/package、Go module/workspace、Java 或 C# build/project 描述；没有可靠 resolver 的语言仍允许显式根查询，但 capability 必须标为 `explicit-only` 或 `unresolved`，不能猜测完整依赖图。

`SourceUniverse` 分别计算 root-resolution、candidate-scan、AST-classification 和 symbol-identity 完整性。生成目录、系统 SDK、依赖缓存和二进制包不因出现在 include/import 路径中自动成为递归扫描根；只有直接目标、项目/依赖元数据或显式范围证明其中存在相关源码时纳入。解析缓存只按输入内容指纹和时效加速，可删除重建且不裁决范围；缺失、陈旧或未解析的适用根使不存在/全集结论降级为 `scope-incomplete`，调用方主动排除或替换适用根则标记为 `scope-bounded`。

## DES-SQG-020 默认范围、显式组合与模型感知

- 状态: confirmed
- 满足: AC-SQG-002, AC-SQG-003, AC-SQG-007, AC-SQG-014, AC-SQG-015, UDES-SQG-018, UDES-SQG-019

公开关系命令的目录输入可省略。默认 resolver 先使用源码位置；没有位置时使用调用工作目录，然后向最近的项目/语言清单、workspace 配置和编译元数据扩展。找不到任何正式元数据时，以规范化工作目录作为一个递归 `fallback` 根继续查询而不是拒绝。默认解析在关系查询内部完成；独立 scope/capability 读取只服务诊断和机器消费，不成为正常调用前置。

范围组合内部使用四种不重叠语义，正式参数名由 TSQG-106 冻结：`auto` 使用默认解析，`augment` 把重复的文件或目录加入自动范围，`exact` 只使用显式文件或目录，`exclude` 从前述选中集合移除根或子树。当次显式输入优先于自动元数据，自动元数据再落到 cwd fallback；生成的根集合始终是派生物。Windows 路径按绝对规范路径、大小写不敏感身份和解析后的 junction/symlink 目标去重，但相同库的不同实际路径或版本保持独立 root identity。

第一条纵向闭环通过命令输入表达显式范围，不新增配置文件。现有 `.srcq.yml` 仍只拥有模型输出默认值；真实重复使用证明项目级根例外能降低完整链路成本时，才允许另行裁决是否在该既有配置 owner 中增加版本化 scope 字段，不能另建第二份目录状态或把自动发现结果写回配置。

resolver 同时为每个根记录 `selected-by` 和 coverage：自动解析缺少适用根是 `scope-incomplete`；调用方主动采用 `exact` 或 `exclude` 则是 `scope-bounded`，可在该显式范围内给出完整结果但不外推到依赖全集。定义查询按 anchor/owner/direct-dependency 优先级扩展并在当前证据足够时停止；outgoing 先处理定义正文，再只为未决目标扩根；references 和 incoming 若请求全集则批量扫描全部选定源码根。该关系感知策略只改变扫描调度，不改变所选范围或隐藏未扫描根。

model renderer 在普通单根、完整且无歧义时省略范围信封。多个根实际贡献结果时用本次稳定短别名标注路径；`scope-bounded`、`scope-incomplete`、零结果或预算未覆盖全部选定根时，追加一行最短范围摘要，并在可恢复时提供携带原查询的完整目录调整命令，但不得复用只表示同快照分页的 `@next`。machine 面始终保留 root identity、canonical path、来源、选择原因、扫描状态和 unresolved inputs，分页沿同一 SourceUniverse snapshot 继续，不重新发现或改写目录集合。

## DES-SQG-021 共享关系骨架承载语言等价适配

- 状态: confirmed
- 满足: REQ-SQG-002, AC-SQG-010, AC-SQG-011, AC-SQG-012, AC-SQG-013, AC-SQG-014, AC-SQG-015, AC-SQG-016, UDES-SQG-020

`symbol_query` 继续唯一持有命令解析、`SourceUniverse`、候选数据模型、批量 AST 扫描、单次调用缓存、调用图展开、预算和 model/machine 输出；不得为每种语言复制查询或图算法。共享 typed relation 层只归一化调用、接收者、绑定、词法 scope、当前类型和 callable owner 的中间表示，Go、Python、Rust、JavaScript、TypeScript 适配器各自声明 AST 节点、限定名、显式类型与构造语法。语言适配器只在同一词法范围、调用前可见且唯一的源码证据上生成 `typed-member-candidate` 或静态限定候选，冲突、越界和动态形式保持 `semantic-unknown`。

`SourceUniverse` 在既有自动/追加/精确/排除组合中调用语言项目 resolver。resolver 只读取已存在的 manifest、workspace 与本地路径引用，返回规范化源码文件或源码根、来源和 unresolved issue；不写配置、不持久化发现结果、不扫描整盘，也不启动语言工具。公共范围 owner 统一计算 `resolved`、`bounded` 与 `incomplete`，语言 resolver 只负责自身元数据语义，避免 C++、C# 或某个包管理器规则进入公共路径。

TypeScript 作为首个纵向消费者验证共享 typed relation 中间契约，因为显式类型和 `new` 初始化能直接区分适配器缺口与公共图算法；该闭环成立后，JavaScript 只复用其无类型语法与构造推断部分，Python、Go、Rust 分别接入自身 grammar 和项目 resolver。共享层反例会熔断全部横向扩展；单语言差异失败只回到该适配器，不借其他语言通过降低其证据边界。

## DES-SQG-022 共享双向调用与显式清单范围合同

- 状态: confirmed by isolated prototype
- 满足: AC-SQG-011, DES-SQG-016, DES-SQG-018, DES-SQG-019, DES-SQG-021

`symbol calls` 的单方向公开合同继续使用 `srcq.symbol.calls/v1`；`--direction both` 使用独立的 `srcq.symbol.calls/bundle/v1`，不得改变或包裹既有 v1。bundle 只保存一次规范化 query、语言、source scope、root 与共享 deadline，incoming/outgoing 分支分别保存 children、nodes、truncated、time-limited、scan、exit 和 evidence，使任一分支都能机械还原为旧 v1，并允许两方向具有不同的 partial 状态。共享执行只复用解析、范围发现和不可变扫描证据，方向遍历、预算消耗与失败边界仍独立可见。

显式项目文件范围通过通用 `--source-manifest PATH` 进入现有 `SourceUniverse`，格式解释由具名 adapter 持有。首个 `vcxproj-direct-items/v1` 只读取直接 `ItemGroup` 下的 `ClCompile`/`ClInclude` 项及可静态应用的最小排除，不执行 import、属性求值、条件矩阵或完整 MSBuild；其完整扫描只表示覆盖该次 `bounded` 直接项集合，不提升为工程完整性。不得自动猜测最近项目文件，也不得把 manifest 参数复用到 `rg`/`fd` 命令域。

关系输出只证明范围、定义候选、节点、边和各分支完整性；guard、effect、fallback、数值与其他行为语义继续由一次有界源码读取承担。skill 只有在一次限定名 bundle 已能替代后续关系发现、且只保留一次行为读取的配对实验中同时保持质量并降低实际价格时才可更新；工具合同成立不自动证明模型策略成立。

## 4. 版本与迁移边界

当前以 ripgrep 15.1.0、Codex PATH 中的 ripgrep 15.2.0、fd 10.4.2 和迁移前已验证的 ast-grep 0.41.1、0.42.0、0.44.1 标记 Windows 行为证据；这些身份限定各项测试结论，不定义允许运行的连续或离散版本范围。完整兼容表示可启动后端的公开命令都能通过相应命令域调用并保持原生语义，不表示所有模式都能结构化压缩；未验证版本的质量声明只覆盖本次实际输出和退出，不能外推未执行模式。`tools/srcq/Cargo.toml` 的 workspace package version 是当前 srcq 候选版本的唯一默认来源；构建参数只允许显式制作另一个已声明的 srcq 版本，不能长期用覆盖值掩盖源码、README、SBOM、release helper 与运行时版本不一致。

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
| 完整兼容退化为不完整 parser | 模式与实际输出能力矩阵、argv 透明传递、透传/产物/只读安全降级和多版本真实引擎测试；版本不作运行门禁 |
| 更短输出丢失必要证据 | 先固定 EvidenceSignature，只比较语义等价表示 |
| fd tree 路径歧义 | 紧凑基数树、按需根/类型标记、可逆转义和 model/machine round-trip 性质测试 |
| 为机器稳定性把冗余 envelope 常驻给模型 | 三输出面分离、字段准入审查、默认语义与异常式回执；用实际 model renderer 计成本 |
| 简单查询承担固定成本 | srcq 内部提供轻量执行与稀疏 renderer；裸输出仅作为等价候选，不建立绕过网关的第二入口 |
| 全量 LSP 工具 Schema 在无关任务中常驻 | 先验证 Codex 原生延迟发现；不成立时使用 `srcq lsp` 只读降级路线，以总 Token 与回合验收 |
| 为缩小 Schema 将 LSP 压成弱类型万能工具 | 保留完整协议注册和读/预览/应用标注；只改变模型侧暴露时机 |
| 基准 agent 受对照输出或协调方干预 | 新鲜 subject、单向监控、冻结 capsule 与独立 audit |
| 环境差异被误归因给候选 | 环境树 hash、允许差异清单、只读项目快照和身份不等即降级结论 |
| 测试资产增加 Codex 运行时体积或 Token | 测试 owner 固定在 development，共享 payload 过滤并清理旧受管理副本 |
| PATH 中的 srcq 缺失、被同名程序遮蔽或版本漂移 | 安装状态、`srcq --version`、`srcq doctor` 与发布身份读回；不回退到 skill 私有副本，PATH 变化后重启消费者进程 |
| 为绕过适配困难过早分叉上游源码 | 以可重复阻塞、根因和外部方案排除为技术门槛，再取得用户针对该次升级的明确同意；此前不拉取源码，获准后固定版本、补丁、供应链、更新和退出责任 |
| 当前目录或单一 workspace 漏掉外部源码 | `SourceUniverse` 消费已有多根、编译/响应文件和语言依赖元数据；范围未闭合时禁止不存在与全集声明 |
| 自动发现把 UE、SDK 或依赖缓存变成无界扫描 | 根按来源与源码属性分类，只扫描与当前目标有关的已解析源码；不默认扫描整盘、启动构建或下载依赖 |
| 每次查询都要求模型预先编排目录 | 目录省略即走 anchor/cwd 默认 resolver；追加、替换与排除使用不重叠语义，异常时返回携带原查询的单一继续动作 |
| 显式窄范围被误报为整个依赖图完整 | `scope-bounded` 与 `scope-incomplete` 分离，全集结论同时声明选定范围与依赖宇宙边界 |

## 6. 设计完成判定

实现闭环要求 rg/fd 全部公开模式有持久分类，各视图按自身语义单元给出正确总量、分页与完整性，fd 紧凑树可逆；AST 现有 CLI、profile、cache、fingerprint、process、rewrite、TTY/LSP、machine schema、诊断和发布合同逐项未退化。P16 还须证明目录省略时能从源码位置或 cwd 直接完成基础查询，显式追加/替换/排除保持确定语义，`SourceUniverse` 能跨当前目录恢复代表消费者的外部源码，并分别报告根解析、候选扫描、AST 分类和身份完整性；缺失、未解析或主动排除的适用根不得产生越界的不存在或全集结论。所有模型可见输出族必须完成字段准入审查，model/machine/native 三面不混用，普通成功不重复机器 envelope，异常回执仍足以分页、判断截断和恢复；自动完整闭环不得放宽多来源或未知大结果，显式控制面不得被自动策略改写。候选选择按实际 model 字符串，定向 round-trip、语义等价和真实 Codex 运行均通过。命名、安装生命周期、消费者退出和 LSP 渐进暴露的既有闭环继续有效。默认外部适配若遇到阻塞，只有 DES-SQG-013 的升级证据、生命周期和退出条件全部落实后才可把改造版上游纳入完成范围。

P10 最终 identity `0cfb8919…59d5` 已由 12/12 required、12/12 行限、完整 usage、detached audit 和 capsule 验真证明质量；总 Token `1,066,470`，比 P9 同质量候选低 `7.31%`。耗时较 P9 高 `32.38%`，因此设计完成结论只成立于质量和 Token 两个更高优先级，不声称速度改善。当前没有可重复共享机制支持继续增加规则、接口或默认预算，达到当前 corpus、模型、项目快照和 Provider 条件下的收益边缘。项目真源已完成；Codex 安装态仍保持上次发布版本，任何后续发布须取得当次明确授权。
