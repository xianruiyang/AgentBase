# 统一源码查询网关分支方案

## 1. 文档职责

本文件把 [current-state.md](current-state.md) 的已确认差距投影为可执行方案。任务合同见 `tasks/`，阶段顺序和闭环见 [plan.md](plan.md)。所有方案均受分支隔离约束；通过验证前不改变总体需求、正式 skill 或 Codex 安装态。

## SOL-SQG-001 固定后端、AST 与历史证据基线

- 状态: verified
- 解决: 已闭环的 P0 基线与 benchmark owner
- 满足: DES-SQG-001, DES-SQG-003, DES-SQG-010
- 依赖: AC-SQG-004, UDES-SQG-007, UDES-SQG-008

冻结 rg、fd、ast-grep 的精确版本、公开模式、help/schema、原生 argv、输出和退出 oracle；把现有 sgy AST 可观察合同变成可重复非回退基线，并把历史总 Token 结果登记为带证据上限的只读输入。随后在现有 `development/code-search-benchmark` owner 内建立绑定源码快照的 corpus、隔离 runner/monitor 和 detached audit capsule，不在分支目录或发布 payload 复制第二套执行器。

预期结果是任何实现前都能回答“要兼容什么、AST 什么不能改变、历史数字能证明什么、如何重复测量”。验证覆盖原生版本读回、现有 AST 定向/集成/真实引擎行为、corpus oracle 和 monitor 隔离；环境身份不完整时只降低结论，不伪造可比性。

## SOL-SQG-002 提取不改变 AST 的公共执行原语

- 状态: verified
- 解决: 已闭环的公共执行边界
- 满足: DES-SQG-001, DES-SQG-002, DES-SQG-004, DES-SQG-005
- 依赖: SOL-SQG-001

逐项比较进程、cwd、argv、stdin/TTY、stdout/stderr、退出、spool、snapshot、cursor、预算、诊断和 artifact 的生命周期与失败语义；只把三个后端真正相同的职责提取为内部原语。AST 命令、serializer、cache、profile 和 fingerprint 保持原位，rg/fd 使用新的 EvidenceSignature 与 renderer 注册。完整执行事实先由内存对象持有，只有分页或显式完整诊断产生 snapshot 消费者时才计算身份并持久化，避免为完整短查询建立不可访问状态；完整诊断仍来自同一事实对象，不建立第二套事实源。此前默认模型回执投影总量和三类完整性是已实现的阶段性边界，新的默认 model 投影由 SOL-SQG-010 取代。

验证以冻结 AST oracle 无差异为先，并覆盖 rg/fd 的 0/1/N/N+1、native error、转换失败、截断、snapshot 和精确 cursor。不能证明同责的实现留在 backend，不以代码复用率作为验收条件。

## SOL-SQG-003 建立 fd 完整兼容与可逆低成本输出

- 状态: verified
- 解决: 已闭环的 fd 命令域与可逆表示
- 满足: DES-SQG-003, DES-SQG-004, DES-SQG-005, DES-SQG-006
- 依赖: SOL-SQG-001, SOL-SQG-002

实现 `sgy fd exec/defaults/doctor`，透明保留 `--` 后 argv，并按精确版本矩阵把公开模式分类为结构化、有界文本、artifact 或透传。普通路径结果用 NUL 分隔输入建立根别名与可逆 trie，同时生成 flat/tree 候选；只有 EvidenceSignature 相同且预计 Token 更低时选择 tree。

验证覆盖文件/目录、0/1/N/N+1、多根、绝对路径、Unicode、空格、同名目录、ignore/hidden、print0、exec/batch、help/version 和 round-trip。tree 不可还原或不更短时必须回到 flat。

## SOL-SQG-004 建立 rg 完整兼容与按证据单元投影

- 状态: verified
- 解决: 已闭环的 rg 命令域与自适应表示
- 满足: DES-SQG-003, DES-SQG-004, DES-SQG-005, DES-SQG-007
- 依赖: SOL-SQG-001, SOL-SQG-002

