# 统一源码查询网关实施计划

## 1. 文档职责

本文件是 [design.md](design.md) 的唯一当前实施计划。它只安排已经由 `REQ-012`、`UDES-SQG-*` 和 `DES-SQG-*` 定义的工作，不创建新需求。当前状态为 `proposed`，尚未开始代码实现，也未授权发布到实际 Codex。

## 2. 推进原则

- 先保证原生兼容、结果正确、授权和可维护性，再降低端到端 Token，最后比较速度。
- 每个 backend 都先完成一条从真实命令到模型输出再到 oracle 的纵向闭环，再扩展横向命令矩阵。
- 现有 sgy AST 能力保持可验证，不用重写稳定代码来追求结构整齐。
- 不同时保留决定同一行为的新旧包装入口；消费者迁移与旧入口删除属于同一阶段。
- 受影响模块先做定向测试；只有公共 schema、发布合同或正式分发范围改变时扩大验证。
- 五-skill 消融的 1,157,111 Token 和当前安装态的 1,765,222 Token 冻结复用，不重跑相同基线。

## 3. 阶段与任务

### P0 固定合同和基准

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| T-SQG-001 | 审核 `REQ-012`、用户设计和模型设计，解决会改变接口的未决项 | — | 经用户确认的需求与设计版本 | 用户确认完整兼容、auto 输出、fd tree、简单快路径和旧入口退出边界 |
| T-SQG-002 | 冻结当前 rg/fd/ast-grep 精确版本、help/schema 和真实行为 oracle | T-SQG-001 | 三个 backend 的版本化命令清单与原生结果语料 | 每个公开命令/模式都有唯一 ID、原生 argv、退出与输出分类，不用旧 wrapper 反推 oracle |
| T-SQG-003 | 固定 Token 与质量基准 | T-SQG-001 | 既有 24 回合结果引用、短查询与多查询任务集、答案 oracle | 不重跑冻结消融；新任务先定义同一质量目标和完整性边界 |

P0 闭环：能够逐项回答“要兼容什么、原生事实是什么、如何证明没有漏模式、如何判断 Token 收益”。缺少命令分类时不进入 backend 实现。

### P1 建立公共执行与输出内核

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| T-SQG-010 | 从现有 sgy 提取 backend-neutral 的进程、流、spool、meta、退出和 artifact 职责 | T-SQG-002 | `EngineAdapter`/`InvocationClass`/`ExecutionSnapshot` 边界 | 现有 AST 真实运行结果逐字节或结构等价；无行为回退 |
| T-SQG-011 | 建立公共 envelope、EvidenceSignature 和 backend schema 注册 | T-SQG-010 | 版本化查询包络与 schema | 0/1/N/N+1、截断、转换失败、native error 独立可表达 |
| T-SQG-012 | 建立语义等价候选 renderer 与 TokenCostEstimator | T-SQG-011, T-SQG-003 | `auto` 规划器、显式 view 和成本 meta | 只在 EvidenceSignature 相同候选间选择；已知结果的选择稳定且实际 Token 复算一致 |
| T-SQG-013 | 建立 snapshot 分页和有界 spool | T-SQG-010, T-SQG-011 | snapshot identity、精确 cursor、artifact 生命周期 | 跨页不混用查询，未知 cursor/快照漂移局部阻断，完整底层结果不进入模型上下文 |

P1 闭环：用现有 AST backend 跑通一次真实查询，证明公共内核没有改变原生执行范围、退出语义或 AST Token-Safe 结果。

