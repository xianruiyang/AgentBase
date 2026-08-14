# 统一源码查询网关分支设计

## 1. 文档职责与状态

本文件定义满足 [requirements.md](requirements.md) 和 [user-design.md](user-design.md) 的候选模型设计，状态为 `proposed`。它只属于本分支，不证明实现可用，也不改变 AgentBase 总体需求或正式入口；实施顺序以 [plan.md](plan.md) 为准。

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

### DES-SQG-001 AST 设计是稳定基线

- 满足: AC-SQG-001, UDES-SQG-002, UDES-SQG-005, UDES-SQG-006

AST 继续使用当前强制 `--` argv 边界、透明参数数组、默认 JSON stream 注入、Token-Safe YAML、profile、cache、fingerprint、后处理、rewrite 安全边界、TTY/LSP、artifact、诊断退出码和发布来源。现有命令不是待淘汰兼容入口，而是 AST 的正式入口。

内部重构必须以当前 CLI、schema、退出状态、缓存身份、位置投影和写入证据为冻结 oracle。除修复已独立确认的 AST 缺陷外，不允许为了 backend 对称、统一 envelope 或减少实现行数改变这些可观察行为。

### DES-SQG-002 公共内核只抽取真实共同职责

- 满足: AC-SQG-001, AC-SQG-002, UDES-SQG-001, UDES-SQG-005

`tools/sgy` 维护一个内部公共执行包络，可包含引擎发现、cwd、参数数组、stdin/TTY、stdout/stderr 捕获、超时、退出状态、结果 spool、查询身份、上下文预算、诊断、artifact 和发布来源。每项抽取都必须先证明三个命令域具有相同生命周期和失败语义；否则留在 backend 内。

公共 Rust 类型不等于公共序列化格式。AST 继续输出现有 `_sgy` 和结果 schema；rg/fd 可以复用相同字段语义，但由各自 serializer 保留文本匹配、路径和 AST 节点的差异。

### DES-SQG-003 原生命令透明边界

- 满足: AC-SQG-001, UDES-SQG-002, UDES-SQG-005

所有 `--` 后 token 均以参数数组保留值、顺序和重复项，不经 shell 拼接。AST 沿用现有 `sgy defaults`；rg/fd 的 `defaults` 只展示原始 argv、为机器读取追加的参数、抑制原因和最终 argv，不启动底层引擎。

每个受支持精确版本维护完整命令矩阵，并把公开模式分为：可安全结构化、只可有界文本、应写显式产物、必须原样透传。不能结构化不等于不兼容；显式原生选项优先，包装只追加已证明不改变查询或副作用集合的机器输出选项。

### DES-SQG-004 最短充分输出规划

- 满足: AC-SQG-001, AC-SQG-002, UDES-SQG-003

backend 先形成 `EvidenceSignature`，明确当前表示必须保留的路径、类型、位置、正文、捕获、规则、诊断、顺序和完整性。规划器只比较签名相同的候选表示，并使用随二进制发布的确定性 Token 估算器选择预计成本最低者；真实 Codex 的 `input + output` Token 用于发布收益判断。

AST 现有 profile 及其选择语义保持不变，不迁入新的 `auto` 规则。rg/fd 可提供 `auto` 与显式 view；不适用的 view 返回局部输入错误，不静默删除原生命令要求的信息。

### DES-SQG-005 结果完整性与分页快照

- 满足: AC-SQG-001, AC-SQG-002, UDES-SQG-003

每个 backend 的结构化结果都能表达引擎版本、查询身份、原生退出、总量、展示量、省略量、结果完整性、正文完整性和诊断。大结果先完整执行并有界 spool，再从同一不可变结果快照投影或分页；游标绑定查询、快照和 view，分页不缩小底层查询范围。

AST 继续使用现有 cache 与 fingerprint 合同，不迁移到 rg/fd 的分页身份。内部可以复用 spool 和 cursor 原语，但不能制造第二套 AST 缓存或弱化源码变化检测。

### DES-SQG-006 fd 可逆目录树

- 满足: AC-SQG-001, AC-SQG-002, UDES-SQG-003, UDES-SQG-004

fd 优先取得无歧义的 NUL 分隔路径，为每个显式根分配稳定短别名，并按词法相对路径建立 trie。名称采用可逆转义，文件、目录和其他已识别类型可区分；多根、绝对路径和根外结果不合并成虚假共同根，重复项遵循原生命令语义。

同一结果生成 flat 与 tree 候选并比较预计 Token，tree 只有更短时才选中。预算不足时报告省略量与不完整状态；结构化省略节点不得与真实路径混淆。目录树是可逆表示，不是采样器。

