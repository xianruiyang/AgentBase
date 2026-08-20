# 验证记录

## 确定性与消费者验证

| 检查 | 结果 | 证明范围 |
| --- | --- | --- |
| `cargo ci-build` / `cargo ci-test` / `cargo lint` / `cargo fmt-check` | pass | srcq 0.4.1 全 workspace 构建、测试、严格 lint 与格式 |
| query gateway | 34/34 pass | rg/fd/scc 共享 renderer、分页/cursor、machine、snapshot、真实 scc 与错误边界 |
| PowerShell `@next` 往返 | pass | 空 argv、空白、元字符、双引号、反引号、美元与换行保持；新 PowerShell 7 进程成功取得第二页 |
| fixture scc invocation log | 1 | 首次页面扫描一次；`@next` 只读 snapshot，不重扫原生 scc |
| source-query 静态合同 | 96 cases；55 strict routing；10 strict references；11/11 skills | skill 消费新 `@next`，引用、触发与非触发边界自洽 |
| 路由基础设施 | 6 suites；22 syntax files；0 evaluator runs | 确定性 evaluator/planner/ledger 基础设施无回归；当前阶段证据可直接复用 |
| 部署 `Validate` | pass | Plugin/DirectCompatibility 候选 payload 与当前证据合同可校验；不等于 Publish |

## independent Codex v6

- experiment identity: `27ac16beea6ef195bd443057fc229b17af603d4d5c2aa7f54fcc31ca74ad20f5`
- preflight: 33.149 s；`srcq.exe --version` 为 `srcq 0.4.1`，`srcq query scc doctor` 为 `ok`；网络三项计数全零。
- subject: 27.522 s；input `64,529`、cached input `40,448`、output `405`、reasoning output `119`；exit 0，postflight failures 为空，网络三项计数全零。
- 第一条命令原样执行普通 scc files 查询，第一页以 `@more shown=80 omitted=97` 和完整 `@next` 结束。
- 第二条命令逐字使用 `@next` 的 `srcq query scc exec --after <cursor> -- <原 argv>`，exit 0；第二页首项为 `D:/program/AgentBase/tools/srcq/crates/srcq-core/src/profile/paths.rs`。模型没有读取 help、skill、源码或第三页。
- capsule SHA-256: `fce108b55bce2871e2bb153e95725cebb5dd04d2530806aa28c07d31a6257926`；4 个原始文件和 2 个环境文件由正式 verifier 验真。

原始 v6 运行只保存在 `%LOCALAPPDATA%\AgentBase\pagination-eval-20260820-v6`，不进入仓库或发布 payload。结论只覆盖正常同一轮 query model 续页；压缩后恢复、cache/process 自身分页和完整 A/B 收益不在本次目标内。
