# 统一源码查询网关分支现状

## 1. 文档职责

本文件记录相对 [requirements.md](requirements.md)、[user-design.md](user-design.md) 和 [design.md](design.md) 的当前直接观察、已经闭环的实现边界与剩余差距。观察对象是当前 AgentBase 工作树；项目正式入口已迁移，实际 Codex 安装态仍须取得当次发布同意。历史测试只按其冻结候选身份保留，不自动覆盖后续源码、skill 或 payload。

## OBS-SQG-001 srcq 已承载三个并列命令域

- 状态: verified
- 关联: DES-SQG-001, DES-SQG-002, DES-SQG-003

当前 `srcq 0.2.0` 保留迁移前 AST 顶层命令，并提供不进入 AST help/schema 的 `srcq rg exec/defaults/doctor` 与 `srcq fd exec/defaults/doctor`。rg/fd 原生 argv 保留顺序、重复、空值和 Windows 非 UTF 参数，机器参数插入原生命令 `--` 之前；不能安全结构化的调用可用 raw、artifact 或 passthrough 保持原生字节和副作用语义。迁移前 `_sgy` 与 `sgy.*` 数据协议继续保留以读取既有 AST 产物，但仓库不提供 `sgy.exe` 命令别名。

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

P0 冻结的 `sgy 0.1.2` AST version/help、命令 help、schema 与 capabilities 已作为迁移前 oracle；比较器只规范化正式命令、配置和环境前缀后，对 `srcq` 当前 release 逐项通过。`_sgy` 与 `sgy.*` 数据协议、serializer、cache、profile、fingerprint、process 和 rewrite 合同保持不变。P0 的 ast-grep 0.41.1、0.42.0、0.44.1 真实矩阵仍作为精确版本基线。

## OBS-SQG-004 候选 skill 与当前 payload 已重建

- 状态: verified
- 关联: DES-SQG-008, DES-SQG-009, CON-SQG-003

正式 `skills/source-query` 用一个精炼主文件按“原生快路径 → rg/fd 网关 → AST → LSP”升级，详细 rg/fd、AST 与 LSP 协议按需读取。正式 payload 只有 `SKILL.md`、`agents/openai.yaml` 和三份按需引用；私有 `sgy.exe`、runtime manifest、来源与许可副本已经退出，消费者只调用用户 PATH 中的 `srcq.exe`。`candidate-skill/source-query` 仅作为隔离 benchmark 输入保留；测试、fixture、runner、corpus、result 和 audit 资产仍由项目开发目录承担。

## OBS-SQG-005 benchmark owner 已具备隔离运行合同

- 状态: verified
- 关联: DES-SQG-010, AC-SQG-004

现有 `development/code-search-benchmark` 已扩展为本项目唯一的 corpus、环境身份、`codex exec --json --ephemeral` monitor、A-B-B-A 调度、受影响 case 选择、usage 汇总和 detached audit capsule owner。语料绑定来源文件 hash，并用 `answer_contract.required` 区分 prompt 必答内容与只用于证明正确性的 supporting facts；环境只允许显式差异，失败和超时不被静默替换。capsule 声明可独立复算的规范化哈希算法。历史安装态、收紧候选、五-skill 消融与裸环境数字以各自证据上限登记，不跨 identity 拼接。

## OBS-SQG-006 当前行为证据已刷新但没有形成收益对照

- 状态: partially_verified
- 关联: REQ-SQG-001, AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-004

正式 detached 路由结果 [current.json](../skill-routing/evidence/current.json) 覆盖 65 个首次路由、65 个行为策略和 13 个治理引用场景，三阶段均符合独立 oracle；简单已知读取保持不触发高级 Skill，AST/LSP、分页、写入安全与编辑器操作职责分离。评估 capsule 把首次选择、行为和按需引用分层，避免把详细协议预加载给 evaluator。早期 21-case 候选结果仅作为历史证据保留。

当前轮完整 candidate-only monitor 覆盖六类真实查询各两次；12 次中 11 次有完整 usage，完整 run 的 input 为 `998,139`、output 为 `5,894`、实际总 Token 为 `1,004,033`，全体 wall time 为 `560,744 ms`。`ue-command-dispatch-submit` 的一次运行在已经取得源码证据后遇到 TLS 重连并超时，没有 final answer 与 usage；它保留为真实失败，不能从聚合删除或补跑替换。因此该组数据不是十二次完整总量，也没有 control，不能与历史数字作因果比较。

关系 case 的受影响补测证明模型两次都取得定义、泛型承载字段和响应映射证据。最终保留路由的两次 run 共 `157,053` Token、`64,131 ms`；更强的回答规则变体增至 `170,824` Token、`61,916 ms`，仍未稳定复述 supporting relation，故已退出。独立 oracle 复核确认两次答案均满足原 prompt 的最小合同，把未复述 `mapping.type` 判作核心失败属于越过 prompt；corpus `2026-08-15.2` 已将必答内容与 supporting facts 显式分开。该修正还没有新的同 identity 全量运行。

用户要求冻结且不重跑的五-skill 消融历史记录仍为实际总 Token `1,157,111`、耗时 `508,509 ms`、核心语义 12/12、严格整体 11/12。它缺少当前 experiment 的完整 identity，只能继续作为历史现实依据。由于当前候选的投影、快照、版本和发布身份已改变，旧候选相对该记录的 `0.91%` Token 与 `20.43%` 耗时方向差不能证明当前实现已达收益边缘；TSQG-061—063 已据此重开。

