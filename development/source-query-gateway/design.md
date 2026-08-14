# 统一源码查询网关设计

## 1. 文档职责与状态

本文件定义满足 `REQ-012` 与 [user-design.md](user-design.md) 的模型设计，状态为 `proposed`。它不证明当前实现已经具备这些能力；当前证据和历史 Token 数据仍以 `development/code-search-workflow-improvement-plan.md` 为来源，实施任务以 [plan.md](plan.md) 为唯一当前计划。

## 2. 设计结论

扩展现有 `tools/sgy`，使其从 ast-grep 专用适配器演化为唯一的模型侧源码查询网关。网关使用一个 Windows 原生二进制、一个公共执行与输出内核和三个相互隔离的 backend：

| Backend | 原生 owner | 网关适配职责 |
| --- | --- | --- |
| `rg` | ripgrep | 文本匹配、文件分组、位置/正文投影和完整性包络 |
| `fd` | fd | 文件/目录发现、根映射、可逆目录树和完整性包络 |
| `ast` | ast-grep | 保留现有结构查询、profile、cache、位置投影和 rewrite 安全能力 |

LSP 保持在 `vscode-lsp-mcp`，只承担真实符号身份、类型、精确引用、层级、诊断和安全重命名。PowerShell 保持 Windows 命令语言职责。网关不自动替模型选择 backend，不签发执行或写入授权，也不判断任务是否完成。

## 3. 权威职责

### DES-SQG-001 公共查询执行内核

- 状态: proposed
- 满足: REQ-012, AC-040, AC-043, AC-044, AC-046
- 关联: UDES-SQG-001, UDES-SQG-002, UDES-SQG-005

`tools/sgy` 作为唯一 owner 维护底层进程启动、cwd、stdin/TTY、stdout/stderr 捕获、超时、退出状态、结果 spool、查询身份、公共完整性包络、上下文预算、诊断、能力探测和发布来源。backend 只解释自己的原生命令与结果，不复制公共预算和输出协议。

### DES-SQG-002 原生命令透明边界

- 状态: proposed
- 满足: AC-040, AC-046
- 关联: UDES-SQG-002

命令形式为 `sgy exec <rg|fd|ast> [gateway options] -- <native argv...>`。`--` 后的 token 以参数数组保留值、顺序和重复项，不经过 shell 拼接。`sgy defaults <backend> ...` 在不执行引擎时返回原始 argv、网关仅为机器读取追加的输出参数、抑制原因和最终 argv。

backend 对每个受支持精确版本维护完整命令矩阵，把调用分为：

1. `structured`：可在不改变搜索、写入或外部执行集合的前提下取得机器输出并压缩。
2. `bounded-text`：原生文本语义可保留，只做字节、行和产物边界管理。
3. `artifact`：二进制或不宜进入上下文的完整结果写入显式产物，stdout 只返回清单。
4. `passthrough`：TTY、LSP 式协议、未知未来模式或显式 raw 请求逐字节透传。

所有原生命令至少属于其中一类。不能结构化不等于不兼容；不得因适配器未知而拒绝原生能力。网关只允许追加已证明不改变原生结果集合的机器输出选项；显式原生选项优先，并在冲突时选择原生输出或 passthrough，不猜测改写。

### DES-SQG-003 最短充分输出规划器

- 状态: proposed
- 满足: AC-041, AC-043, AC-045, CON-001
- 关联: UDES-SQG-003

每个 backend 先从原生命令和调用者的 gateway view/profile 得到 `EvidenceSignature`，明确结果必须保留的路径、类型、位置、正文、捕获、规则、诊断、顺序和完整性字段。只有签名相同的表示才允许比较成本。

输出规划器为实际结果生成适用候选，例如平铺、按文件分组、目录树、仅位置、仅文件、摘要加分页、现有 AST Token-Safe 和 lossless/raw。默认 `auto` 使用随二进制发布的确定性 Token 估算器选择预计成本最低者；估算器名称和版本进入 meta，不强制进入最小 stdout。UTF-8 字节只作为估算器不可用时的退化选择，真实 Codex `input + output` Token 仍是发布收益证据。

调用者可显式选择 `auto`、`grouped`、`tree`、`locations`、`files`、`summary`、`lossless` 或 `raw`。显式选择不能删除原生命令已经要求且影响语义的字段；不适用的 view 返回局部可恢复输入错误，不静默退化为另一种证据。