### DES-SQG-007 rg 结果适配

- 满足: AC-SQG-001, AC-SQG-002, UDES-SQG-002, UDES-SQG-003

普通 batch 搜索使用 ripgrep 原生 JSON 事件，区分 match、context、begin/end、summary 与错误，并按 EvidenceSignature 选择分组正文、位置或文件视图。count、文件列表、replace 展示、passthru、preprocessor、显式 JSON、help/version 和特殊报告分别进入命令矩阵，不以启发式输出 flag 黑名单猜测。

无匹配、原生错误、转换错误和结果省略分别保持。只有完整消费底层结果才能声明查询集合完整；N+1 只能证明当前展示窗口是否还有下一项。

### DES-SQG-008 Skill 与成本路由

- 满足: AC-SQG-002, AC-SQG-003, UDES-SQG-001

候选最终只保留一个精炼的源码查询 skill，主文件说明触发边界、backend 选择、完整性和写入安全，rg、fd 与 AST 的详细协议按需读取。AST 部分以现有 `ast-grep-token-safe` 合同为语义来源，迁移只改变文档归属，不改变 sgy 用法和安全边界；只有独立路由与行为证据证明等价后才退出旧 skill。

一次精确文件名发现、已知文件内少量文本定位或天然有界的直接读取继续使用受限原生快路径。需要全集或不存在证明、大结果压缩、目录树、AST、缓存或分页时才承担 skill 和网关成本。LSP 只在真实符号语义会改变结论时升级。

### DES-SQG-009 安全与故障边界

- 满足: AC-SQG-001, UDES-SQG-002, UDES-SQG-005

网关不是 sandbox 或授权系统。rg preprocessor、fd exec/batch 与 ast-grep rewrite/apply 继续使用当前用户权限和上位授权。网关只对缺少解释必需输入、可能混用快照、二进制输出缺少产物目标或转换会破坏原生字节设置局部可恢复门禁；其他特殊模式透传或落产物并给诊断。

原生退出与 wrapper 错误分通道记录。转换失败不得输出成功空结果；stderr 不混入结构化 stdout，源码正文和秘密不进入 telemetry/meta。

## 4. 版本与迁移边界

首个候选以 ripgrep 15.1.0、fd 10.4.2 和当前 sgy 已验证的 ast-grep 0.41.1、0.42.0、0.44.1 建立 Windows 精确版本矩阵，不外推连续版本范围。完整兼容表示该精确版本所有公开模式都可通过相应命令域调用并保持原生语义，不表示所有模式都能结构化压缩。

| 当前对象 | 分支目标 |
| --- | --- |
| `tools/sgy` | 保持 AST 正式入口并增加 rg/fd 命令域 |
| `rg_receipt.py` | rg 命令域完成真实替代后删除 |
| `rg-token-safe`、`fd-usage` | 消费者与路由证据闭环后由统一 skill 取代 |
| `ast-grep-token-safe` | 语义原样迁入按需 AST 引用后退出；sgy 命令不迁移 |
| `symbol-structure-workflow` | 保留，只维护查询与 LSP 的升级边界 |
| 现有 sgy runtime、cache 与发布记录 | 原位沿用，不复制、不建立第二状态源 |

## 5. 主要风险与控制

| 风险 | 控制 |
| --- | --- |
| 表面统一破坏成熟 AST 合同 | AST 公开行为冻结；rg/fd 适配它的质量标准，不要求命令对称 |
| 公共抽象吞掉 backend 特有语义 | 先证明共同生命周期；serializer、cache 和写入边界允许独立 |
| 完整兼容退化为不完整 parser | 精确版本命令矩阵、argv 透明传递、透传/产物退路和真实引擎测试 |
| 更短输出丢失必要证据 | 先固定 EvidenceSignature，只比较语义等价表示 |
| fd tree 路径歧义 | 根别名、可逆转义、类型标记和 round-trip 性质测试 |
| 简单查询承担固定成本 | 保留适用范围不同的原生快路径，以端到端 Token 验证触发边界 |

## 6. 设计完成判定

只有 rg/fd 全部公开模式有持久分类，结果完整性可复核，fd tree 可逆，AST 现有 CLI、profile、cache、fingerprint、process、rewrite、TTY/LSP、诊断和发布合同逐项不退化，消费者与旧同责入口完成迁移，并且真实 Codex 依次证明 `AC-SQG-001` 的质量充分、`AC-SQG-002` 的端到端总 Token 收益和 `AC-SQG-003` 的速度取舍时，本设计才可由 `proposed` 进入待主线采纳状态。该状态仍不自动修改总体项目或授权发布。
