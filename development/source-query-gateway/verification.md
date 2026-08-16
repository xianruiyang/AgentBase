# 统一源码查询网关验证记录

## 1. 记录边界

本文件只汇总本分支候选的可重复验证结果。命令输出、测试代码、语料和独立评估原始文件仍由各自项目入口或项目外 capsule 承担；这里不复制大日志，也不把局部验证扩张为端到端模型收益。

## 2. 已完成验证

| 范围 | 入口 | 结果 |
| --- | --- | --- |
| P0 backend 合同 | `backend-contract/tests` | 6 项通过；版本、模式表、fixture、语义分类与原生 no-match oracle 一致 |
| AST 精确版本 | P0 ast-grep 0.41.1/0.42.0/0.44.1 矩阵 | 30 项通过 |
| srcq Rust workspace 当前门禁 | `cargo ci-test`、`cargo ci-build`、`cargo lint`、`cargo fmt-check` | `srcq 0.3.1` 的全部 workspace、all-targets、all-features 非 ignored 测试、构建、Clippy `-D warnings` 与格式检查通过；真实引擎发现的 machine 消费者遗漏修正后做了定向复验 |
| 当前真实 ast-grep 0.44.1 | `SRCQ_AST_GREP=<native exe>`、`SRCQ_AST_GREP_EXPECTED_VERSION='ast-grep 0.44.1'` 后运行受影响 ignored 套件 | CLI 3 项、core profile 1 项、integration workflow 4 项通过；默认 model 与显式 machine 消费边界已覆盖 |
| rg/fd 当前定向单元 | `cargo test -p srcq-cli --lib` | 37 项通过；覆盖原生 token 不被 wrapper 抢占、有序路径树、前缀重入回退、cursor 与模式分类 |
| rg/fd 当前真实集成 | `cargo test -p srcq-cli --test query_gateway_real` | 22 项通过；除直接入口、表示选择、预算、续页和三输出面外，覆盖 rg 15.2、未来版本、变化协议安全降级、machine 转换错误和副作用不重放 |
| srcq-cli 当前静态质量 | `cargo clippy -p srcq-cli --all-targets --all-features -- -D warnings`、`cargo fmt --all -- --check` | 通过 |
| release helper | `cargo test -p srcq-release`、当前 `build-release.ps1` | 4 项通过；生成绑定源码快照的 `srcq 0.3.1` Windows x86_64 MSVC manifest、SBOM、许可证和受校验归档；归档 SHA-256 为 `2ce4c7351ca7d7e469f66b473852e3a6b97c52e1935fe5e4544042df602b2915` |
| backend 候选矩阵 | `backend-contract/verify_candidate.py --srcq <srcq.exe>` | 当前直接/显式入口下 29 个模式样本、7 个原生 oracle 通过 |
| AST 候选非回退 | `ast-baseline/compare_ast_baseline.py --expected-version 0.3.1` | 通过；比较器只剔除新增 rg/fd/query 行，不改写历史 AST 期望 |
| 候选 skill | skill-creator `quick_validate.py` | 有效 |
| 候选 payload | `verify_candidate_payload.py` | 5 个允许文件，无二进制、私有运行时或开发资产泄漏 |
| Windows 安装生命周期 | `tools/srcq/scripts/test-install-srcq.ps1`，0.3.0 → 0.3.1 | 当前归档安装、幂等、完整性读回、受管漂移修复、新进程 PATH、失败回滚、恶意包/篡改拒绝、真实升级、doctor、卸载边界、并发 PATH、配置/cache 保留与显式清理通过 |
| 完整短查询按需 snapshot 机制 | 同一 release 查询、25 个唯一 argv、A-B-B-A，本机进程总耗时 | 旧实现 4115.9/3918.1 ms 且每轮落 25 个 snapshot；当前实现 3870.5/3875.3 ms 且 0 snapshot，均值少 144.1 ms（3.59%） |
| 正式 Skill 静态校验 | skill-creator `quick_validate.py` | `source-query` 与 `symbol-structure-workflow` 均有效；前者恰为 5 个协议文件 |
| 当前 detached 路由 | `development/skill-routing/evidence/current.json` | 66/66 首次路由、66/66 行为策略、13/13 治理引用由三个独立 `gpt-5.6-sol`/medium/default 运行通过；当前候选 bundle 为 `577DAF40…E20E4E`，仓库与隐藏期望均未被评估器访问 |
| 原生 LSP 渐进路径 | `evidence/lsp-progressive-v1.json` | no-LSP、单项与多阶段三案均按预期只调用 0/2/3 个 MCP 能力，质量通过、usage 完整；独立审计结论为 `pass_with_execution_caveat` |
| 当前正式部署合同 | `manage_agentbase.ps1 -Action Validate` | 当前候选、11 个 Skill、`source-query`、portable settings、MCP、路由证据与直接兼容 payload 通过只读发布前验证；未执行 Publish |
| 上一 identity 插件 payload | 隔离 `build_plugin.ps1 -SkipOfficialValidation` | 11 个 Skill；`source-query` 恰为 5 文件且无 `.exe`；当前静态合同仍证明相同源 payload 边界，正式构建待新 evidence |
| benchmark owner 定向回归 | `development/code-search-benchmark/tests` 与 `source-query-gateway/tests` | 24 项 benchmark owner 和 9 项环境准备/路由测试通过；受影响 case、调度、回答合同、identity、capsule 与外部文件哈希、正常速度门禁、超时保留及 Token 分项/价格边界可重复 |
| Token 与价格报告合同 | `experiment.py` usage v2、GPT-5.6 当前官方系数 | 原始 usage、普通/缓存读/缓存写、可见/推理输出、实际总量和环境汇总已分离；短上下文 `1/0.1/1.25/6`、长上下文 `2/0.2/2.5/9` 随 experiment identity 冻结，缺失缓存写入或请求级上下文档位时只报边界，不伪造精确账单 |
| 当前 corpus | `corpus/v6.json`、`validate_corpus.py` | 6 项 oracle 与 AgentBase/GptProjectTest 绑定源码逐项验证通过；行数验收已显式进入被测 prompt，普通文本与高级证据触发边界绑定当前规则/skill |
| 当前 candidate-only 全量审计 | `evidence/audit-result-v12.json` | 12 次中 11 次 usage 完整，完整 run 合计 1,004,033 Token；1 次 TLS 超时原样保留，无 control |
| 上一冻结身份 Codex 对照 | `evidence/audit-result-v13.json` | 24/24 运行正常退出且 usage 完整；两边质量 12/12；candidate 相对 control 总 Token `6,115,095 → 4,208,028`（`-31.186%`），耗时 `1,174,966 → 938,489 ms`（`-20.126%`）；不覆盖本轮直接入口和自适应输出 identity |
| 关系 case 受影响审计 | `evidence/relation-audit-v1.json`、`evidence/relation-audit-v2.json` | 保留规则取得全部源码证据；更强规则增加 Token 而未改善 prompt 必答内容，已退出 |
| 回答合同适用性审计 | `evidence/oracle-audit-v1.json` | 两次答案均满足 prompt 最小合同；未复述 supporting mapping type 不构成 core fail |
| 历史隔离模型审计 | `evidence/audit-result-v11.json` | 旧候选核心与严格语义 12/12、格式与严格整体 11/12；不覆盖当前候选 |
| 历史端到端成本 | `development/code-search-benchmark/experiment.py` monitor | 旧候选实际总 Token 1,146,601、404.603 s；不覆盖当前候选 |
| 当前最终候选 | `evidence/audit-result-v15.json`、`evidence/capsule-verification-v15.json` | identity `e32871ba…`；12/12 语义与可见行限通过，1,150,528 Token、363.163 s、48 次命令无失败；capsule、28 个原始流和 2 个环境文件确定性校验通过 |