实现 `sgy rg exec/defaults/doctor`，普通 batch 通过 ripgrep 原生 JSON 事件解析 match/context/summary/error，并提供 locations、files、grouped、summary、lossless 与 raw 候选；特殊公开模式按矩阵显式进入结构化、有界文本、artifact 或透传，不再由 Python wrapper 猜测 argv 和前缀。每种 view 先形成自己的证据单元再分页：files 对匹配文件去重，locations 排除 context，正文视图保留 match/context，summary 对完整集合聚合且不产生续页。

定向验证增加“summary 不续页、files 总量按文件、locations 不产生 context 空页”的真实反例；完整验证仍须覆盖 fixed/regex、多 pattern、glob、上下文、no-match、count、文件列表、replace、passthru、preprocessor、显式 JSON、sort、help/version、长路径、长行、非 UTF-8 与子匹配。无匹配、原生错误、转换错误和结果省略必须可区分。

## SOL-SQG-005 复核 AST 并收敛三后端诊断、版本与供应链

- 状态: partially_superseded
- 解决: 已闭环的 AST 非回退、诊断与候选供应链
- 满足: DES-SQG-001, DES-SQG-002, DES-SQG-009
- 依赖: SOL-SQG-003, SOL-SQG-004

用 P0 oracle 复核 AST 全部当前入口，只在序列化和行为等价时让 AST 复用公共原语；统一读取三个后端的版本身份、缺失、输出不兼容、透传和发布来源，但不统一它们不同的 cache、serializer 或副作用语义。srcq workspace package version 是默认 release、README、Cargo metadata、release helper、SBOM 与运行时版本的唯一来源；显式构建覆盖只制作被调用方主动声明的版本，不能承担日常版本真源。当前源码、Windows release、来源、许可证、manifest、payload 与安装 smoke 已统一到 `0.2.0` 并通过当时影响验证；仅新的 advisory scan 因宿主没有 `cargo-audit` 而未刷新。OBS-SQG-010 已推翻“精确后端版本可作运行门禁”的部分，AST 非回退与 srcq 自身供应链结论继续有效，后端运行兼容由 SOL-SQG-012 取代。

任何非必要 AST 公开行为变化都使方案回到公共边界裁决。最终证据必须分别覆盖权威 owner 和三个实际后端，不能用 rg/fd 通过推断 AST 仍有效。

## SOL-SQG-006 建立统一 skill 并退出旧入口

- 状态: verified
- 解决: GAP-SQG-002
- 满足: DES-SQG-008, DES-SQG-009
- 依赖: SOL-SQG-003, SOL-SQG-004, SOL-SQG-005

正式 `source-query` 保留一次精确文件名、已知文件内少量文本和天然有界读取的原生快路径；只有全集、不存在证明、大结果压缩、目录树、AST、缓存或分页确实需要时才承担网关成本，真实符号身份改变结论时才升级 LSP。AST 规则已完整迁入按需引用，旧三个查询 skill、rg Python wrapper 与私有运行时已经退出。

正式 payload 只含一个主文件、metadata 与三份按需引用；插件和直接兼容部署合同禁止复制二进制、测试或 benchmark 资产。Codex 安装态仍由逐次发布授权决定，不由项目真源变化自动更新。

## SOL-SQG-007 以当前候选身份的隔离总成本证据裁决采纳

- 状态: verified
- 解决: GAP-SQG-003, GAP-SQG-002
- 满足: REQ-SQG-001, AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-004, DES-SQG-010
- 依赖: SOL-SQG-001, SOL-SQG-005, SOL-SQG-006

先运行后端定向、公共契约、性质/fuzz、真实版本矩阵和 detached 路由评估，再由正式 monitor 运行相同 experiment identity 的真实 Codex 对照。独立 auditor 逐案裁决质量并复算 `input + output` 总 Token，质量相同后比较 Token，前两项不退化后再比较 wall time；失败、回退和无收益样本都保留。

