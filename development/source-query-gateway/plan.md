# 统一源码查询网关分支实施计划

## 1. 文档职责

本文件只安排 [requirements.md](requirements.md)、[user-design.md](user-design.md) 与 [design.md](design.md) 已定义的候选分支工作，不创建总体项目需求。状态为 `proposed`，尚未开始实现，也未授权写入正式 skill、总体项目入口或实际 Codex。

## 2. 推进原则

- 先保证原生语义、答案质量、授权、安全和可维护性，再降低端到端 Token，最后比较速度。
- AST 以当前 sgy 行为为冻结基线；新增 rg/fd，不能把 AST 迁入另一套命令、profile、cache 或 process 设计。
- 每个 backend 先闭环一条真实命令、结果与 oracle，再扩展完整命令矩阵。
- 只抽取已证明相同的内部职责；公共抽象导致 AST 行为变化或 backend 语义丢失时立即回退设计。
- 受影响模块先做定向验证；公共协议、发布合同或正式分发范围改变时才扩大。
- 五-skill 消融的 1,157,111 Token 和当前安装态的 1,765,222 Token 作为冻结对照，不重跑相同基线。

## 3. 阶段与任务

### P0 固定分支合同和 AST 基线

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| T-SQG-001 | 审核根本需求、用户设计与模型设计中的接口未决项 | — | 经用户确认的分支合同 | 根目标保持“质量 → 总 Token → 速度”；统一包装、完整兼容、fd tree 与 AST 基线只作为服务该目标的设计约束 |
| T-SQG-002 | 冻结 rg/fd/ast-grep 精确版本、help/schema 与真实行为 oracle | T-SQG-001 | 三个 backend 的命令清单和原生语料 | 每个公开模式有唯一 ID、原生 argv、退出与输出分类 |
| T-SQG-003 | 冻结当前 sgy AST 可观察合同 | T-SQG-002 | CLI/schema/cache/process/rewrite/TTY/LSP/release 基线 | 当前定向、集成和真实引擎用例可重复，结果或结构等价边界明确 |
| T-SQG-004 | 固定质量与 Token 比较协议 | T-SQG-001 | 既有基线引用、短查询与多查询任务、答案 oracle | 不重跑冻结对照；新候选使用同一模型、项目、顺序和质量目标 |

P0 闭环：能逐项回答要兼容什么、AST 什么不能改变、原生事实是什么、如何证明没有漏模式，以及如何判断总 Token 收益。

### P1 在不改变 AST 的前提下建立公共内核

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| T-SQG-010 | 识别 sgy 内部可真正跨 backend 复用的进程、spool、meta、退出、预算与 artifact 职责 | T-SQG-003 | 候选公共边界和不应抽取清单 | 每项都有相同生命周期/失败语义证据，不能证明的留在 AST 内 |
| T-SQG-011 | 提取内部执行原语并保持 AST serializer、cache 和命令层不变 | T-SQG-010 | backend-neutral 内部接口 | P0 AST oracle 全部保持；公开 help/schema/exit 无非预期差异 |
| T-SQG-012 | 建立 rg/fd 的 EvidenceSignature、完整性字段与 renderer 注册 | T-SQG-011, T-SQG-004 | 新 backend 公共语义接口 | 0/1/N/N+1、截断、转换失败和 native error 可独立表达 |
| T-SQG-013 | 建立 rg/fd 的有界 spool、snapshot 和精确 cursor | T-SQG-011, T-SQG-012 | 查询快照与产物生命周期 | 跨页不混快照，未知 cursor 局部阻断，底层完整结果不进入模型上下文 |

P1 闭环：现有 AST 查询、缓存投影和 rewrite 行为不变，同时新 backend 已有可用而不绑死 AST 的内部承载边界。

### P2 fd 纵向闭环与完整矩阵

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| T-SQG-020 | 实现 `sgy fd exec/defaults/doctor`、argv passthrough 和路径读取 | T-SQG-002, T-SQG-011 | fd 最小闭环 | 真实 fd 10.4.2 的文件、目录、0/1/N/N+1 和多根查询与原生 oracle 一致 |
| T-SQG-021 | 实现根别名、可逆转义、trie 与 flat/tree renderer | T-SQG-012, T-SQG-020 | fd tree schema | Windows 路径、Unicode、空格、多根、同名目录、对象类型和 round-trip 性质测试通过 |
| T-SQG-022 | 覆盖 fd 全部公开模式 | T-SQG-002, T-SQG-020 | fd 完整命令矩阵 | exec/batch、print0、absolute/base-directory、ignore/hidden、help/version 等均结构化或明确透传/产物 |
| T-SQG-023 | 验证 fd 自适应表示 | T-SQG-004, T-SQG-021 | 深/宽/多根结果成本报告 | tree 只在预计 Token 更低时选中，全部路径与完整性可还原 |

P2 闭环：fd 常用发现得到更短且可逆的树，所有特殊命令仍保持原生能力，没有第二套简化查询语法。