### DES-SQG-004 公共结果包络与分页快照

- 状态: proposed
- 满足: AC-043, AC-018
- 关联: DES-SQG-001, DES-SQG-003

结构化输出使用一套版本化公共包络，至少包含：schema、backend、engine/version、query identity、native exit、view、roots、total、shown、omitted、result completeness、text completeness、snapshot identity 和 diagnostics。backend 结果字段保留独立 schema，不把文本匹配、路径和 AST 节点伪装成同一种记录。

大结果先完整执行并有界 spool，再从同一不可变结果快照分页或投影；游标绑定 snapshot identity 和 view。分页只节省模型可见上下文，不改变底层查询范围。spool 是本次查询产物，不自动成为当前源码真源；源文件变化后是否仍可作为当前证据由调用方裁决，AST 位置复用继续要求现有文件 fingerprint 合同。

### DES-SQG-005 fd 可逆目录树

- 状态: proposed
- 满足: AC-041, AC-042, AC-043
- 关联: UDES-SQG-004, DES-SQG-003

fd adapter 对默认路径输出使用以下合同：

- 不解析 shell 文本；优先让受支持 fd 产生无歧义的 NUL 分隔路径，再由 adapter 解码。
- 每个显式搜索根分配稳定短别名，路径按原生身份做词法相对化，不用 canonicalize 改写符号链接、大小写或用户给出的根。
- 使用 trie 合并共同目录前缀，文件、目录和其他可识别对象类型保持可区分；多根、绝对路径和根外结果不合并为虚假共同根。
- 名称使用可逆转义，目录树能够机械还原每条完整路径；同一结果生成 flat、grouped 和 tree 后按 Token 估算选择，树不更短时不为形式强制使用。
- 排序稳定且显式；重复记录的处理遵循原生命令语义，不因建树静默去重。
- 预算不足时在公共包络报告 omitted/complete，并在树中使用结构化省略节点；不得把省略节点当作真实文件名。

目录树只压缩表示，不做结果采样。若用户以后需要统计采样，它必须成为不同 view 和不同完整性语义。

### DES-SQG-006 rg 结果适配

- 状态: proposed
- 满足: AC-040, AC-041, AC-043
- 关联: DES-SQG-002, DES-SQG-003

rg adapter 在已验证的普通 batch 搜索中取得原生 JSON 事件，区分 match、context、begin/end、summary 和错误；按文件只输出一次路径，并按 EvidenceSignature 选择行、列、子匹配、正文或文件级结果。`--count`、文件列表、replace 展示、passthru、preprocessor、特殊报告、help/version 与显式 JSON 等模式分别进入命令矩阵，不用一组手写“疑似输出 flag”解释全部 argv。

原生无匹配、执行错误、包装转换错误和结果省略分别保持。N+1 可以判断当前展示窗口是否覆盖全集，但完整执行得到的原生 total 才能证明查询集合完整；任何 native 上限、提前退出或未消费完整流都反映在 completeness，不由可见条目推断。

### DES-SQG-007 AST 能力原位迁移

- 状态: proposed
- 满足: AC-040, AC-043, AC-046
- 关联: UDES-SQG-001, UDES-SQG-005

现有 sgy 的 ast-grep argv 透明传递、profile、safe YAML、cache、fingerprint、`process containing`、`group-locations`、rewrite preview/apply、TTY/LSP、artifact、诊断和发布能力迁入 `ast` backend，不重写已验证算法。新公共包络只抽取跨 backend 的字段；AST 特有 range、metaVariables、rule、severity、replacement 和写入证据仍由 AST schema 定义。

新命令稳定后，项目 skill 和测试迁移到带显式 backend 的入口；旧的无 backend AST 命令不作为长期兼容入口保留。

### DES-SQG-008 单一 skill 与成本路由

- 状态: proposed
- 满足: AC-044, AC-045, AC-006, AC-007
- 关联: UDES-SQG-001

建立一个统一的源码查询 skill，替代 `rg-token-safe`、`fd-usage` 和 `ast-grep-token-safe`。主文件只说明触发边界、backend 选择、公共完整性和修改安全；backend 详细协议按实际选择再读取。

