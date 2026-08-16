# 统一源码查询网关分支现状

## 1. 文档职责

本文件记录相对 [requirements.md](requirements.md)、[user-design.md](user-design.md) 和 [design.md](design.md) 的当前直接观察、已经闭环的实现边界与剩余差距。观察对象是当前 AgentBase 工作树；项目正式入口已迁移，实际 Codex 安装态仍须取得当次发布同意。历史测试只按其冻结候选身份保留，不自动覆盖后续源码、skill 或 payload。

## OBS-SQG-001 srcq 已承载三个并列命令域

- 状态: verified
- 关联: DES-SQG-001, DES-SQG-002, DES-SQG-003

当前 `srcq 0.3.0` 保留迁移前 AST 顶层命令，并以 `srcq rg <native argv...>`、`srcq fd <native argv...>` 提供不抢占任何原生 token 的普通入口；定向 model、machine、native、artifact、diagnostic 与 continuation 位于独立的 `srcq query <rg|fd> ...` 控制面。rg/fd 原生 argv 保留顺序、重复、空值和 Windows 非 UTF 参数，机器参数插入原生命令 `--` 之前；不能安全结构化的调用可用 native、artifact 或 passthrough 保持原生字节和副作用语义。迁移前 `_sgy` 与 `sgy.*` 数据协议继续保留以读取既有 AST 产物，但仓库不提供 `sgy.exe` 命令别名。

29 个 ripgrep 15.1.0 与 fd 10.4.2 公开模式样本均有唯一分类，7 个 raw/artifact oracle 已逐字回放。`defaults` 只解释参数和模式，不发现或启动引擎。

## OBS-SQG-002 查询结果按所选证据单元投影并按需持久化快照

- 状态: verified
- 关联: DES-SQG-004, DES-SQG-005, DES-SQG-006, DES-SQG-007

直接反例曾证明旧实现先按 rg 原始 match/context 事件分页、再投影 files/locations/summary：`summary --limit 1` 为已经完整的摘要生成无意义续页；files 把匹配事件数当作文件数；带 context 的 locations 第一页可为空却声称已展示一项。当前实现改为先形成视图自己的证据单元，再计算总量与分页；summary 是终止视图，files 按去重后的匹配文件分页，locations 只按匹配位置分页。相应真实集成回归已覆盖普通 rg、fd、native files、count 和 vimgrep。

普通 model 成功结果只返回证据正文；完整结果不附加 envelope、schema、固定回执或 backend/version/view 等内部元数据。只有续页、截断、错误或恢复需要时才追加最短差异信息；显式 `--receipt full`、machine、native 与 artifact 仍可取得其请求对象。完整默认结果不再计算或持久化无消费者的 snapshot；只有续页或 full 回执需要身份时才计算 hash、原子持久化并返回精确 cursor。进程与持久 snapshot 的既有上限、hash 和混用拒绝仍保留。

fd 会冻结对象类型并为每个显式根建立可逆 trie；只有估算 Token 确实低于 flat 时 auto 才选 tree。rg 普通 batch 消费原生 JSON 事件，grouped、records、locations、files、summary 与 lossless 均在相同证据签名内选择；count、vimgrep 和特殊模式使用独立严格解析或透传。

## OBS-SQG-003 AST 公开合同保持冻结

- 状态: verified
- 关联: DES-SQG-001, DES-SQG-009

P0 冻结的 `sgy 0.1.2` AST version/help、命令 help、schema 与 capabilities 已作为迁移前 oracle；比较器只规范化正式命令、配置和环境前缀后，对 `srcq` 当前 release 逐项通过。`_sgy` 与 `sgy.*` 数据协议、machine serializer、cache、profile、fingerprint、process 和 rewrite 合同保持不变。P0 的 ast-grep 0.41.1、0.42.0、0.44.1 真实矩阵仍作为精确版本基线。该证据冻结机器兼容和 AST 语义，不要求新增 model renderer 逐字保持当前 YAML。

## OBS-SQG-004 候选 skill 与当前 payload 已重建

- 状态: verified
- 关联: DES-SQG-008, DES-SQG-009, CON-SQG-003