历史实验先证明只压低工具输出不足以降低总成本，再把普通查询移出 skill 触发面，并以跨根权威范围、关系端点和最小回答约束修复质量。当时候选在核心与严格语义均 12/12、严格整体 11/12 的前提下，实际总 Token 为 `1,146,601`、耗时为 `404,603 ms`；相对不再重跑的历史五-skill 记录方向性降低 `0.91%` Token 与 `20.43%` 耗时。该结论既缺少严格同 identity control，又不覆盖后续稀疏回执、语义投影、按需 snapshot 和单一版本来源改动，只能作为下一轮测试的历史输入。

供应链与 detached 路由已经刷新；早先 candidate-only monitor 的 TLS 超时和 usage 缺失作为失败路径保留，回答合同也已把 prompt 必答内容与 supporting facts 显式分开。继续加重全局回答规则既增加 Token 又没有改善用户实际必答内容，因此该变体已经退出。

用户允许的新同 identity 对照由同一当前安装态生成 control/candidate，24 次 A-B-B-A 运行全部正常退出且 usage 完整。独立 detached 审计确认两边质量均为 12/12；candidate 总 Token 降低 `31.186%`、总耗时降低 `20.126%`、工具调用减少 101 次，六个 case 的两次聚合均改善。按质量、Token、速度顺序保留当前候选并停止基于该语料继续调优；结论只覆盖本次冻结 identity，实际发布仍需当次用户明确同意。

## SOL-SQG-008 将迁移前 sgy 原子收敛为独立 srcq Windows CLI

- 状态: verified
- 解决: GAP-SQG-004, GAP-SQG-005
- 满足: DES-SQG-011, UDES-SQG-009, UDES-SQG-010
- 依赖: SOL-SQG-005, SOL-SQG-006

仓库运行时 owner 已原子更新为 `tools/srcq`、`srcq.exe`、`%LOCALAPPDATA%\Programs\srcq\current`、srcq 安装状态、归档、包名、manifest、来源、文档和验证。安装态固定为用户级受管目录与唯一 PATH 项，验证覆盖全新安装、状态读回、幂等重装、可恢复升级、保留无关 PATH 的卸载、默认保留 cache、显式删除 cache，以及新进程中的 `srcq --version` 和 `srcq doctor`。没有 `sgy.exe` 兼容别名或旧受管安装轨道。

正式 skill 直接调用 PATH 中的 `srcq.exe`，缺少 srcq、受管安装损坏、srcq 命令身份错误或同名遮蔽时只返回安装、升级或重启恢复动作；外部后端版本差异不触发安装恢复。Skill 内置二进制及其 runtime manifest、来源和许可副本已删除；部署与插件 payload 不复制 srcq/sgy，也不保留私有 fallback。安装、升级或卸载一次即可穿透所有消费者，只有 `tools/srcq` 维护运行时来源和生命周期。

## SOL-SQG-009 采用原生渐进 LSP 语义查询

- 状态: verified
- 解决: GAP-SQG-006
- 满足: AC-SQG-005, DES-SQG-012, UDES-SQG-011
- 依赖: SOL-SQG-006, SOL-SQG-008

`vscode-lsp-mcp` 内部继续维护完整的 18 工具注册、精确 Schema、安全标注和独立验证；Codex 模型侧使用宿主原生延迟目录。Skill 只持久化最小升级和停止原则，具体 LSP 命令与参数按需读取，不默认先跑 health、capabilities 或工具全览。

无 LSP、单项 LSP 和多阶段 LSP 三类真实 Codex 路径分别只调用 0、2、3 个必要 MCP 能力，质量、完整 usage 与独立审计通过。因此保留 MCP，不新增万能调度工具或 `srcq lsp`；后者只在未来宿主行为回退且同身份实测不达标时重开。rename、Code Action、format、command 和 debug 继续由 `symbol-structure-workflow` 承担，不迁入 Source Query Gateway。相对总 Token 收益仍与整体同身份 control 一并受 SOL-SQG-007 的证据边界约束。

## SOL-SQG-010 以查询意图入口驱动自适应模型输出