### P2 fd 纵向闭环与完整矩阵

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| T-SQG-020 | 实现 fd engine discovery、argv passthrough 和默认路径结构读取 | T-SQG-002, T-SQG-010 | fd adapter 最小闭环 | 真实 fd 10.4.2 的文件、目录、0/1/N/N+1 与多根查询通过 |
| T-SQG-021 | 实现根别名、可逆转义、trie 和 flat/grouped/tree renderer | T-SQG-011, T-SQG-012, T-SQG-020 | fd tree/v1 | Windows 路径、Unicode、空格、多根、相同目录名、文件/目录和 round-trip 性质测试通过 |
| T-SQG-022 | 覆盖 fd 全部公开模式 | T-SQG-002, T-SQG-020 | fd 完整命令矩阵实现 | exec/batch、print0、absolute/base-directory、ignore/hidden、help/version 和未知模式均保持原生语义或明确 passthrough/artifact |
| T-SQG-023 | 验证 fd auto 表示收益 | T-SQG-021, T-SQG-003 | 小/中/大/深/宽目录结果成本报告 | tree 只在实际预计 Token 更低时选中；完整路径和 completeness 与原生 oracle 一致 |

P2 闭环：模型通过统一入口完成真实文件发现，目录树比平铺路径更短且能还原全部路径；特殊 fd 命令仍可执行，没有第二套简化查询语法。

### P3 rg 纵向闭环与完整矩阵

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| T-SQG-030 | 实现 rg engine discovery、JSON event adapter 和文件分组 | T-SQG-002, T-SQG-010, T-SQG-011 | rg 普通 batch 查询闭环 | 真实 ripgrep 15.1.0 的 fixed/regex、多个 pattern、glob、上下文和 no-match 与原生 oracle 一致 |
| T-SQG-031 | 实现 rg locations/files/grouped/summary/lossless/raw renderer | T-SQG-012, T-SQG-030 | rg backend schema 与 auto 规划 | 长路径、多文件、长行、二进制/非 UTF-8、子匹配和文本截断保持独立状态 |
| T-SQG-032 | 覆盖 rg 全部公开模式 | T-SQG-002, T-SQG-030 | rg 完整命令矩阵实现 | count/files/replace/passthru/pre/json/sort/help/version/特殊输出和错误均有真实测试分类，不用不完整 option 黑名单 |
| T-SQG-033 | 删除 Python 回执机制依赖 | T-SQG-030, T-SQG-032 | rg 消费者改用新 backend 的候选差异 | 原 `-e '--no-heading'`、原生 `rg` 前缀和显式格式等故障机制不再存在；不是靠新增特例规避 |

P3 闭环：统一 rg backend 能完成全部位置与不存在证明，输出比原生重复路径更短，且五类已知包装失败均由接口结构消失而非重试兜底。

### P4 AST 迁移和跨 backend 收敛

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| T-SQG-040 | 把现有 ast-grep adapter 接入显式 `ast` backend | T-SQG-010, T-SQG-011 | 新 AST 命令入口 | 当前 sgy 单元、集成、真实引擎、cache、process、TTY/LSP 和 rewrite 测试保持通过 |
| T-SQG-041 | 迁移 AST profile 到公共 auto/EvidenceSignature | T-SQG-012, T-SQG-040 | AST renderer 注册 | token-safe、locations、files、custom、lossless 的字段和完整性不退化 |
| T-SQG-042 | 建立三个 backend 的一致 doctor/defaults/capabilities | T-SQG-022, T-SQG-032, T-SQG-040 | 统一诊断和能力 schema | 缺失引擎、错误版本、输出不兼容和原生 passthrough 状态可机械区分 |

P4 闭环：同一二进制分别完成 fd、rg、AST 真实任务，共用包络与预算但保持 backend 语义；AST 写入安全门和 fingerprint 机制没有回退。

### P5 Skill、消费者和旧入口迁移

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| T-SQG-050 | 建立统一源码查询 skill 与按需 backend 引用 | T-SQG-023, T-SQG-033, T-SQG-042 | 一个精炼 skill | 路由用例覆盖简单快路径、完整性、tree、AST、LSP 边界和 PowerShell 非触发 |
| T-SQG-051 | 更新 `symbol-structure-workflow`、全局最小路由与当前消费者 | T-SQG-050 | 唯一依赖方向 | 文本→网关/原生快路径→AST backend→LSP 的升级只发生在缺少必要证据时 |
| T-SQG-052 | 删除旧 skill、Python wrapper、旧 AST 命令和重复协议 | T-SQG-050, T-SQG-051 | 旧入口退出 | 仓库、插件 payload、部署清单和安装沙箱不存在同责入口或悬空引用 |
| T-SQG-053 | 更新 README、runtime manifest、许可证、来源和发布文档 | T-SQG-052 | 可维护文档与供应链记录 | 文档版本、二进制 hash、源码 revision、archive 与实际运行读回一致 |