## 3. 证据边界

冻结五-skill 历史记录为实际总 Token 1,157,111、508.509 s、核心 12/12、严格整体 11/12；按用户要求未重跑。当前候选的 1,150,528 Token 和 363.163 s 方向性分别低 0.57% 与 28.58%，独立审计按可见 prompt 判定 12/12；历史 identity 与 prompt 明示程度不同，因此不把差额声明为严格因果收益。

最终候选没有命令失败、usage 缺失、超时或 postflight 漂移。六类两次重复仍存在正常模型路径波动，且长尾不再共享错误入口、失败回退或固定无用协议；P9 因此在当时证据边界达到收益边缘。随后按 usage 分项进行的 OBS-SQG-013 只识别出“多轮证据取得”是下一研究对象，尚未证明哪些回合可消除，也没有形成 P10 实现证据。项目真源中的消费者迁移和旧 skill 退出已经完成；P9 identity 已于 2026-08-16 正式发布，P10 尚未实施或发布。

新的 advisory scan 未运行，因为当前授权环境未安装 `cargo-audit`；候选 release record 已明确记录该限制。

上一冻结轮已经运行真实独立 agent 路由、LSP 渐进调用和 control/candidate 总成本对照，并由 detached auditor 复算 capsule、usage 与质量。LSP 三案仍直接支持未改动的渐进能力裁决；双环境实验只证明当时冻结的六类 corpus 与身份，不覆盖本轮直接入口、自适应表示、内部预算或更新后的常驻路由。candidate 的 4 次 hard tool failure 与 control 的 2 次仍作为后续可靠性观察保留。

