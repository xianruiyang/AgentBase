# 统一源码查询网关分支实施计划

## 1. 文档职责

本文件只安排 [requirements.md](requirements.md)、[user-design.md](user-design.md) 与 [design.md](design.md) 已定义的候选分支工作，不创建总体项目需求。P0—P5 的历史 sgy 实现已形成，但后续实现变化、正式 `srcq` 命名决策、LSP 渐进暴露需求与语义投影反例使 P3、P4、P5 及 P6 完成证据重新打开；主线采纳与 Codex 发布仍待用户分别授权。

## 2. 推进原则

- 先保证原生语义、答案质量、授权、安全和可维护性，再降低端到端 Token，最后比较速度。
- AST 以当前 sgy 行为为冻结基线；新增 rg/fd，不能把 AST 迁入另一套命令、profile、cache 或 process 设计。
- 每个 backend 先闭环一条真实命令、结果与 oracle，再扩展完整命令矩阵。
- 只抽取已证明相同的内部职责；公共抽象导致 AST 行为变化或 backend 语义丢失时立即回退设计。
- 受影响模块先做定向验证；公共协议、发布合同或正式分发范围改变时才扩大。
- 历史结果按 [benchmark-protocol.md](benchmark-protocol.md) 的身份边界冻结复用；不能证明同一 experiment identity 时只作为现实依据，不拼接为新对照。
- 正式产品与唯一命令为 Source Query Gateway / `srcq.exe`；`sgy` 只是迁移前实现和历史证据名称，安装发布前原子迁移且不保留兼容别名。
- srcq 作为独立 Windows CLI 只安装一份；先验证安装态并让消费者改用 PATH 入口，再退出 skill 内置运行时，不保留双版本 fallback。
- LSP 完整工具注册表可作为协议真源，但不能因此全量常驻模型上下文；先验证 Codex 原生延迟发现，不成立时才实现 `srcq lsp` 只读降级路线。

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

当前轮 candidate-only 全量运行有 12 个计划样本，其中 11 个 usage 完整，完整样本合计 `1,004,033` Token；另一次受 TLS 重连影响超时，故不能把该部分总数与冻结消融比较。关系 case 的受影响补测确认最终保留规则下两次核心回答充分；继续强化回答规则把两次成本从 `157,053` 增至 `170,824` Token，却没有增加 prompt 必答信息，已按收益边缘退出。corpus 已显式区分 prompt 必答内容与 supporting oracle facts，下一次有效收益实验必须使用新 identity 并同时包含 control/candidate。

### 3.5 对本计划的约束

- 统一包装必须减少完整模型路径，而不只是缩短 stdout；固定 skill 成本、失败和回退全部计入。
- 简单文件/文本任务必须保留低固定成本路径；结构和 LSP 只在改变质量或能由复用抵消成本时升级。
- 不用首轮安装态、第二轮候选和消融之间的跨快照差额推导单一机制因果；它们只限定当前改进方向。
- 新候选必须通过 [benchmark-protocol.md](benchmark-protocol.md) 的隔离、监控和独立审计流程；旧数据不因缺少完整 identity 被伪装成可逐字复现实验。

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
| TSQG-042 | 完成三命令域诊断、单一版本来源和 Windows CLI 生命周期 | TSQG-022, TSQG-032, TSQG-041 | capability/doctor、release 与安装生命周期证据 | workspace、README、metadata、helper、SBOM、manifest 与运行时版本一致；全新安装、状态、幂等重装、可恢复升级、卸载、PATH 与新进程读回通过；缺失引擎、错误版本、输出不兼容和透传状态可区分，AST 现有诊断合同不变 |
| TSQG-043 | 将迁移前 sgy 产品身份原子迁移为 Source Query Gateway / `srcq.exe` | TSQG-042 | `tools/srcq`、`srcq.exe`、安装目录/状态、归档、包名、skill 调用、文档与证据的唯一正式身份 | 当前 sgy 行为 oracle 在新命令下等价；发布 payload、PATH 和安装状态不含 `sgy.exe` 别名、第二运行时或旧受管安装遗留 |

P4 闭环：同一 srcq 二进制在不改变已验证 sgy 行为合同的前提下完成 fd、rg 与 AST 真实任务；rg/fd 共享合适的基础设施，AST 继续使用原有设计和安全合同；正式产品身份、安装、升级、查询和卸载只剩 `srcq`，不存在 `sgy.exe` 双轨入口。