## OBS-SQG-007 srcq 已有独立 Windows 安装生命周期

- 状态: verified
- 关联: DES-SQG-011, UDES-SQG-009

`tools/srcq/scripts/install-srcq.ps1` 从 `srcq.release/v1` 受校验归档安装到默认 `%LOCALAPPDATA%\Programs\srcq\current`，维护唯一用户 `PATH` 项，并显式提供 `Install`、`Status`、`Upgrade` 和 `Uninstall`。安装会验证归档 SHA-256、精确成员集合、目标架构、逐文件 hash 和 `srcq --version`；升级使用 staging、旧版本备份与失败恢复；卸载依据 `srcq.install/v1` 状态只移除受管成员和安装器增加的 PATH 项，默认保留 cache。

隔离生命周期测试覆盖幂等安装、状态读回、新 PowerShell 进程 PATH 解析、升级提交失败回滚、恶意 ZIP 与篡改状态拒绝、正常升级、保留并发 PATH 修改、未知安装文件、用户配置和默认 cache，以及显式 cache 清理。候选 skill 已退出私有运行时；正式旧 skill 与部署合同仍待消费者迁移。

## OBS-SQG-008 LSP 原生渐进发现已经通过候选侧实测

- 状态: verified
- 关联: AC-SQG-002, AC-SQG-005, DES-SQG-012, UDES-SQG-011

`vscode-lsp-mcp` 当前在一次 `tools/list` 中固定返回 18 个工具；按真实 MCP 公开字段序列化的工具定义合计为 `15,747` 字符。这是可观测的工具合同尺寸，不等于经 tokenizer 和客户端序列化后的实际 Token。

隔离真实 Codex 三案分别覆盖不需要 LSP、只需符号身份和随后新增精确引用需要。实际 MCP 调用严格为 0、`list_workspaces + symbol_info`、`list_workspaces + symbol_info + get_references`；三案答案质量、usage、退出码和独立 capsule 哈希审计均通过，总 Token 分别为 `112,858`、`173,459`、`207,743`。这证明当前候选使用宿主原生延迟目录即可按必要证据逐级展开，不需要新增 `srcq lsp` 第二入口；数据只证明候选侧行为和绝对成本，不与旧 control 拼成因果收益。

## GAP-SQG-005 srcq 正式命名已经迁移

- 状态: resolved
- 关联: DES-SQG-011, UDES-SQG-009, UDES-SQG-010, OBS-SQG-007

当前源码目录、Cargo 包、可执行文件、安装脚本、默认安装目录、状态、归档、release manifest、候选 skill 和验证入口均已使用 Source Query Gateway / `srcq`。迁移前历史证据和冻结 AST 数据协议保留 `sgy` 身份；它们不提供可执行别名、安装 fallback 或第二运行时。正式旧 skill 和部署消费者的退出由 GAP-SQG-004 单独跟踪。

## GAP-SQG-006 LSP 渐进暴露路径已经闭环

- 状态: resolved
- 关联: AC-SQG-005, DES-SQG-012, UDES-SQG-011, OBS-SQG-008

真实隔离三案已经证明 LSP 能力按证据需要从 0 到单项再到多阶段展开，未发生无关 MCP 调用或失败。由于需求允许原生延迟发现达标时不新增 CLI，本分支不实现 `srcq lsp`；未来只有宿主行为回退且同身份实测证明总成本或可靠性不达标时才重开该设计。

## GAP-SQG-004 独立安装入口已成为项目消费者唯一运行时

- 状态: resolved
- 关联: DES-SQG-011, UDES-SQG-009, OBS-SQG-007

`tools/srcq` 是唯一运行时 owner；正式 `source-query`、CI、插件与直接兼容部署合同只消费 PATH 中的 `srcq.exe`。三个旧查询 Skill、Python rg wrapper、内置 sgy 与其同步/签署合同已经退出；缺失或版本不符时只给出安装、升级和开启新终端的恢复动作。实际 Codex 根目录是否更新仍由逐次发布授权独立决定。

## GAP-SQG-003 当前候选缺少身份一致的完成证据

- 状态: open
- 关联: REQ-SQG-001, AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-004

当前后端、AST 冻结、候选 payload、独立路由和 candidate-only 监控均已有直接证据，但 corpus 回答合同刚刚修正，完整运行又有一次 usage 缺失，且用户要求冻结的 control 与当前 Codex、工作区、候选及 corpus identity 不同。继续单独重跑 candidate 不会产生可比较收益结论；只有用户允许一次同 identity 的 control/candidate 对照，或明确接受不形成当前因果收益结论，才能关闭该差距。在此之前不得恢复收益边缘、主线采纳或发布完成判断。

## GAP-SQG-002 项目主线迁移已实施

- 状态: resolved
- 关联: CON-SQG-001, DES-SQG-008

[migration-candidate.md](migration-candidate.md) 记录了旧 skill、Python rg wrapper、全局路由和消费者的原子迁移；当前项目真源已完成迁移，Skill、静态合同、三阶段 detached 路由、部署与插件 payload 验证通过。Codex 安装态没有随项目修改自动变化，仍需用户针对当次发布明确同意。
