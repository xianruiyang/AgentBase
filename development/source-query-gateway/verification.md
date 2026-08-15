# 统一源码查询网关验证记录

## 1. 记录边界

本文件只汇总本分支候选的可重复验证结果。命令输出、测试代码、语料和独立评估原始文件仍由各自项目入口或项目外 capsule 承担；这里不复制大日志，也不把局部验证扩张为端到端模型收益。

## 2. 已完成验证

| 范围 | 入口 | 结果 |
| --- | --- | --- |
| P0 backend 合同 | `backend-contract/tests` | 版本、模式表、fixture、语义分类通过 |
| AST 精确版本 | P0 ast-grep 0.41.1/0.42.0/0.44.1 矩阵 | 30 项通过 |
| sgy Rust workspace 历史基线 | `cargo ci-test` | 稀疏回执改动前全部非 ignored 测试通过；当前按影响范围复核 sgy-cli 与 release owner，未机械重跑无关 workspace 测试 |
| Rust workspace 当前格式 | `cargo fmt --all` | 通过 |
| rg/fd 当前定向单元 | `cargo test -p sgy-cli --lib` | 29 项通过；含 `--receipt auto|full` 参数合同 |
| rg/fd 当前真实集成 | `cargo test -p sgy-cli --test query_gateway_real` | 15 项通过；新增各 view 证据单元、summary 终止和完整默认查询不落 snapshot 回归 |
| sgy-cli 当前静态质量 | `cargo clippy -p sgy-cli --all-targets --all-features -- -D warnings`、`cargo fmt --all -- --check` | 通过 |
| release helper | `cargo test -p sgy-release`、`cargo clippy -p sgy-release --all-targets -- -D warnings` | 4 项通过；manifest 读回 workspace 0.2.0 与 ast-grep/rg/fd 三引擎声明 |
| backend 候选矩阵 | `backend-contract/verify_candidate.py` | 29 个模式样本、7 个原生 oracle 通过 |
| AST 候选非回退 | `ast-baseline/compare_ast_baseline.py --expected-version 0.2.0` | 仅 release version 可变，其余冻结输出逐字一致 |
| 候选 skill | skill-creator `quick_validate.py` | 有效 |
| 候选 payload | `verify_candidate_payload.py` | 14 个允许文件，当前二进制 hash `fcec9aa2…e230` 一致，无开发资产泄漏 |
| Windows 安装生命周期 | `tools/sgy/scripts/test-install-sgy.ps1`，0.1.1 → 0.2.0 | 安装、幂等、失败回滚、恶意包/篡改拒绝、升级和卸载全部通过 |
| 完整短查询按需 snapshot 机制 | 同一 release 查询、25 个唯一 argv、A-B-B-A，本机进程总耗时 | 旧实现 4115.9/3918.1 ms 且每轮落 25 个 snapshot；当前实现 3870.5/3875.3 ms 且 0 snapshot，均值少 144.1 ms（3.59%） |
| 历史 detached 路由 | `evidence/routing-result-v13.json` | 旧候选 21/21；当前 skill/协议身份变化后只作历史输入 |
| 历史隔离模型审计 | `evidence/audit-result-v11.json` | 旧候选核心与严格语义 12/12、格式与严格整体 11/12；不覆盖当前候选 |
| 历史端到端成本 | `development/code-search-benchmark/experiment.py` monitor | 旧候选实际总 Token 1,146,601、404.603 s；不覆盖当前候选 |

## 3. 证据边界

冻结五-skill 历史记录为实际总 Token 1,157,111、508.509 s、核心 12/12、严格整体 11/12；按用户要求未重跑。旧候选曾在同一质量口径下方向性少 10,510 Token、快 103.906 s，但历史记录缺少当前 manifest 的完整环境 identity，且当前二进制、skill 与回执协议已经变化，因此该差额不再支持当前候选完成或收益边缘判断。

旧候选的唯一格式失败是一条九行答案超过八行限制；更低 Token 的中间候选曾降低核心或严格质量，已按质量优先退出。当前实现修正的直接反例、后端矩阵、AST 冻结、skill、payload、release 与安装生命周期已经通过，但 detached 行为与真实 Codex 总 Token 对照尚未刷新；主线消费者迁移、旧 skill 退出和真实 Codex 安装态也未执行。

新的 advisory scan 未运行，因为当前授权环境未安装 `cargo-audit`；候选 release record 已明确记录该限制。

本次没有运行真实独立 agent 路由或总 Token 对照，因用户明确要求先完成实现。直接候选回归证明 summary/files/locations 的总量、页边界和续页身份已修正；A-B-B-A 本机机制测试证明完整默认查询不再建立无消费者 snapshot，并在该固定短查询样本上减少 3.59% 进程总耗时。这些只证明对应机制和局部资源成本，不替代端到端 Token 证据。