正式 `skills/source-query` 用一个精炼主文件按“已知正文直接读取 → srcq rg/fd 普通入口 → 按需 AST → 渐进 LSP”组织，只有完整性、分页、特殊协议或定向输出才读取 rg/fd 细则。正式 payload 只有 `SKILL.md`、`agents/openai.yaml` 和三份按需引用；私有 `sgy.exe`、runtime manifest、来源与许可副本已经退出，消费者只调用用户 PATH 中的 `srcq.exe`。`candidate-skill/source-query` 仅作为隔离 benchmark 输入保留；测试、fixture、runner、corpus、result 和 audit 资产仍由项目开发目录承担。

## OBS-SQG-005 benchmark owner 已具备隔离运行合同

- 状态: verified
- 关联: DES-SQG-010, AC-SQG-004

现有 `development/code-search-benchmark` 已扩展为本项目唯一的 corpus、环境身份、`codex exec --json --ephemeral` monitor、A-B-B-A 调度、受影响 case 选择、usage 汇总和 detached audit capsule owner。语料绑定来源文件 hash，并用 `answer_contract.required` 区分 prompt 必答内容与只用于证明正确性的 supporting facts；环境只允许显式差异，失败和超时不被静默替换。capsule 声明可独立复算的规范化哈希算法。历史安装态、收紧候选、五-skill 消融与裸环境数字以各自证据上限登记，不跨 identity 拼接。

失败的运行前置审计确认四个互相独立的问题：read-only sandbox 在模型执行前拦截真实 `srcq` 查询；未初始化的隔离 home 会在首次 subject 内刷新系统 skill；复制全部安装 skill 会因大型无关知识库触发 CLI 扫描上限；未预登记工作区 trust 会在首次访问后改写两侧 `config.toml`，使冻结身份失效。此外，旧 `target/release/srcq.exe` 虽报告同版本，却仍使用过时参数入口。当前 owner 已要求 `danger-full-access + approval_policy=never`，仍以只读 prompt 和运行后身份读回约束副作用；prepare 会绑定 Codex 二进制 hash，预登记正式工作区，先执行并单独计量 control/candidate 代表性命令，再冻结环境。隔离 home 默认只复制因果 skill 集并拒绝 `%TEMP%` 路径；候选 srcq 复制前必须通过真实直觉入口。大型工作区可声明相对 identity scope，oracle 必须落在该范围内，范围内的 patch 与未跟踪内容仍完整哈希。当前非运行型验证覆盖 benchmark owner 26 项与 home 准备 9 项测试；正式 corpus 已在新的同身份环境中运行，结果见 GAP-SQG-007。

## OBS-SQG-006 上一冻结身份的行为与收益证据已经闭环

- 状态: verified
- 关联: REQ-SQG-001, AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-004

原冻结 identity 的 65 个首次路由、65 个行为策略和 13 个治理引用场景曾作为过程依据。当前 [current.json](../skill-routing/evidence/current.json) 已由三个互相独立的 detached 运行刷新为 66/66 首次路由、66/66 行为策略和 13/13 治理引用通过；简单已知读取保持不触发高级 Skill，AST/LSP、分页、写入安全与编辑器操作职责继续分离。

早先 candidate-only monitor 的 `1,004,033` Token 与一次 TLS 超时仍作为失败机制和历史过程证据保留，不再承担当前相对收益裁决。

关系 case 的受影响补测证明模型两次都取得定义、泛型承载字段和响应映射证据。独立 oracle 复核确认 prompt 必答内容与 supporting facts 必须分开，corpus 随后升级到 `2026-08-15.3`，并已纳入当前同身份全量对照。

当前 control/candidate 由同一安装态按显式 allowlist 构建，除全局查询路由、旧查询 skills 退出、正式 `source-query`/`symbol-structure-workflow` 与 candidate 私有 `srcq.exe` 外无意外差异。24 次运行全部正常退出且 usage 完整；独立审计确认两边必需与核心语义均为 24/24。control 实际总 Token 为 `6,115,095`，candidate 为 `4,208,028`（`-31.186%`）；总耗时从 `1,174,966 ms` 降到 `938,489 ms`（`-20.126%`）；工具调用从 268 降到 167。六个 case 的两次聚合均同时降低 Token 和耗时，因此当前候选在质量、Token、速度顺序下保留。单对运行仍有 4/12 Token 反向和 5/12 耗时反向，说明随机波动存在；不据此继续堆叠规则或针对语料调优。