- 状态: verified
- 解决: GAP-SQG-007
- 满足: REQ-SQG-001, AC-SQG-001, AC-SQG-002, AC-SQG-006, AC-SQG-007, AC-SQG-008, UDES-SQG-002, UDES-SQG-003, UDES-SQG-004, UDES-SQG-006, UDES-SQG-013
- 依赖: SOL-SQG-002, SOL-SQG-003, SOL-SQG-004, SOL-SQG-005, SOL-SQG-007

保留当前内部 `EvidenceSignature`、退出、完整性、快照与诊断事实，由 srcq 统一接管 rg、fd 与 ast-grep，正式规则不再路由到裸工具。rg/fd 普通模型入口收敛为 `srcq <rg|fd> <native argv...>`：模型只表达查询对象、范围和原生语义，不再为普通查询携带 `exec`、argv 分隔、view、limit、heading、receipt 或正文预算。网关控制放在 backend 前的独立显式控制面；machine、native、artifact 和定向证据投影仍可覆盖自动规划。AST 继续沿用既有 `srcq exec/defaults/cache/process` 与强制 argv 边界，不为统一表面改写成熟合同。本方案明确取代 SOL-SQG-006 中面向模型的裸 rg/fd 快路径；已知文件正文的直接有界读取不属于底层搜索工具绕行。

统一 model planner 在取得真实结果后才选择表示，只向模型输出干净的证据正文；正常成功和完整不带 envelope 或回执，只有截断、分页、错误、歧义与恢复需要才追加最短差异信息。现有稳定 JSON/YAML、完整 receipt、lossless、schema/capabilities 和 round-trip 能力归入显式 machine/diagnostic 视图；原生字节、TTY/LSP、写入与 artifact 继续走 native/artifact 视图。模式选择不得改变结果集合、顺序、位置、缓存或副作用。

fd model renderer 使用可逆紧凑基数树并合并单子链；rg 按正文、位置、文件、count 的真实证据单元生成原生等效文本、单行、文件 heading、分组正文、路径树以及“路径树 + 文件 heading + 位置叶子”等候选。同文件多位置先消除路径重复，多文件共享长目录时再压缩目录，离散单位置不强制树形；auto 只在 EvidenceSignature 相同后按实际模型文本成本选择，裸输出没有预设优先级。内部安全预算代替模型预填输出限制，短结果完整返回，大结果按证据单元分页并只给必要续点。AST 保持 profile/cache/rewrite 和 machine schema，只让模型投影把源码正文表达一次，并按当前需求显示捕获。`doctor` 成功只给必要健康结论，偏差时才给 observed/expected、实际路径与恢复；`defaults` 只显示实际注入、抑制或不可推导差异。cache/process/artifact 的模型回执按同一准入规则审查，显式请求完整内容时不误删请求对象。

已完成的三输出面、字段准入、renderer、内部预算和精确分页继续保留。OBS-SQG-010 推翻了当前实现已可进入采纳对照的判断：后端版本拒绝、普通入口最小语法缺失和按请求措辞过早升级 AST 会制造失败回合。修订按 SOL-SQG-012 至 SOL-SQG-014 纵向闭环，随后迁移当前消费者并冻结新 identity；只有这些机制变化并通过影响验证后才恢复受监控隔离 Codex control/candidate。质量持平后比较端到端总 Token，再比较同 service tier 耗时；字符级样本只用于定位机制，不作为完成证据。

## SOL-SQG-011 为真实后端阻塞保留条件性源码改造路线

- 状态: conditional
- 解决: 仅在外部适配被证据证明无法关闭 GAP-SQG-007 时启用
- 满足: DES-SQG-013, UDES-SQG-014
- 依赖: SOL-SQG-010

当前方案仍以已安装的 rg、fd 与 ast-grep 二进制为执行后端，不拉取或内嵌上游源码。若实施中出现可重复的必要验收失败，先形成升级裁决包：固定复现、上游内部根因、外部适配方案及其失败证据、目标 revision、许可证与维护成本，并提交用户讨论。只有裁决确认源码级修改是满足目标的最低长期成本方案，且用户针对该次升级明确同意后，才允许拉取源码、重投影任务图并实施 Windows 定向补丁；未获同意时保持当前边界，不先行下载或建立 fork。

