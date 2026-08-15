# 统一源码查询网关分支现状

## 1. 文档职责

本文件记录相对 [requirements.md](requirements.md)、[user-design.md](user-design.md) 和 [design.md](design.md) 的当前直接观察、已经闭环的实现边界与剩余差距。观察对象是当前 AgentBase 分支工作树；总体项目、正式 skill 与 Codex 安装态仍未采纳本分支。历史测试只按其冻结候选身份保留，不自动覆盖后续源码、skill 或 payload。

## OBS-SQG-001 sgy 已承载三个并列命令域

- 状态: verified
- 关联: DES-SQG-001, DES-SQG-002, DES-SQG-003

候选 `sgy 0.2.0` 保留原 AST 顶层命令，并增加可直接调用但不进入 AST help/schema 的 `sgy rg exec/defaults/doctor` 与 `sgy fd exec/defaults/doctor`。rg/fd 原生 argv 保留顺序、重复、空值和 Windows 非 UTF 参数，机器参数插入原生命令 `--` 之前；不能安全结构化的调用可用 raw、artifact 或 passthrough 保持原生字节和副作用语义。

29 个 ripgrep 15.1.0 与 fd 10.4.2 公开模式样本均有唯一分类，7 个 raw/artifact oracle 已逐字回放。`defaults` 只解释参数和模式，不发现或启动引擎。

## OBS-SQG-002 查询结果按所选证据单元投影并按需持久化快照

- 状态: verified
- 关联: DES-SQG-004, DES-SQG-005, DES-SQG-006, DES-SQG-007

直接反例曾证明旧实现先按 rg 原始 match/context 事件分页、再投影 files/locations/summary：`summary --limit 1` 为已经完整的摘要生成无意义续页；files 把匹配事件数当作文件数；带 context 的 locations 第一页可为空却声称已展示一项。当前实现改为先形成视图自己的证据单元，再计算总量与分页；summary 是终止视图，files 按去重后的匹配文件分页，locations 只按匹配位置分页。相应真实集成回归已覆盖普通 rg、fd、native files、count 和 vimgrep。

默认 v2 回执仍固定显式返回总量与结果、显示、正文三类完整性，只在非零退出或真正需要分页时增加必要字段；backend、引擎版本、mode、view、offset 和字节数由内部对象持有，显式 `--receipt full` 才返回完整 v1 诊断回执。完整默认结果不再计算或持久化无消费者的 snapshot；只有续页或 full 回执需要身份时才计算 hash、原子持久化并返回精确 cursor。进程与持久 snapshot 的既有上限、hash 和混用拒绝仍保留。

fd 会冻结对象类型并为每个显式根建立可逆 trie；只有估算 Token 确实低于 flat 时 auto 才选 tree。rg 普通 batch 消费原生 JSON 事件，grouped、records、locations、files、summary 与 lossless 均在相同证据签名内选择；count、vimgrep 和特殊模式使用独立严格解析或透传。

## OBS-SQG-003 AST 公开合同保持冻结

- 状态: verified
- 关联: DES-SQG-001, DES-SQG-009

P0 冻结的 `sgy 0.1.2` AST version/help、命令 help、schema 与 capabilities 已对 `0.2.0` 候选逐字复核，唯一允许差异是 release version 字段。完整 sgy workspace 测试已运行一次且通过；P0 的 ast-grep 0.41.1、0.42.0、0.44.1 真实矩阵共 30 项通过。公共改动只复用了进程输出上限，没有迁移 AST serializer、cache、profile、fingerprint、process 或 rewrite 合同。

## OBS-SQG-004 候选 skill 与当前 payload 已重建

- 状态: verified
- 关联: DES-SQG-008, DES-SQG-009, CON-SQG-003

分支内 `candidate-skill/source-query` 用一个精炼主文件按“原生快路径 → rg/fd 网关 → AST → LSP”升级，详细 rg/fd 与 AST 协议按需读取。skill 的静态结构此前通过验证，测试资产排除合同不变。

当前 Windows release、来源记录、SBOM、manifest 与 candidate payload 已从同一 `0.2.0` workspace 版本重建：二进制 SHA-256 为 `fcec9aa20b0ccaf27729451399d5ca46e962be21830438af210aea95a314e230`，archive SHA-256 为 `0d75a224c62e7b9861a8806743a2423ab5cdcbc3e431c119a0e32001dbcc6733`，source revision 为 `sha256:3722e37b103a4428c2b6cc9ad656664893c5c694f1a18fb5ad3a79ebedb0c910`。payload 校验确认 14 个运行文件且没有测试、fixture、benchmark、runner、corpus、result 或 audit 资产；AST 冻结差异和 Windows 安装生命周期通过。宿主没有 `cargo-audit`，因此仍只能记录既有审计继承依据与限制，不声称完成新的 advisory scan。