## 4. 新模型输出设计的验证状态

SOL-SQG-010 已实现：rg/fd 普通调用只传原生 argv，显式控制进入 `srcq query`；renderer 在真实结果后比较单行、heading 与保持顺序的路径树；内部预算按完整证据单元分页；全局规则、source-query、CLI 文档和 backend verifier 已迁移。用户已审查并认可单一命中、同文件多命中、共享目录多文件、fd 树、无匹配和错误恢复的真实默认输出；最终 identity 已由本轮 candidate-only 运行、确定性验真和独立语义审计共同冻结。

当前组件证据覆盖 argv 冲突、模式分类、原生 oracle、输出选择、顺序回退、分页/cursor、machine/raw/artifact、AST 非回退、Windows release 与安装生命周期。最终真实隔离候选再覆盖模型质量、总 Token 和耗时；detached auditor 只做语义与结构裁决，`verify-capsule` 独立重算密码学身份和外部原始文件。两者共同关闭 AC-SQG-002、AC-SQG-003 与 GAP-SQG-007。

## 5. 最终逐项审计

| 状态 | 条目 | 当前证据边界 |
| --- | --- | --- |
| 已证明 | REQ-SQG-001；AC-SQG-001 至 AC-SQG-008；CON-SQG-001 至 CON-SQG-003 | 组件、release/install、路由、LSP 渐进三案、最终 12-run usage、独立语义审计和确定性 capsule 校验共同覆盖 |
| 已证明 | UDES-SQG-001 至 UDES-SQG-014 | 唯一 srcq 入口、原生兼容、自动最低充分输出、AST 基线、Windows 生命周期、分层触发、benchmark 隔离与源码升级授权边界均有直接实现或验证 |
| 已执行 | P9 实际 Codex 安装 | 2026-08-16 已通过正式增量入口发布 DirectCompatibility 与 `srcq 0.3.1`；该状态只覆盖已验证的 P9 identity，不授权或证明 P10 |
| 计划中 | GAP-SQG-008 / P10 | 当前只有轮次审计、裁决边界和候选收益门槛；未修改模型规则、skill 或 srcq，不能据此声称 Token 已下降 |

因此 P9 的项目实现、证据和安装已经完成；P10 以 GAP-SQG-008 重新打开优化调查，但必须先完成 TSQG-082，不能把方案文档当作行为改进或收益证据。