一次精确文件名发现、已知文件中的少量文本定位或已经天然有界的直接读取，不需要完整性、压缩、结构或复用能力时可继续使用全局内核规定的受限原生快路径，不触发网关 skill。需要全部/不存在证明、大结果压缩、目录树、AST、缓存、分页或机器产物时使用统一网关。`symbol-structure-workflow` 只在真实符号语义或 LSP 会改变结论时触发，不重复网关的 backend 规则。

### DES-SQG-009 安全、授权与故障边界

- 状态: proposed
- 满足: REQ-005, AC-016, AC-017, AC-040
- 关联: DES-SQG-001, DES-SQG-002

网关不是 sandbox 或授权系统。rg preprocessor、fd exec/batch、ast-grep rewrite/apply 以及任意原生副作用仍使用当前用户权限，授权由适用规则和用户请求决定。网关只对无法解释必需输入、可能混用结果快照、二进制输出缺少产物目标或转换会破坏原生字节设置局部可恢复门禁；其他未知或特殊模式选择 passthrough/artifact 并给诊断。

原生退出码与 wrapper 自身错误分通道记录。转换失败时不得输出成功空结果；已经产生的完整原始结果保存为有界临时产物或显式目标，stdout 返回失败原因和恢复动作。stderr 不混入结构化 stdout，秘密和源码正文不进入 telemetry/meta。

## 4. 版本与兼容声明

首个候选以当前 Windows 环境的 ripgrep 15.1.0、fd 10.4.2 和 ast-grep 0.44.1 建立主矩阵，并保留现有 sgy 已验证的 ast-grep 0.41.1 与 0.42.0 回归。支持范围只覆盖逐项真实运行的精确版本；升级通过新增矩阵和 release 证据完成，不声明连续版本范围。

完整兼容的含义是“该精确版本公开的所有命令模式都可通过网关调用并保持原生语义”，不等于每种模式都能转换为 Token-Safe 结构。结构化、文本、artifact 和 passthrough 的分类必须覆盖全部模式，未分类项使该版本不能发布为完整兼容。

## 5. 依赖和正式入口迁移

| 当前对象 | 目标裁决 |
| --- | --- |
| `tools/sgy` | 扩展为统一网关唯一源码与发布 owner |
| `rg_receipt.py` 及测试 | rg backend 验证后删除 |
| `rg-token-safe` | 当前消费者迁入统一 skill 后删除 |
| `fd-usage` | 当前消费者迁入统一 skill 后删除 |
| `ast-grep-token-safe` | 由统一 skill 取代；内置运行时与来源记录迁移，不复制二进制 |
| `symbol-structure-workflow` | 保留，只维护网关与 LSP 的语义升级边界 |
| `development/code-search-benchmark` | 保留为不执行查询的端到端成本核算入口 |

迁移不保留 Python wrapper、重复 skill 或旧 AST 命令别名。发布、插件 payload、路由合同、README、runtime manifest、许可证和部署清单在同一消费者闭环内更新。

## 6. 设计风险与控制

| 风险 | 控制 |
| --- | --- |
| 统一工具膨胀为自动决策巨石 | 公共层只维护执行和表示；backend 与 LSP 语义分开 |
| 为兼容重新实现三套不完整 CLI parser | 逐精确版本建立完整命令矩阵、argv 透明传递、未知模式 passthrough、真实二进制测试与 fuzz |
| Token 估算器选择更短但信息不足的表示 | EvidenceSignature 先固定必要信息，只比较语义等价表示 |
| 树输出路径歧义 | 根别名、可逆转义、类型标记、round-trip 性质测试 |
| 统一 skill 对简单任务增加固定回合 | 原生快路径保留在不同适用范围，路由评估覆盖触发与非触发 |
| 完整结果执行造成资源无界 | 有界 spool、显式预算、超时、artifact 和完整性状态；不以展示上限限制写入集合 |
| backend 升级导致静默兼容漂移 | 精确版本声明、doctor、版本矩阵和 release gate |

## 7. 设计完成判定

本设计只有在三个 backend 的全部公开模式均有持久分类、公共结果可复核、fd tree 可逆、AST 既有安全合同不退化、统一 skill 完成消费者迁移、旧同责入口退出，并且真实 Codex 质量与总 Token 验证达到 `REQ-012/CON-001` 时才能标记为 `confirmed`。实现存在或单个 backend 通过不能证明统一网关完成。
