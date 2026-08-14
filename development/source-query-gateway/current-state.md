# 统一源码查询网关分支现状

## 1. 文档职责

本文件记录相对 [requirements.md](requirements.md)、[user-design.md](user-design.md) 和 [design.md](design.md) 的当前直接观察与差距。观察以当前 AgentBase 工作树为对象；实现变化后应修订相应条目，不把旧观察继续当作现状。

## OBS-SQG-001 sgy 当前只以 ast-grep 为查询引擎

- 状态: confirmed
- 来源: `tools/sgy/README.md`、`tools/sgy/crates/sgy-cli/src/main.rs`、`tools/sgy/crates/sgy-core/src/lib.rs`
- 关联: DES-SQG-001, DES-SQG-002, DES-SQG-003

当前 `sgy 0.1.2` 的公开命令、engine 解析、defaults、adapter、cache、process、profile、TTY/LSP 和诊断都围绕 ast-grep。代码已经具备进程、预算、artifact、缓存与结构化适配等成熟职责，但尚无 rg 或 fd 命令域；哪些内部职责能在不改变 AST 合同的前提下共享仍需逐项证明。

## OBS-SQG-002 sgy 已有广泛 AST 行为与发布验证

- 状态: confirmed
- 来源: `tools/sgy/crates/*/tests`、`tools/sgy/tests`、`tools/sgy/scripts`、`tools/sgy/docs/compatibility.md`
- 关联: DES-SQG-001, DES-SQG-009

现有测试覆盖 argv 边界、run/scan adapter、lossless、cache、process、profile、write、TTY/LSP、真实 ast-grep 版本和发布安装生命周期。正式文档精确声明 ast-grep 0.41.1、0.42.0、0.44.1 与 Windows x86_64 MSVC；这些现有入口和结果是后续非回退 oracle 的来源，但尚未冻结为本分支独立基线身份。

## OBS-SQG-003 benchmark 当前只分析已经完成的局部路径记录

- 状态: confirmed
- 来源: `development/code-search-benchmark/README.md`、`development/code-search-benchmark/analyze.py`
- 关联: DES-SQG-010

当前 benchmark owner 能核算 manifest 中已经完成的搜索路径，但不会建立隔离 Codex 环境、启动 subject、监控 JSONL/usage、冻结源码快照、比较环境 allowlist 或生成 detached audit capsule。分支已有历史种子与协议，尚无符合新协议的正式 corpus 和执行入口。

## OBS-SQG-004 当前模型侧查询职责分散

- 状态: confirmed
- 来源: `skills/rg-token-safe`、`skills/fd-usage`、`skills/ast-grep-token-safe`、`skills/symbol-structure-workflow`、`skills/powershell-usage`
- 关联: DES-SQG-008

当前正式候选由多个 skill 分别承担文本、文件、AST、符号升级和 PowerShell 命令规则，rg 还存在 Python 回执脚本。它们是现行入口；在统一候选通过质量与成本证据并完成消费者迁移前不能提前删除或把实验规则当作新真源。

## OBS-SQG-005 历史对照尚不能证明统一包装有净收益

- 状态: confirmed
- 来源: `plan.md` 第 3 节、`benchmark-protocol.md` 第 7 节
- 关联: AC-SQG-001, AC-SQG-002, AC-SQG-003, DES-SQG-010

两轮历史真实 Codex 对照显示局部结构投影有条件收益，但当时的候选相对安装态和五-skill 消融都增加端到端总 Token；旧数据还缺少完整源码快照和严格一致的环境身份。它们能限定改进方向，不能作为新候选达成需求的证据。

## GAP-SQG-001 缺少统一 rg 与 fd 命令域

- 状态: confirmed
- 关联: DES-SQG-002, DES-SQG-003, DES-SQG-006, DES-SQG-007, OBS-SQG-001

当前 `sgy` 不能通过与 AST 同质量的单一二进制承载 rg/fd，也没有 EvidenceSignature、自适应 renderer、fd 可逆目录树或 rg 原生 JSON 事件适配。

## GAP-SQG-002 缺少三个后端的完整兼容与非回退基线

- 状态: confirmed
- 关联: DES-SQG-001, DES-SQG-003, DES-SQG-009, OBS-SQG-002

现有 AST 测试尚未形成分支独立的冻结身份；rg/fd 的精确版本、全部公开模式、原生输出和退出分类也未建立，因此不能证明完整兼容或 AST 不回退。

## GAP-SQG-003 缺少可重复的隔离 agent 总成本实验入口

- 状态: confirmed
- 关联: DES-SQG-010, OBS-SQG-003, OBS-SQG-005

当前入口不能从冻结 manifest 自动完成环境构建、subject 隔离、外部监控、完整 usage 保存、独立审计和 identity 复用，无法产生 `AC-SQG-004` 要求的收益证据。

## GAP-SQG-004 现行模型侧入口尚未收敛

- 状态: confirmed
- 关联: DES-SQG-008, OBS-SQG-004

尚无经过验证的统一查询 skill，也没有证据支持退出 rg/fd/AST 的现行同责入口。提前迁移会破坏当前可用能力，继续永久叠加则会保留固定 Token 成本与多入口维护负担。

## GAP-SQG-005 根本需求尚无完成证据

- 状态: confirmed
- 关联: REQ-SQG-001, AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-004, OBS-SQG-005

当前不存在同时证明质量充分、端到端总 Token 降低、前两项不退化后速度改善且可隔离复核的候选结果；因此不能把已有包装、设计或局部输出压缩视为完成。