## OBS-SQG-007 srcq 已有独立 Windows 安装生命周期

- 状态: verified
- 关联: DES-SQG-011, UDES-SQG-009

`tools/srcq/scripts/install-srcq.ps1` 从 `srcq.release/v1` 受校验归档安装到默认 `%LOCALAPPDATA%\Programs\srcq\current`，维护唯一用户 `PATH` 项，并显式提供 `Install`、`Status`、`Upgrade` 和 `Uninstall`。安装会验证归档 SHA-256、精确成员集合、目标架构、逐文件 hash 和 `srcq --version`；升级使用 staging、旧版本备份与失败恢复；卸载依据 `srcq.install/v1` 状态只移除受管成员和安装器增加的 PATH 项，默认保留 cache。

隔离生命周期测试覆盖幂等安装、状态读回、新 PowerShell 进程 PATH 解析、升级提交失败回滚、恶意 ZIP 与篡改状态拒绝、正常升级、保留并发 PATH 修改、未知安装文件、用户配置和默认 cache，以及显式 cache 清理。`Status` 现会复核 manifest 身份、全部受管文件哈希、实际版本和唯一 PATH 项；同版本 `Install` 能修复被篡改二进制或缺失 PATH。真实 Codex Publish 在写入前复用该状态与 `doctor`，缺失运行时会局部阻断；部署沙箱不消费宿主安装。正式 skill、部署与插件合同已经退出私有运行时和旧查询 skill。

当前 `0.3.0` 源码快照 `sha256:35fc5293e472f372184bdfdbe605ed20fd0556a5b800fffb56ddd581ed9a212f` 已生成 Windows x86_64 MSVC 归档，归档 SHA-256 为 `00cfdebd21a25faa9a7d517c68aedda407df4681541144fda2723851fb4da8a0`。隔离生命周期用上一份 `0.2.0` 归档升级到该 `0.3.0` 候选，安装、幂等、完整性读回、受管漂移修复、新进程 PATH、失败回滚、恶意 ZIP、篡改 state、真实升级、doctor、卸载边界、并发 PATH、配置/cache 保留与显式 cache 清理全部通过；没有写入真实用户安装位置。

上一冻结 AST 身份以本机受支持的原生 ast-grep 0.44.1 绑定明确版本 oracle 后，15 项 ignored 真实引擎测试通过，覆盖 run/scan/rewrite、cache/process、LSP、TTY、completion、new/test、失败/取消和 Windows Console Ctrl-C。本轮恢复了顶层 help 中原有 Operational、cache 与 process 语法提示，并用只投影 AST 表面的基线比较证明当前 `0.3.0` 未因新增 rg/fd/query 行发生 AST help/schema/capabilities 回退。

## OBS-SQG-008 LSP 原生渐进发现已经通过候选侧实测

- 状态: verified
- 关联: AC-SQG-002, AC-SQG-005, DES-SQG-012, UDES-SQG-011

`vscode-lsp-mcp` 当前在一次 `tools/list` 中固定返回 18 个工具；按真实 MCP 公开字段序列化的工具定义合计为 `15,747` 字符。这是可观测的工具合同尺寸，不等于经 tokenizer 和客户端序列化后的实际 Token。

隔离真实 Codex 三案分别覆盖不需要 LSP、只需符号身份和随后新增精确引用需要。实际 MCP 调用严格为 0、`list_workspaces + symbol_info`、`list_workspaces + symbol_info + get_references`；三案答案质量、usage、退出码和独立 capsule 哈希审计均通过，总 Token 分别为 `112,858`、`173,459`、`207,743`。这证明当前候选使用宿主原生延迟目录即可按必要证据逐级展开，不需要新增 `srcq lsp` 第二入口；数据只证明候选侧行为和绝对成本，不与旧 control 拼成因果收益。

## OBS-SQG-009 普通查询入口与结果后置输出已经实现