### P3 rg 纵向闭环与完整矩阵

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| T-SQG-030 | 实现 `sgy rg exec/defaults/doctor`、JSON event adapter 和文件分组 | T-SQG-002, T-SQG-011, T-SQG-012 | rg 普通 batch 闭环 | 真实 ripgrep 15.1.0 的 fixed/regex、多 pattern、glob、上下文和 no-match 与原生 oracle 一致 |
| T-SQG-031 | 实现 locations/files/grouped/summary/lossless/raw renderer | T-SQG-004, T-SQG-030 | rg backend schema 与 auto 规划 | 长路径、多文件、长行、非 UTF-8、子匹配与文本截断状态独立 |
| T-SQG-032 | 覆盖 rg 全部公开模式 | T-SQG-002, T-SQG-030 | rg 完整命令矩阵 | count/files/replace/passthru/pre/json/sort/help/version 与错误有真实分类，不用 option 黑名单猜测 |
| T-SQG-033 | 删除 Python 回执机制依赖 | T-SQG-030, T-SQG-032 | rg 消费者候选差异 | 已知 argv 解析和输出前缀故障由接口结构消失，不靠新增特例规避 |

P3 闭环：rg 能完成全部位置与不存在证明，压缩重复路径且保持原生退出、完整性和特殊模式。

### P4 AST 不回退与跨 backend 收敛

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| T-SQG-040 | 用 P0 oracle 复核 AST 当前公开入口 | T-SQG-011, T-SQG-023, T-SQG-032 | AST 非回退差异报告 | `sgy exec/defaults/cache/process/schema/capabilities/doctor`、profile、TTY/LSP 与 rewrite 均无非预期变化 |
| T-SQG-041 | 仅在序列化与行为等价时让 AST 复用公共内部原语 | T-SQG-040 | 最小共享实现或保留独立的裁决 | 共享有证据；无法证明同责时不为减少代码强行合并 |
| T-SQG-042 | 完成三命令域的诊断、版本和发布来源读回 | T-SQG-022, T-SQG-032, T-SQG-041 | capability/doctor 与 release 证据 | 缺失引擎、错误版本、输出不兼容和透传状态可区分，AST 现有诊断合同不变 |

P4 闭环：同一 sgy 二进制完成 fd、rg 与 AST 真实任务；rg/fd 共享合适的基础设施，AST 继续使用原有设计和安全合同。

### P5 Skill、消费者与重复入口退出

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| T-SQG-050 | 建立精炼的统一查询 skill 和按需 backend 引用 | T-SQG-023, T-SQG-033, T-SQG-042 | 候选 skill | 简单快路径、完整性、tree、AST、LSP 边界和 PowerShell 非触发路由通过 |
| T-SQG-051 | 将现有 AST skill 语义原样迁入按需引用 | T-SQG-050 | AST 规则等价映射 | sgy 命令、profile、cache、process、rewrite 和安全边界无丢项；独立行为证据等价 |
| T-SQG-052 | 更新消费者并退出已被替代的 rg/fd wrapper 与旧 skill | T-SQG-050, T-SQG-051 | 唯一职责方向 | 不删除 sgy AST 命令；仓库不存在同责 Python wrapper、重复规则或悬空引用 |
| T-SQG-053 | 更新分支内发布候选清单与供应链材料 | T-SQG-052 | 候选 runtime manifest、来源、许可证和部署差异 | 二进制 hash、源码 revision、archive 与真实运行读回一致 |

P5 闭环：查询规则只有一个低成本入口，AST 设计保持，重复的 rg/fd 包装职责退出；总体项目仍未因此自动采纳分支。

### P6 质量、Token、速度与采纳裁决

| ID | 任务 | 依赖 | 产出 | 验证与闭环 |
| --- | --- | --- | --- | --- |
| T-SQG-060 | 运行 backend 定向、公共契约、性质/fuzz 与真实版本矩阵 | T-SQG-053 | 质量验证结果 | 声称支持的版本和模式全部通过，AST 基线无回退 |
| T-SQG-061 | 运行 detached skill 路由和行为评估 | T-SQG-050, T-SQG-052 | 分支评估证据 | 首次路由、简单非触发、AST/LSP 边界和写入安全满足独立 oracle |
| T-SQG-062 | 运行真实 Codex 候选总 Token 测试 | T-SQG-004, T-SQG-060, T-SQG-061 | Input/cached/Output/reasoning/耗时/质量报告 | 只测机制已改变的候选，比较冻结安装态与五-skill 消融；短任务和多查询任务分别报告 |
| T-SQG-063 | 裁决保留、收紧或退出 | T-SQG-062 | 收益边缘结论 | 质量先通过；固定成本无收益则收紧触发，压缩收益不抵成本则不宣称优化完成 |
| T-SQG-064 | 请求主线采纳与当次 Codex 发布授权 | T-SQG-063 | 用户裁决 | 只有用户确认后才更新总体需求、README、正式 skill 和安装态；Git 按既有授权另行维护 |

P6 闭环：先有直接证据证明模型取得正确且充分的所需内容，再证明端到端总 Token 收益，最后在前两项不退化时比较速度；是否进入主线和发布仍由用户单独确认。

## 4. 停止条件

- AST 现有 CLI、profile、cache、fingerprint、process、rewrite、TTY/LSP、诊断或 release gate 任一发生非必要变化时，停止并回到设计裁决。
- 原生命令不能在不改变语义的情况下结构化时使用透传或产物；仍有未分类模式时停止该版本的“完整兼容”声明。
- 公共抽象迫使 backend 复制、丢失特有语义或新增第二状态源时，保留独立实现，不以形式统一为完成目标。
- fd tree 不能机械还原路径或预计 Token 不低于 flat 时不选 tree。
- 真实 Codex 质量退化时先修正质量；质量相同但总 Token 高于冻结消融且无必要证据收益时，继续收紧或退出，不以速度补偿。
