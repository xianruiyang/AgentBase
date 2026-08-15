# 统一源码查询网关验证记录

## 1. 记录边界

本文件只汇总本分支候选的可重复验证结果。命令输出、测试代码、语料和独立评估原始文件仍由各自项目入口或项目外 capsule 承担；这里不复制大日志，也不把局部验证扩张为端到端模型收益。

## 2. 已完成验证

| 范围 | 入口 | 结果 |
| --- | --- | --- |
| P0 backend 合同 | `backend-contract/tests` | 版本、模式表、fixture、语义分类通过 |
| AST 精确版本 | P0 ast-grep 0.41.1/0.42.0/0.44.1 矩阵 | 30 项通过 |
| sgy Rust workspace | `cargo ci-test` | 全部非 ignored 测试通过；含 rg/fd 真实集成与约 59 秒压力测试 |
| Rust 静态质量 | `cargo fmt --all`、`cargo lint` | 通过 |
| rg/fd 定向单元 | `cargo test -p sgy-cli --lib` | 28 项通过 |
| rg/fd 真实集成 | `cargo test -p sgy-cli --test query_gateway_real` | 11 项通过 |
| backend 候选矩阵 | `backend-contract/verify_candidate.py` | 29 个模式样本、7 个原生 oracle 通过 |
| AST 候选非回退 | `ast-baseline/compare_ast_baseline.py --expected-version 0.2.0` | 仅 release version 可变，其余冻结输出逐字一致 |
| 候选 skill | skill-creator `quick_validate.py` | 有效 |
| 候选 payload | `verify_candidate_payload.py` | 14 个允许文件，二进制 hash 一致，无开发资产泄漏 |
| Windows 安装生命周期 | `tools/sgy/scripts/test-install-sgy.ps1`，0.1.1 → 0.2.0 | 安装、幂等、失败回滚、恶意包/篡改拒绝、升级和卸载全部通过 |
| 最终 detached 路由 | `evidence/routing-result-v13.json` | 21/21 route/reference 与授权、预览、同快照 oracle 通过 |
| 最终隔离模型审计 | `evidence/audit-result-v11.json` | 核心语义 12/12、严格语义 12/12、格式 11/12、严格整体 11/12 |
| 最终端到端成本 | `development/code-search-benchmark/experiment.py` monitor | input 1,139,430；output 7,171；实际总 Token 1,146,601；404.603 s；31 次工具调用、0 失败 |

## 3. 证据边界

冻结五-skill 历史记录为实际总 Token 1,157,111、508.509 s、核心 12/12、严格整体 11/12；按用户要求未重跑。最终候选在同一质量口径下方向性少 10,510 Token、快 103.906 s，但历史记录缺少当前 manifest 的完整环境 identity，因此只证明当前授权证据边界内的保留裁决，不证明严格因果 A/B。

最终候选的唯一格式失败是一条九行答案超过八行限制；历史严格整体同为 11/12，故没有质量退化。更低 Token 的中间候选曾降低核心或严格质量，已按质量优先退出。主线消费者迁移、旧 skill 退出和真实 Codex 安装态尚未执行，也不由本记录授权。

新的 advisory scan 未运行，因为当前授权环境未安装 `cargo-audit`；候选 release record 已明确记录该限制。