- 状态: verified
- 关联: AC-SQG-002, AC-SQG-007, AC-SQG-008, DES-SQG-003, DES-SQG-004, DES-SQG-005, DES-SQG-006, DES-SQG-007, UDES-SQG-002, UDES-SQG-003, UDES-SQG-004, UDES-SQG-006

当前工作区候选已经建立 model、machine 与 native/artifact 三输出面，并完成 `srcq rg <native argv...>`、`srcq fd <native argv...>` 普通入口。backend 后全部 token 都属于原生命令，模型无需先提供 `exec`、`--`、view、heading、tree、limit、receipt 或正文预算；显式控制统一进入 `srcq query`，不与原生参数争用。

planner 在取得真实完整事实后，才对同一证据页比较平铺 locator、文件 heading、共享路径前缀树及其位置/正文叶子，选择实际模型文本成本更低者。路径树按原生首次出现顺序构造；若前缀重入、重复、对象类型或父子关系不能无损表达，则自动退回平铺。默认内部 2048 estimated-token 软预算和 80 个证据单元硬页上限共同决定完整页边界，大结果只在完整证据单元后返回 snapshot 绑定的精确 cursor。直觉入口、renderer 与预算完成后，srcq workspace 的 `cargo ci-test`、`cargo ci-build`、`cargo lint` 和 `cargo fmt-check` 通过；随后有序树和原生 token 冲突修正又通过 srcq-cli 37 项单元与 19 项真实网关集成测试。真实 rg/fd 15.1.0/10.4.2 smoke、ast-grep 0.44.1 AST smoke，以及开发合同的 29 个 rg/fd 公开主模式分类和 7 个原生 oracle 回放通过。新的独立 Codex 对照已经运行，但暴露运行时版本兼容和直觉入口可发现性问题，不能据组件验证推导总成本收益。

## OBS-SQG-010 当前候选的失败回合抵消了输出压缩

- 状态: verified
- 关联: AC-SQG-001, AC-SQG-002, AC-SQG-006, AC-SQG-007, AC-SQG-008, DES-SQG-003, DES-SQG-008, DES-SQG-009, UDES-SQG-002, OBS-SQG-009

experiment identity `6a30fc236bf36c54910d38c625c1595929e623ccfb3391ddb112cafc6148c4ab` 完成 24 次 A-B-B-A subject 与 detached 独立审计；24/24 均正常退出、usage 完整且 postflight 身份未漂移。审计结果归档于 [audit-result-v14.json](evidence/audit-result-v14.json)，文件 SHA-256 为 `04966624dfc2e6caf22313108fe6d0dcb7d7305322c73c371da129473c673399`。candidate 必需/核心语义为 12/12，control 为 11/12；candidate 格式与整体为 11/12，control 分别为 10/12、9/12。

成本结果反向：subject Token 从 `1,526,268` 增至 `2,845,522`（`+86.437%`），含 setup 从 `1,558,647` 增至 `2,877,939`（`+84.643%`），同为正常 service tier 的 subject 耗时从 `504,290 ms` 增至 `830,366 ms`（`+64.660%`），工具调用从 75 增至 126；12 个配对中有 10 个 candidate Token 更高。candidate 的 35 个非零工具退出中，17 个直接来自 srcq 对 PATH 中 rg 15.2.0 的精确版本拒绝；简单文件发现连续尝试 `files`、`--files` 等不存在入口；已知 C++ 函数完整定义任务在文本定位足以继续时仍反复尝试无法匹配实际声明形态的 AST pattern。输入 Token 增量为 `1,306,000`，远高于输出增量 `13,254`，说明主要成本来自失败后的额外模型回合和上下文重放，而不是最终答案长度。

## OBS-SQG-011 P9 三项失败机制已经在组件边界消除

- 状态: verified
- 关联: AC-SQG-001, AC-SQG-002, AC-SQG-006, AC-SQG-007, AC-SQG-008, DES-SQG-003, DES-SQG-008, DES-SQG-009, SOL-SQG-012, SOL-SQG-013, SOL-SQG-014, OBS-SQG-010

