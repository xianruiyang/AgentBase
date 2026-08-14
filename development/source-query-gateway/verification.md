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
| rg/fd 定向单元 | `cargo test -p sgy-cli --lib` | 26 项通过 |
| rg/fd 真实集成 | `cargo test -p sgy-cli --test query_gateway_real` | 10 项通过 |
| backend 候选矩阵 | `backend-contract/verify_candidate.py` | 29 个模式样本、7 个原生 oracle 通过 |
| AST 候选非回退 | `ast-baseline/compare_ast_baseline.py --expected-version 0.2.0` | 仅 release version 可变，其余冻结输出逐字一致 |
| 候选 skill | skill-creator `quick_validate.py` | 有效 |
| 候选 payload | `verify_candidate_payload.py` | 14 个允许文件，二进制 hash 一致，无开发资产泄漏 |
| Windows 安装生命周期 | `tools/sgy/scripts/test-install-sgy.ps1`，0.1.1 → 0.2.0 | 安装、幂等、失败回滚、恶意包/篡改拒绝、升级和卸载全部通过 |

## 3. 尚待验证

- detached 路由与行为评估；
- 受监控隔离 Codex 对照和独立质量审计；
- 基于质量、总 Token、耗时顺序的最终保留、收紧或退出裁决。

新的 advisory scan 未运行，因为当前授权环境未安装 `cargo-audit`；候选 release record 已明确记录该限制。