### P5 Skill、消费者与重复入口退出

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| TSQG-050 | 建立精炼的统一查询 skill 和按需 backend 引用 | TSQG-023, TSQG-033, TSQG-043 | 只调用 PATH 中 srcq.exe 的候选 skill | 简单快路径、完整性、tree、AST、LSP 边界和 PowerShell 非触发路由通过；缺失、错误版本或 PATH 尚未刷新时只给安装、升级或重启恢复动作 |
| TSQG-051 | 将现有 AST skill 语义原样迁入按需引用 | TSQG-050 | AST 规则等价映射 | 迁移前 sgy 命令结构、profile、cache、process、rewrite 和安全边界在 srcq 命令前缀下无丢项；独立行为证据等价 |
| TSQG-052 | 更新消费者并退出已被替代的 rg/fd wrapper、旧 skill 与内置 sgy | TSQG-050, TSQG-051 | 唯一职责与运行时方向 | 保留 AST 行为合同并统一为 srcq 命令；先验证 PATH 运行时再删除同责 Python wrapper、重复规则和 skill 内置 sgy，不存在私有 fallback 或悬空引用 |
| TSQG-053 | 更新分支内 srcq 发布与候选 payload 合同 | TSQG-052 | 独立 srcq Windows release、安装状态和不含二进制的 skill payload | 二进制 hash、源码 revision、archive、安装状态与真实运行读回一致；skill payload 不含 srcq/sgy、tests、fixtures、benchmark、runner、corpus、结果或 audit 资产，旧直接安装副本被移除 |
| TSQG-054 | 冻结 LSP 工具暴露基线和三类真实 Codex 语义查询样本 | TSQG-050 | 固定 18 工具公开定义尺寸、活动工具快照、无 LSP/单项 LSP/多阶段 LSP 对照语料 | 记录实际 Input/Output/cached Token、工具回合、耗时和质量；不以 UI 数量或序列化字符数替代端到端成本 |
| TSQG-055 | 验证并收敛 Codex 原生延迟 MCP 工具发现 | TSQG-054 | 宿主能力证据与最小 skill 路由 | 未使用 LSP 时不注入全量 Schema；单项查询不展开无关读取或修改工具；新增发现回合被总 Token 收益覆盖，质量不退化 |
| TSQG-056 | 裁决并闭环 LSP 渐进模型入口 | TSQG-055 | 通过的原生延迟 MCP 方案，或必要时的 `srcq lsp` 只读降级实现 | 原生方案达标时不新增 CLI LSP 入口；不达标时 `srcq lsp` 复用 VS Code companion、认证 IPC、协议验证和 Provider 事实，只覆盖工作区、符号信息、引用、层级和诊断读取，不迁入 rename/code action/format/command/debug 修改职责 |

P5 闭环：查询规则只有一个低成本入口，AST 设计保持，重复的 rg/fd 包装职责退出；srcq 只由 Windows 安装器维护一份，skill 和插件不再复制运行时；LSP 工具只在语义证据真实需要时渐进暴露，原生延迟发现达标时不为形式统一新增 `srcq lsp`，不达标时也只迁入只读查询；总体项目仍未因此自动采纳分支。

### P6 质量、Token、速度与采纳裁决

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| TSQG-060 | 运行 backend 定向、公共契约、性质/fuzz 与真实版本矩阵 | TSQG-053, TSQG-056 | 质量验证结果 | 声称支持的版本和模式全部通过，AST 基线无回退，LSP 渐进入口未破坏 Provider 语义或授权边界 |
| TSQG-061 | 运行 detached skill 路由和行为评估 | TSQG-050, TSQG-052, TSQG-056 | 分支评估证据 | 首次路由、简单非触发、AST/LSP 边界、单项渐进发现和写入安全满足独立 oracle |
| TSQG-062 | 通过正式 monitor 运行真实 Codex 隔离对照 | TSQG-006, TSQG-060, TSQG-061 | 原始事件、环境差异、Input/cached/Output/reasoning/耗时/质量与 audit 结果 | identity 相同的历史基线直接复用；只运行受影响对照，短任务与多查询任务分别报告，失败与回退不丢弃 |
| TSQG-063 | 裁决保留、收紧或退出 | TSQG-062 | 收益边缘结论 | 质量先通过；固定成本无收益则收紧触发，压缩收益不抵成本则不宣称优化完成 |
| TSQG-064 | 请求主线采纳与当次 Codex 发布授权 | TSQG-063 | 用户裁决 | 只有用户确认后才更新总体需求、README、正式 skill 和安装态；Git 按既有授权另行维护 |

P6 当前停在受控收益证据边界：供应链、独立路由和 candidate-only 影响验证已完成，失败与 oracle 争议也已保留并修正；旧 control 按用户要求不重跑，且与当前 Codex、工作区、候选和 corpus identity 不同。继续运行 candidate-only 不能关闭 `AC-SQG-004`，因此 TSQG-062 等待用户决定是否允许一次新的同 identity 对照；TSQG-063、TSQG-064 随之保持未开始。是否进入主线和发布仍由用户单独确认。

## 5. 停止条件

- AST 现有 CLI、profile、cache、fingerprint、process、rewrite、TTY/LSP、诊断或 release gate 任一发生非必要变化时，停止并回到设计裁决。
- 原生命令不能在不改变语义的情况下结构化时使用透传或产物；仍有未分类模式时停止该版本的“完整兼容”声明。
- 公共抽象迫使 backend 复制、丢失特有语义或新增第二状态源时，保留独立实现，不以形式统一为完成目标。
- fd tree 不能机械还原路径或预计 Token 不低于 flat 时不选 tree。
- 真实 Codex 质量退化时先修正质量；质量相同但总 Token 高于冻结消融且无必要证据收益时，继续收紧或退出，不以速度补偿。
- control/candidate 出现 allowlist 外环境差异、subject 接触对照信息、monitor 干预答案、usage 缺失或 audit capsule 不完整时，该实验停止且不得进入收益聚合。
- Plugin 或 DirectCompatibility 候选 payload 中出现测试、fixture、benchmark、runner、corpus、原始结果或审计资产时停止发布，不以它们位于 skill 子目录为理由保留。
- `sgy` 到 `srcq` 未完成全部正式身份的原子迁移，srcq 未通过正式安装、状态、升级、卸载与新进程 PATH 读回，或任一消费者仍依赖 skill 内置副本时，停止运行时迁移与发布，不增加命令别名或双版本 fallback。
- LSP 渐进方案不能证明未用 LSP 时全量 Schema 未进入活动上下文，或发现回合使总 Token 不降反升时，不宣称渐进暴露已完成；进入 `srcq lsp` 降级设计后不得顺带迁入编辑器修改和执行职责。