`srcq 0.3.1` 不再以 rg、fd 或 ast-grep 的版本字符串拒绝可启动后端。默认读取在结构转换失败且已捕获内容是安全 UTF-8 文本时复用同次字节；machine 明确返回转换错误，副作用模式不预探测、不重放。真实 rg 15.2、伪造 99.0 同协议、变化协议、安全降级、原生错误和副作用单次执行均有回归覆盖。`srcq files`、根级 AST 命令和缺失分隔符只返回指向唯一正式入口的一行修正。

全局规则和 `source-query` 已把普通路径固定为“已知正文直接有界读取、文件发现 `srcq fd`、文本查询 `srcq rg`”，不要求预加载 skill、help、doctor 或展示参数；已知名称和“完整定义”不再直接触发 AST。只有文本证据仍缺语法边界、候选区分、截断恢复或结构关系时升级 AST，AST 空结果没有新源码语法证据时不得盲试；真实身份、类型、引用或层级会改变结论时才升级 LSP。静态路由合同 66 个场景、31 个 strict 和 11/11 skill 正反覆盖通过。

当前 Windows 候选绑定源码快照 `sha256:1b4c2b17fe04cada4af84362c861586c45e5389acafc08e8e34e49736fc1b512`，归档 `srcq-0.3.1-x86_64-pc-windows-msvc.zip` 的 SHA-256 为 `2ce4c7351ca7d7e469f66b473852e3a6b97c52e1935fe5e4544042df602b2915`。workspace 门禁、当前真实 ast-grep 0.44.1 的 8 项受影响测试、AST 0.3.1 基线、29 个后端模式、7 个原生 oracle 和 0.3.0→0.3.1 隔离安装生命周期通过；`cargo-audit` 因宿主未安装而未刷新。该段只证明三项根因机制和发行边界，后续真实模型闭环见 OBS-SQG-012。

## OBS-SQG-012 当前候选的真实模型质量与成本已经闭环

- 状态: verified
- 关联: REQ-SQG-001, AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-004, AC-SQG-006, AC-SQG-007, AC-SQG-008, UDES-SQG-007, UDES-SQG-012, UDES-SQG-013, OBS-SQG-011

最终 candidate-only experiment identity 为 `e32871ba9c0f8b19716e7b191260c29666939879215350baa4604d1bfd9c7ac4`。六类任务各运行两次，12/12 正常退出且 usage 完整，48 次命令全部成功，postflight 没有身份漂移；总 Token 为 `1,150,528`，其中 input `1,140,588`、cached input `932,096`、output `9,940`、reasoning output `4,699`，端到端耗时 `363.163 s`。独立 detached audit 逐案确认语义、正式源码范围和可见行数限制 12/12 通过，结果见 [audit-result-v15.json](evidence/audit-result-v15.json)，文件 SHA-256 为 `5a8d8d797ef8b8ed1a8a46dd5a30de5bbab8bc9d940c92030f60c441b0b64b30`。

capsule `b2636807dd68b69eafd5cc203ef7670b714779002dfccfb528a5c389312adf4a` 由新增的确定性 `verify-capsule` 重算 experiment identity、28 个原始流和两个环境文件并通过，结果见 [capsule-verification-v15.json](evidence/capsule-verification-v15.json)。密码学计算和语义裁决因此各有唯一 owner，不要求审计模型伪造 SHA 计算。

冻结五-skill 历史记录为 `1,157,111` Token、`508.509 s`、核心 12/12、严格整体 11/12，按用户要求未重跑。当前候选方向性少 `6,583` Token（`-0.57%`）、快 `145.346 s`（`-28.58%`），且当前可见合同严格质量为 12/12；两者 identity 和 prompt 明示程度不同，因此该差额只证明当前绝对成本已进入并略低于历史参照，不声明严格因果百分比。调优已经消除版本拒绝、错形试探、AST 盲试、权威源码副本污染、`srcq lsp` 猜测和普通 DTO/唯一调用的高级 skill 预加载；剩余单次波动没有共同失败机制，继续增加常驻规则的预期收益已低于 Token 与过拟合成本。

## OBS-SQG-013 剩余成本主要集中在多轮证据取得

