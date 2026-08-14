# 统一源码查询网关分支现状

## 1. 文档职责

本文件记录相对 [requirements.md](requirements.md)、[user-design.md](user-design.md) 和 [design.md](design.md) 的当前直接观察、已经闭环的实现边界与剩余差距。观察对象是当前 AgentBase 分支工作树；总体项目、正式 skill 与 Codex 安装态仍未采纳本分支。

## OBS-SQG-001 sgy 已承载三个并列命令域

- 状态: verified
- 关联: DES-SQG-001, DES-SQG-002, DES-SQG-003

候选 `sgy 0.2.0` 保留原 AST 顶层命令，并增加可直接调用但不进入 AST help/schema 的 `sgy rg exec/defaults/doctor` 与 `sgy fd exec/defaults/doctor`。rg/fd 原生 argv 保留顺序、重复、空值和 Windows 非 UTF 参数，机器参数插入原生命令 `--` 之前；不能安全结构化的调用可用 raw、artifact 或 passthrough 保持原生字节和副作用语义。

29 个 ripgrep 15.1.0 与 fd 10.4.2 公开模式样本均有唯一分类，7 个 raw/artifact oracle 已逐字回放。`defaults` 只解释参数和模式，不发现或启动引擎。

## OBS-SQG-002 查询结果具有有界快照和可验证完整性

- 状态: verified
- 关联: DES-SQG-004, DES-SQG-005, DES-SQG-006, DES-SQG-007

rg/fd 结构化结果分别表达原生退出、结果/正文/显示完整性、总量、展示量、快照和精确游标。查询先有界捕获到不可变 snapshot，再从同一身份投影；游标绑定 query、snapshot、实际 view 与 offset，未知或混用游标被局部拒绝。进程 stdout/stderr 有独立上限，超限时终止进程组；snapshot 数量与文件完整性也有上限和 hash 校验。

fd 会冻结对象类型并为每个显式根建立可逆 trie；只有估算 Token 确实低于 flat 时 auto 才选 tree。rg 普通 batch 消费原生 JSON 事件，grouped、records、locations、files、summary 与 lossless 均在相同证据签名内选择；count、vimgrep 和特殊模式使用独立严格解析或透传。

## OBS-SQG-003 AST 公开合同保持冻结

- 状态: verified
- 关联: DES-SQG-001, DES-SQG-009

P0 冻结的 `sgy 0.1.2` AST version/help、命令 help、schema 与 capabilities 已对 `0.2.0` 候选逐字复核，唯一允许差异是 release version 字段。完整 sgy workspace 测试已运行一次且通过；P0 的 ast-grep 0.41.1、0.42.0、0.44.1 真实矩阵共 30 项通过。公共改动只复用了进程输出上限，没有迁移 AST serializer、cache、profile、fingerprint、process 或 rewrite 合同。

## OBS-SQG-004 候选 skill 与发布 payload 已形成

- 状态: verified
- 关联: DES-SQG-008, DES-SQG-009, CON-SQG-003

分支内 `candidate-skill/source-query` 用一个精炼主文件按“原生快路径 → rg/fd 网关 → AST → LSP”升级，详细 rg/fd 与 AST 协议按需读取。skill 静态校验通过。候选 payload 共 14 个文件，只含规则、引用、Windows 二进制、runtime/release 来源和许可证；自动检查确认不含 test、fixture、benchmark、runner、corpus、result 或 audit 资产。

候选二进制 SHA-256 为 `126f68cd1ffbd9c272833cc66ac36e6723f96d511b02f282fe90fd976c51392b`，发布 archive SHA-256 为 `9c6d1ba36c082299bde5a61cc4df59c4c79e0ba17cbc0cc3b91ebc9a4a75c5a1`。安装、重复安装、失败升级回滚、恶意 ZIP、篡改状态、升级、卸载和用户配置/缓存保护测试通过。宿主没有 `cargo-audit`，因此本候选只记录既有审计继承依据与限制，不声称完成新的 advisory scan。

## OBS-SQG-005 benchmark owner 已具备隔离运行合同

- 状态: verified
- 关联: DES-SQG-010, AC-SQG-004

现有 `development/code-search-benchmark` 已扩展为本项目唯一的 corpus、环境身份、`codex exec --json --ephemeral` monitor、A-B-B-A 调度、usage 汇总和 detached audit capsule owner。语料绑定来源文件 hash，环境只允许显式差异，失败和超时不被静默替换。历史安装态、收紧候选、五-skill 消融与裸环境数字以各自证据上限登记，不跨 identity 拼接。

## GAP-SQG-001 独立模型行为与端到端收益尚待新候选实测

- 状态: open
- 关联: REQ-SQG-001, AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-004

静态 skill、backend oracle、AST 非回退和发布包验证只证明候选能力本身，不能证明模型会以最低充分成本选用它。还需 detached 路由/行为评估和受监控真实 Codex 对照，逐案确认质量后复算 input + output 总 Token，再在前两项不退化时比较耗时。

## GAP-SQG-002 主线迁移仍由用户采纳决定

- 状态: deferred
- 关联: CON-SQG-001, DES-SQG-008

[migration-candidate.md](migration-candidate.md) 已定义旧 skill、Python rg wrapper、全局路由和消费者的原子迁移方式；当前没有改动或删除这些正式入口。只有收益证据达到根本需求且用户确认采纳后，才可实施主线迁移；发布到 Codex 仍需当次单独确认。