P5 闭环：当前消费者只通过统一 owner 获得网关能力，简单查询保留不同适用范围的原生快路径，旧包装不再决定行为或占用运行时 Token。

### P6 质量、Token、速度与发布闭环

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| T-SQG-060 | 运行 backend 定向、workspace 公共契约、fuzz/property 与真实版本矩阵 | T-SQG-053 | 质量验证结果 | 全部声称版本和命令分类通过；失败对象明确，不靠全量重跑碰运气 |
| T-SQG-061 | 刷新独立 skill 路由、行为策略与引用证据 | T-SQG-050, T-SQG-052 | 当前 detached evidence | 首次路由、简单非触发、LSP/AST 边界和规则行为满足隐藏 oracle |
| T-SQG-062 | 运行真实 Codex 总 Token 候选测试 | T-SQG-060, T-SQG-061, T-SQG-003 | 候选总 Input/cached/Output/reasoning/耗时/质量报告 | 只测机制已改变的候选，比较冻结安装态和五-skill 消融；短任务与多查询任务分别报告 |
| T-SQG-063 | 收益边缘裁决 | T-SQG-062 | 保留、调整触发或退出网关的证据结论 | 质量先通过；固定加载成本无收益时继续收紧触发，表示压缩不抵成本时不得宣称 Token 优化完成 |
| T-SQG-064 | Git 提交、非强制推送和按次发布 | T-SQG-063 | 可回退提交与可选 Codex 发布 | Git 按既有持续授权处理；实际 Codex 发布仍等待用户针对该次明确确认，新任务验证加载结果 |

P6 闭环：`REQ-012` 的每项 AC 都有直接证据，答案质量不低于对照，端到端 Token 收益如实成立，旧入口已退出且发布资产可回滚。

## 4. 关键里程碑

| 里程碑 | 包含任务 | 可观察结果 | 不代表什么 |
| --- | --- | --- | --- |
| M1 合同闭合 | T-SQG-001..003 | 全命令范围、原生 oracle 和成本基准明确 | 不代表实现可用 |
| M2 表示闭合 | T-SQG-010..023 | fd tree 与公共 auto 真实可用 | 不代表 rg/AST 完成 |
| M3 查询闭合 | T-SQG-030..042 | 三 backend 共用网关且各自语义成立 | 不代表消费者已迁移 |
| M4 入口闭合 | T-SQG-050..053 | 单一 skill/owner 生效，旧入口退出 | 不代表 Token 收益通过 |
| M5 交付闭合 | T-SQG-060..064 | 质量、Token、速度、供应链和发布均有证据 | 发布仍需当次用户确认 |

## 5. 回退与停止条件

- 原生命令无法在不改变语义的情况下适配时，保留 passthrough/artifact，不降低兼容目标；若完整矩阵仍有未分类模式，停止该版本的“完整兼容”声明。
- 公共抽象迫使 backend 复制或丢失特有语义时，回到 `DES-SQG-001/004` 修订边界，不在 adapter 中增加隐藏特例。
- fd tree 不能机械还原路径或在实际 Token 上不比 flat 更短时，不选 tree；不为符合形式保留更贵表示。
- AST 现有 rewrite、cache、fingerprint、TTY/LSP 或 release gate 任一退化时停止迁移，不用 rg/fd 新能力掩盖。
- 真实 Codex 质量退化时先修正质量；质量相同但总 Token 高于冻结消融且没有必要证据收益时，继续收紧触发或重新裁决统一入口，不以更快为理由发布为优化完成。