- 状态: verified
- 关联: REQ-SQG-001, AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-007, DES-SQG-010, DES-SQG-014, UDES-SQG-012, OBS-SQG-012

最终候选的 `1,150,528` Token 中，input 为 `1,140,588`，其中 cached input `932,096`、普通 input `208,492`；output 为 `9,940`，其中 reasoning output `4,699`、可见 output `5,241`。它执行 48 次工具命令，而冻结五-skill 历史为 29 次。按 benchmark 已冻结的相对价格系数换算，短上下文成本单位从历史 `470,501.6` 降至当前 `361,341.6`（`-23.20%`），长上下文从 `919,448.2` 降至 `692,863.2`（`-24.64%`）；这说明缓存输入的单价优势已经降低计费等价成本，但原始总 Token 仍被更多模型—工具往返重放。

三个相对历史上升的任务共消耗 `771,535` Token、28 次工具命令；历史对应任务为 `657,616` Token、17 次工具调用。逐案结果仍全部正确且命令无失败，因此这些增量不能归因于旧版失败恢复，也不能仅凭调用数认定冗余。现有证据只支持把权威范围确认、名称定位、完整正文、关系映射、依赖续查和重复确认逐条分类，判断哪些回合相互独立、哪些必须顺序执行、哪些暴露真实工具能力缺口；在完成该审计前，不能把新增 `inspect`、批量查询或更强常驻规则当成既定方案。

## GAP-SQG-008 高成本查询尚未证明最少必要证据轮次

- 状态: open
- 关联: REQ-SQG-001, AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-007, DES-SQG-014, UDES-SQG-002, UDES-SQG-003, UDES-SQG-012, UDES-SQG-013, OBS-SQG-013

当前候选已经满足质量、输出和可靠性合同，但三个高成本任务在多个模型回合中分别取得范围、定位、正文和关系证据。尚无完整归因能证明这些回合是任务固有依赖、模型未按闭环规划，还是现有 srcq 无法在保持边界和失败语义时共同返回必要证据。缺口不是“缺少一个名为 `inspect` 的命令”，而是缺少可复核的最小证据图、全部 28 次调用的分类以及每个拟合并回合的证据等价证明。只有这些输入完成后，才能裁决无需改动、精炼稳定规划原则、扩展既有命令域或新增高层入口中的最小充分方案。

## GAP-SQG-007 查询意图入口与自适应模型输出已经闭环

- 状态: resolved
- 关联: REQ-SQG-001, AC-SQG-001, AC-SQG-002, AC-SQG-006, AC-SQG-007, AC-SQG-008, UDES-SQG-002, UDES-SQG-003, UDES-SQG-004, UDES-SQG-006, UDES-SQG-013, UDES-SQG-014, OBS-SQG-009, OBS-SQG-010, OBS-SQG-011, OBS-SQG-012

组件、消费者、路由、真实模型质量、端到端成本和独立复核已经共同覆盖当前候选。该 P9 identity 已于 2026-08-16 通过正式增量入口发布为 DirectCompatibility 安装；P10 当前只有项目方案，尚未修改运行时或再次发布。每次后续发布仍独立受逐次授权约束。

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

- 状态: resolved
- 关联: REQ-SQG-001, AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-004

上一迁移身份的同 identity 对照已经完成：24/24 运行与 usage 完整、环境差异符合 allowlist、两边质量相同，candidate 总 Token 降低 `31.186%`，并在前两项不退化后把总耗时降低 `20.126%`。独立结果归档于 [audit-result-v13.json](evidence/audit-result-v13.json)。该证据关闭当时迁移身份的完成差距，但不覆盖此后新增的直觉入口、自适应输出、更新 corpus、其他模型或项目；Codex 发布仍需逐次单独授权。

## GAP-SQG-002 项目主线迁移已实施

- 状态: resolved
- 关联: CON-SQG-001, DES-SQG-008

[migration-candidate.md](migration-candidate.md) 记录了旧 skill、Python rg wrapper、全局路由和消费者的原子迁移；当前项目真源已完成迁移，Skill、静态合同、三阶段 detached 路由、部署与插件 payload 验证通过。Codex 安装态没有随项目修改自动变化，仍需用户针对当次发布明确同意。