改造后的后端仍封装在 `srcq.exe` 内部，不增加模型入口、用户安装入口或行为真源。实现必须固定来源与补丁身份，覆盖上游行为矩阵、srcq 投影、release manifest、SBOM、安装升级、漏洞响应和退出验证；能回到无补丁上游时删除分叉，不把临时 fork 永久固化为兼容负担。

## SOL-SQG-012 以实际输出能力取代后端版本许可

- 状态: verified
- 解决: GAP-SQG-007
- 满足: DES-SQG-003, DES-SQG-007, DES-SQG-009, DES-SQG-013, UDES-SQG-002, UDES-SQG-014
- 依赖: SOL-SQG-010

删除 rg、fd 与 ast-grep 精确版本的运行拒绝和 `doctor` 失败判断；版本只进入显式诊断、测试身份与证据上限。普通调用直接执行实际后端并按输出合同解析，成功时沿用当前自适应投影；输出不能安全结构化时，确认无副作用且可确定重放的读取模式在同一 srcq 调用内降级为原生文本，可能启动外部程序、写入或改变状态的模式执行前即进入 native/artifact，不得自动重复运行。转换失败、无匹配和原生错误继续分离，未知输出不能伪装成成功空结果。

验证覆盖当前真实 rg 15.1 与 Codex PATH 中 rg 15.2、fd/ast-grep 已有矩阵、伪造未来版本字符串但同协议输出、结构字段变化、原生错误、只读降级和有副作用不重放。只有公开外部边界无法满足必要验收且根因位于上游内部时，才重新进入 SOL-SQG-011 的用户裁决；本轮不拉取源码。

## SOL-SQG-013 固化普通查询的最小语法与定向恢复

- 状态: verified
- 解决: GAP-SQG-007
- 满足: DES-SQG-003, DES-SQG-008, DES-SQG-009, AC-SQG-002, AC-SQG-008, UDES-SQG-013
- 依赖: SOL-SQG-010

全局常驻规则只增加完成普通查询不可缺少的 `srcq fd <fd argv...>` 与 `srcq rg <rg argv...>` 两个正式语法；简单文件发现和文本定位不加载 source-query skill，skill 继续只承载完整性、分页、特殊协议、AST 与 LSP 升级。CLI 对可识别的 `files`、`--files` 等错形返回指向唯一正式入口的一行修正，不再落入旧 AST 分隔符错误，也不新增别名、自动猜 backend 或第二语法。

验证覆盖无 skill 的文件发现与文本定位、正确普通入口、错形一次恢复、rg/fd 原生同名参数、未知错形和 AST 旧入口；成功路径不得增加帮助、schema 或固定回执。独立路由只检验模型是否无需 help/doctor 即使用正确语法，不把具体 benchmark 答案写入规则。

## SOL-SQG-014 以证据缺口裁决 AST 升级

- 状态: verified
- 解决: GAP-SQG-007
- 满足: DES-SQG-001, DES-SQG-008, DES-SQG-009, AC-SQG-001, AC-SQG-002, AC-SQG-006, UDES-SQG-006, UDES-SQG-013
- 依赖: SOL-SQG-010

把“完整定义”从 AST 触发条件中移除：已知名称先用文本定位和有界源码读取，命中少且边界可由实际源码确认时立即闭环；文本证据仍不能可靠确定语法边界、候选有歧义、读取被截断，或任务确需结构关系、控制流、rule/rewrite 时才升级 AST，真实身份、重载、类型或精确引用需要语义裁决时升级 LSP。AST 无匹配后只有取得会改变 pattern 的实际语法证据才能再次查询，否则回到文本路径，不允许同一信息下连续试探。

验证同时覆盖已知唯一函数完整定义、长或截断函数、同名/重载、宏或嵌套结构、跨结果结构关系、AST 空结果和 LSP 身份分歧；验收对象是质量、工具回合与端到端 Token，不以减少 AST 调用数量本身判定正确。