## OBS-SQG-005 benchmark owner 已具备隔离运行合同

- 状态: verified
- 关联: DES-SQG-010, AC-SQG-004

现有 `development/code-search-benchmark` 已扩展为本项目唯一的 corpus、环境身份、`codex exec --json --ephemeral` monitor、A-B-B-A 调度、受影响 case 选择、usage 汇总和 detached audit capsule owner。语料绑定来源文件 hash，并用 `answer_contract.required` 区分 prompt 必答内容与只用于证明正确性的 supporting facts；环境只允许显式差异，失败和超时不被静默替换。capsule 声明可独立复算的规范化哈希算法。历史安装态、收紧候选、五-skill 消融与裸环境数字以各自证据上限登记，不跨 identity 拼接。

## OBS-SQG-006 当前行为证据已刷新但没有形成收益对照

- 状态: partially_verified
- 关联: REQ-SQG-001, AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-004

当前候选的 detached 路由结果 [routing-result-v15.json](evidence/routing-result-v15.json) 覆盖 21 个首次路由、非触发、跨根、关系端点、行数预算、AST、LSP、分页和写入安全场景，21/21 符合独立 oracle。评估 capsule 已把首次选择与按需引用分层，避免把详细协议预加载给 evaluator。

当前轮完整 candidate-only monitor 覆盖六类真实查询各两次；12 次中 11 次有完整 usage，完整 run 的 input 为 `998,139`、output 为 `5,894`、实际总 Token 为 `1,004,033`，全体 wall time 为 `560,744 ms`。`ue-command-dispatch-submit` 的一次运行在已经取得源码证据后遇到 TLS 重连并超时，没有 final answer 与 usage；它保留为真实失败，不能从聚合删除或补跑替换。因此该组数据不是十二次完整总量，也没有 control，不能与历史数字作因果比较。

关系 case 的受影响补测证明模型两次都取得定义、泛型承载字段和响应映射证据。最终保留路由的两次 run 共 `157,053` Token、`64,131 ms`；更强的回答规则变体增至 `170,824` Token、`61,916 ms`，仍未稳定复述 supporting relation，故已退出。独立 oracle 复核确认两次答案均满足原 prompt 的最小合同，把未复述 `mapping.type` 判作核心失败属于越过 prompt；corpus `2026-08-15.2` 已将必答内容与 supporting facts 显式分开。该修正还没有新的同 identity 全量运行。

用户要求冻结且不重跑的五-skill 消融历史记录仍为实际总 Token `1,157,111`、耗时 `508,509 ms`、核心语义 12/12、严格整体 11/12。它缺少当前 experiment 的完整 identity，只能继续作为历史现实依据。由于当前候选的投影、快照、版本和发布身份已改变，旧候选相对该记录的 `0.91%` Token 与 `20.43%` 耗时方向差不能证明当前实现已达收益边缘；TSQG-061—063 已据此重开。

## GAP-SQG-003 当前候选缺少身份一致的完成证据

- 状态: open
- 关联: REQ-SQG-001, AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-004

当前后端、AST 冻结、候选 payload、独立路由和 candidate-only 监控均已有直接证据，但 corpus 回答合同刚刚修正，完整运行又有一次 usage 缺失，且用户要求冻结的 control 与当前 Codex、工作区、候选及 corpus identity 不同。继续单独重跑 candidate 不会产生可比较收益结论；只有用户允许一次同 identity 的 control/candidate 对照，或明确接受不形成当前因果收益结论，才能关闭该差距。在此之前不得恢复收益边缘、主线采纳或发布完成判断。

## GAP-SQG-002 主线迁移仍由用户采纳决定

- 状态: deferred
- 关联: CON-SQG-001, DES-SQG-008

[migration-candidate.md](migration-candidate.md) 已定义旧 skill、Python rg wrapper、全局路由和消费者的原子迁移方式；当前没有改动或删除这些正式入口。只有收益证据达到根本需求且用户确认采纳后，才可实施主线迁移；发布到 Codex 仍需当次单独确认。
