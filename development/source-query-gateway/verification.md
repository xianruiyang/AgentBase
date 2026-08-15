# 统一源码查询网关验证记录

## 1. 记录边界

本文件只汇总本分支候选的可重复验证结果。命令输出、测试代码、语料和独立评估原始文件仍由各自项目入口或项目外 capsule 承担；这里不复制大日志，也不把局部验证扩张为端到端模型收益。

## 2. 已完成验证

| 范围 | 入口 | 结果 |
| --- | --- | --- |
| P0 backend 合同 | `backend-contract/tests` | 版本、模式表、fixture、语义分类通过 |
| AST 精确版本 | P0 ast-grep 0.41.1/0.42.0/0.44.1 矩阵 | 30 项通过 |
| srcq Rust workspace 当前门禁 | `cargo ci-test`、`cargo ci-build`、`cargo lint`、`cargo fmt-check` | 当前提交的全部 workspace、all-targets、all-features 非 ignored 测试、构建、Clippy `-D warnings` 与格式检查通过；覆盖 CLI、core、unit、integration、protocol、stress 和 release 包 |
| 当前真实 ast-grep 0.44.1 | `SRCQ_AST_GREP=<native exe>`、`SRCQ_AST_GREP_EXPECTED_VERSION='ast-grep 0.44.1'` 后运行 workspace ignored 套件 | 15 项通过；覆盖 run/scan/rewrite、cache/process、LSP 字节透传、TTY、completion、new/test、失败/取消和 Windows Console Ctrl-C |
| rg/fd 当前定向单元 | `cargo test -p srcq-cli --lib` | 29 项通过；含 `--receipt auto|full` 参数合同 |
| rg/fd 当前真实集成 | `cargo test -p srcq-cli --test query_gateway_real` | 15 项通过；新增各 view 证据单元、summary 终止和完整默认查询不落 snapshot 回归 |
| srcq-cli 当前静态质量 | `cargo clippy -p srcq-cli --all-targets --all-features -- -D warnings`、`cargo fmt --all -- --check` | 通过 |
| release helper | `cargo test -p srcq-release`、`cargo clippy -p srcq-release --all-targets -- -D warnings` | 4 项通过；manifest 读回 workspace 0.2.0 与 ast-grep/rg/fd 三引擎声明 |
| backend 候选矩阵 | `backend-contract/verify_candidate.py` | 29 个模式样本、7 个原生 oracle 通过 |
| AST 候选非回退 | `ast-baseline/compare_ast_baseline.py --expected-version 0.2.0` | 仅 release version 可变，其余冻结输出逐字一致 |
| 候选 skill | skill-creator `quick_validate.py` | 有效 |
| 候选 payload | `verify_candidate_payload.py` | 5 个允许文件，无二进制、私有运行时或开发资产泄漏 |
| Windows 安装生命周期 | `tools/srcq/scripts/test-install-srcq.ps1`，0.1.1 → 0.2.0 | 安装、幂等、失败回滚、恶意包/篡改拒绝、升级和卸载全部通过 |
| 完整短查询按需 snapshot 机制 | 同一 release 查询、25 个唯一 argv、A-B-B-A，本机进程总耗时 | 旧实现 4115.9/3918.1 ms 且每轮落 25 个 snapshot；当前实现 3870.5/3875.3 ms 且 0 snapshot，均值少 144.1 ms（3.59%） |
| 正式 Skill 静态校验 | skill-creator `quick_validate.py` | `source-query` 与 `symbol-structure-workflow` 均有效；前者恰为 5 个协议文件 |
| 正式 detached 路由 | `development/skill-routing/evidence/current.json` | 65/65 首次路由、65/65 行为策略、13/13 治理引用独立通过；首次选择只读取全局短路由与 skill frontmatter |
| 原生 LSP 渐进路径 | `evidence/lsp-progressive-v1.json` | no-LSP、单项与多阶段三案均按预期只调用 0/2/3 个 MCP 能力，质量通过、usage 完整；独立审计结论为 `pass_with_execution_caveat` |
| 正式部署合同 | `manage_agentbase.ps1 -Action Validate`、`test_manage_agentbase.ps1` | 11 个 Skill、增量发布/回滚、旧入口退出、测试资产和私有运行时排除通过 |
| 插件 payload | 隔离 `build_plugin.ps1 -SkipOfficialValidation` | 11 个 Skill；`source-query` 恰为 5 文件且无 `.exe` |
| benchmark owner 定向回归 | `development/code-search-benchmark/tests/test_experiment.py` | 受影响 case 选择、candidate-only 调度、回答合同、capsule canonical hash、identity 与超时保留通过 |
| 当前 candidate-only 全量审计 | `evidence/audit-result-v12.json` | 12 次中 11 次 usage 完整，完整 run 合计 1,004,033 Token；1 次 TLS 超时原样保留，无 control |
| 关系 case 受影响审计 | `evidence/relation-audit-v1.json`、`evidence/relation-audit-v2.json` | 保留规则取得全部源码证据；更强规则增加 Token 而未改善 prompt 必答内容，已退出 |
| 回答合同适用性审计 | `evidence/oracle-audit-v1.json` | 两次答案均满足 prompt 最小合同；未复述 supporting mapping type 不构成 core fail |
| 历史隔离模型审计 | `evidence/audit-result-v11.json` | 旧候选核心与严格语义 12/12、格式与严格整体 11/12；不覆盖当前候选 |
| 历史端到端成本 | `development/code-search-benchmark/experiment.py` monitor | 旧候选实际总 Token 1,146,601、404.603 s；不覆盖当前候选 |

## 3. 证据边界

冻结五-skill 历史记录为实际总 Token 1,157,111、508.509 s、核心 12/12、严格整体 11/12；按用户要求未重跑。旧候选曾在同一质量口径下方向性少 10,510 Token、快 103.906 s，但历史记录缺少当前 manifest 的完整环境 identity，且当前二进制、skill 与回执协议已经变化，因此该差额不再支持当前候选完成或收益边缘判断。

旧候选的唯一格式失败是一条九行答案超过八行限制；更低 Token 的中间候选曾降低核心或严格质量，已按质量优先退出。当前实现修正的直接反例、完整 workspace、真实 ast-grep 0.44.1、后端矩阵、AST 冻结、skill、payload、release、安装生命周期和 detached 路由已经通过。当前 candidate-only monitor 不能替代受控对照：一次真实超时缺少 usage，且用户冻结的旧 control 与当前 identity 不同。项目真源中的消费者迁移和旧 skill 退出已经完成；实际 Codex 安装态尚未发布。

新的 advisory scan 未运行，因为当前授权环境未安装 `cargo-audit`；候选 release record 已明确记录该限制。

当前轮已经运行真实独立 agent 路由、candidate-only 总 Token 监控和 LSP 渐进调用，并通过 detached auditor 复算 capsule、usage 与质量。LSP 三案只证明候选侧的按需行为和绝对成本；每案均有一次只读命令被策略拒绝后恢复，是执行质量提示而非 MCP 失败。关系 case 的审计分歧进一步证明结构化 oracle 的 supporting facts 不能自动变成最终答案必答项，corpus `2026-08-15.2` 已显式修正该边界。由于没有当前 identity 的 control，且新 corpus 尚无完整双环境运行，这些证据只证明当前行为、失败路径和测试机制，不证明相对收益。
