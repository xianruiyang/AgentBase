# 统一源码查询网关分支现状

## 1. 文档职责

本文件记录相对 [requirements.md](requirements.md)、[user-design.md](user-design.md) 和 [design.md](design.md) 的当前直接观察、已经闭环的实现边界与剩余差距。观察对象是当前 AgentBase 工作树；项目正式入口已迁移，实际 Codex 安装态仍须取得当次发布同意。历史测试只按其冻结候选身份保留，不自动覆盖后续源码、skill 或 payload。

## OBS-SQG-001 srcq 已承载四个并列命令域

- 状态: verified
- 关联: DES-SQG-001, DES-SQG-002, DES-SQG-003

当前 `srcq 0.4.1` 保留迁移前 AST 顶层命令，并以 `srcq rg <native argv...>`、`srcq fd <native argv...>`、`srcq scc <native argv...>` 提供不抢占任何原生 token 的普通入口；定向 model、machine、native、artifact、diagnostic 与 continuation 位于独立的 `srcq query <rg|fd|scc> ...` 控制面。原生 argv 保留顺序、重复、空值和 Windows 非 UTF 参数，机器参数插入原生命令 `--` 之前；不能安全结构化的调用可用 native、artifact 或 passthrough 保持原生字节和副作用语义。迁移前 `_sgy` 与 `sgy.*` 数据协议继续保留以读取既有 AST 产物，但仓库不提供 `sgy.exe` 命令别名。

29 个 ripgrep 15.1.0/fd 10.4.2 与 7 个 scc 3.7.0 公开模式样本均有唯一分类，9 个 raw/artifact oracle 已逐字或规范化回放。`defaults` 只解释参数和模式，不发现或启动引擎。

## OBS-SQG-002 查询结果按所选证据单元投影并按需持久化快照

- 状态: verified
- 关联: DES-SQG-004, DES-SQG-005, DES-SQG-006, DES-SQG-007

直接反例曾证明旧实现先按 rg 原始 match/context 事件分页、再投影 files/locations/summary：`summary --limit 1` 为已经完整的摘要生成无意义续页；files 把匹配事件数当作文件数；带 context 的 locations 第一页可为空却声称已展示一项。当前实现改为先形成视图自己的证据单元，再计算总量与分页；summary 是终止视图，files 按去重后的匹配文件分页，locations 只按匹配位置分页。相应真实集成回归已覆盖普通 rg、fd、native files、count 和 vimgrep。

普通 model 成功结果只返回证据正文；完整结果不附加 envelope、schema、固定回执或 backend/version/view 等内部元数据。query 续页以 `@more` 返回剩余数量，并在 `@next` 后投影 PowerShell 7 可直接执行的完整命令；其他截断、错误或恢复仍只追加最短差异信息。显式 `--receipt full`、machine、native 与 artifact 仍可取得其请求对象。直接入口在完整结果不超过 512 个证据单元且完整表示仍落在原 2048 estimated-Token 总预算时越过初始 80 项限制；单文件只有在同一总预算内才把单行正文上限提高到 1024，多文件或更大结果仍分页。完整默认结果不再计算或持久化无消费者的 snapshot；只有续页或 full 回执需要身份时才计算 hash、原子持久化并返回精确 cursor。进程与持久 snapshot 的既有上限、hash 和混用拒绝仍保留。

fd 会冻结对象类型并为每个显式根建立可逆 trie；只有估算 Token 确实低于 flat 时 auto 才选 tree。rg 普通 batch 消费原生 JSON 事件，grouped、records、locations、files、summary 与 lossless 均在相同证据签名内选择；count、vimgrep 和特殊模式使用独立严格解析或透传。

## OBS-SQG-003 AST 公开合同保持冻结

- 状态: verified
- 关联: DES-SQG-001, DES-SQG-009

P0 冻结的 `sgy 0.1.2` AST version/help、命令 help、schema 与 capabilities 已作为迁移前 oracle；比较器只规范化正式命令、配置和环境前缀后，对 `srcq` 当前 release 逐项通过。`_sgy` 与 `sgy.*` 数据协议、machine serializer、cache、profile、fingerprint、process 和 rewrite 合同保持不变。P0 的 ast-grep 0.41.1、0.42.0、0.44.1 真实矩阵仍作为精确版本基线。该证据冻结机器兼容和 AST 语义，不要求新增 model renderer 逐字保持当前 YAML。

## OBS-SQG-004 候选 skill 与当前 payload 已重建

- 状态: verified
- 关联: DES-SQG-008, DES-SQG-009, CON-SQG-003

正式 `skills/source-query` 用一个精炼主文件按“已知正文直接读取 → srcq rg/fd/scc 普通入口 → 按需高级 scc/AST → 渐进 LSP”组织，只有完整性、分页、特殊协议或定向输出才读取对应细则。正式 payload 只有 `SKILL.md`、`agents/openai.yaml` 和四份按需引用；私有 `sgy.exe`、runtime manifest、来源与许可副本已经退出，消费者只调用用户 PATH 中的 `srcq.exe`。`candidate-skill/source-query` 及其 routing capsule helper 仅冻结 P9/P10 的隔离 benchmark 输入与复算入口，不是当前 payload 或模型消费者；当前模型入口是正式 `skills/source-query`，路由评估由 `development/skill-routing` 维护。测试、fixture、runner、corpus、result 和 audit 资产仍由项目开发目录承担。旧 `ast-grep-token-safe`、`fd-usage` 与 `rg-token-safe` 安装路径由 `development/codex-deployment/managed_asset_lifecycle.json` 以稳定身份持有退役状态，使旧主机升级时由正式 Publish 备份并移除残留，而不是仅凭当前 payload 不再列出它们。

## OBS-SQG-005 benchmark owner 已具备隔离运行合同

- 状态: verified
- 关联: DES-SQG-010, AC-SQG-004

现有 `development/code-search-benchmark` 已扩展为本项目唯一的 corpus、环境身份、`codex exec --json --ephemeral` monitor、A-B-B-A 调度、受影响 case 选择、usage 汇总和 detached audit capsule owner。语料绑定来源文件 hash，并用 `answer_contract.required` 区分 prompt 必答内容与只用于证明正确性的 supporting facts；环境只允许显式差异，失败和超时不被静默替换。capsule 声明可独立复算的规范化哈希算法。历史安装态、收紧候选、五-skill 消融与裸环境数字以各自证据上限登记，不跨 identity 拼接。

失败的运行前置审计确认四个互相独立的问题：read-only sandbox 在模型执行前拦截真实 `srcq` 查询；未初始化的隔离 home 会在首次 subject 内刷新系统 skill；复制全部安装 skill 会因大型无关知识库触发 CLI 扫描上限；未预登记工作区 trust 会在首次访问后改写两侧 `config.toml`，使冻结身份失效。此外，旧 `target/release/srcq.exe` 虽报告同版本，却仍使用过时参数入口。当前 owner 已要求 `danger-full-access + approval_policy=never`，仍以只读 prompt 和运行后身份读回约束副作用；prepare 会绑定 Codex 二进制 hash，预登记正式工作区，先执行并单独计量 control/candidate 代表性命令，再冻结环境。隔离 home 默认只复制因果 skill 集并拒绝 `%TEMP%` 路径；候选 srcq 复制前必须通过真实直觉入口。大型工作区可声明相对 identity scope，oracle 必须落在该范围内，范围内的 patch 与未跟踪内容仍完整哈希。当前非运行型验证覆盖 benchmark owner 27 项与 home 准备/路由 11 项测试；正式 corpus 已在新的同身份环境中运行，结果见 GAP-SQG-007 与 GAP-SQG-008。

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

首个独立运行时 `0.3.0` 与后续 `0.3.1` 的源码快照和归档保留为历史安装证据。当前 `0.4.0` 归档已通过从 `0.3.1` 升级的隔离生命周期：安装、幂等、完整性读回、受管漂移修复、新进程 PATH、失败回滚、恶意 ZIP、篡改 state、真实升级、doctor、卸载边界、并发 PATH、配置/cache 保留与显式 cache 清理全部通过；测试没有写入真实用户安装位置。

上一冻结 AST 身份以本机受支持的原生 ast-grep 0.44.1 绑定明确版本 oracle 后，15 项 ignored 真实引擎测试通过，覆盖 run/scan/rewrite、cache/process、LSP、TTY、completion、new/test、失败/取消和 Windows Console Ctrl-C。`0.4.0` 继续用只投影 AST 表面的基线比较证明新增 scc/query 行没有造成 AST help/schema/capabilities 回退。

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

## OBS-SQG-014 P10 第一阶段轮次审计只证明命令面可表达

- 状态: superseded
- 关联: AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-006, AC-SQG-007, DES-SQG-014, UDES-SQG-012, UDES-SQG-013, OBS-SQG-013, DEC-SQG-001

[round-trip-audit-p10.md](evidence/round-trip-audit-p10.md) 已把三个上升 case 的 6 个 run、28 次命令逐项绑定到前置知识、直接产出和后续消费；数量、`771,535` Token 与 106,219 个 stdout 字符均与原始记录对账。反事实证据图在不新增命令的条件下得到约 10 次调用的表达下界：Provider 的多个 anchor 在请求时已知，可一次取得；containing 必须先定位文件，再同轮读取两个已知范围；HJSON 必须先裁决正式源码 owner，再做范围内全集查询。后两类真实依赖被保留，没有为减少回合而强行并发。

该审计当时把“已有命令能够表达答案”错误外推成“默认工具输出没有能力缺口”。v1-v4 的 106 次命令和同一捕获对照已经推翻该外推：固定页会在单文件完整结果中返回 `@more`，模型随后重复猜锚点和重查。约 10 次仍是有用的表达下界，但不能独立决定职责；更新后的归因与裁决见 [round-trip-audit-p10.md](evidence/round-trip-audit-p10.md) 第 5 节。

## OBS-SQG-015 P10 第一版规则候选通过三阶段独立路由验证

- 状态: verified
- 关联: AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-006, AC-SQG-007, DES-SQG-014, UDES-SQG-012, UDES-SQG-013, OBS-SQG-014

第一版全局规则要求先确定当前结论的最小证据闭环：输入已知、彼此独立且有界的证据在同一决策内取得，只有后续输入依赖前一步、候选仍需消歧或结果可能无界时才分轮；普通文本首查不加载高级查询 skill、入口文档、help、doctor 或输出参数，所有 fd、rg 与 AST 查询仍经 `srcq`。`source-query` 同步收窄到文本路径之后的 AST、特殊协议或只读 LSP 证据，语义编辑继续由既有编辑 owner 承担；任务表和变更治理的描述也只消除本次独立评估直接暴露的非职责触发，没有新增执行入口。

三个新案例覆盖独立有界证据、依赖权威范围和普通首查边界。候选 bundle `47D9E58F…E7742` 的静态合同为 68 个案例、33 个 strict 案例，三个脱离仓库的独立 Codex 运行分别覆盖 68 个路由、68 个行为策略和 13 个引用选择，全部通过；正式部署 `Validate` 也通过。该证据只证明第一版规则结构、路由边界和发布合同成立；OBS-SQG-016 已证明它不能满足真实模型的质量与成本目标，后续规则身份必须重新刷新三阶段证据。

## OBS-SQG-016 P10 第一版真实候选未达到质量与总成本目标

- 状态: verified
- 关联: AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-007, DES-SQG-010, DES-SQG-014, UDES-SQG-007, UDES-SQG-012, UDES-SQG-013, OBS-SQG-015

candidate-only identity `34b6fd64…1360c` 在正常速度、medium、full access、approval never 下完成三个受影响 case 各两次，P9 与冻结五-skill 历史未重跑。确定性 capsule 验证覆盖 16 个原始文件和 2 个环境文件；detached 审计结果见 [iteration-audit-p10-v1.md](evidence/iteration-audit-p10-v1.md) 与 [audit-result-p10-affected-v1.json](evidence/audit-result-p10-affected-v1.json)。

六次运行总 Token `748,591`、26 次命令、耗时 `269.370 s`；相对 P9 同六次只读记录仅少 2.97% Token 和 2 次命令，短/长价格等价反而上升 19.39%/20.29%，且 required 质量 4/6、strict 质量 1/6。containing 两次在定位唯一实现后仍读取 README、测试和多轮同义锚点，达到 `446,292` Token、15 次命令；最终答案还普遍遗漏关系、行号或完整性适用范围。第一版因此不采纳。直接机制支持把规则改为“每个工具轮次对应一个真实依赖层”、按完整闭环总 Token 裁决、直接实现充分后停止次级旁证，并明确最终压缩必须保留关系、范围、完整性与可定位依据；它仍不支持新增 srcq 命令。

## OBS-SQG-017 P10 第二版降低总 Token 但未守住质量顺序

- 状态: verified
- 关联: AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-007, DES-SQG-014, OBS-SQG-016

candidate-only identity `5047af5e…cb61` 在相同三个受影响 case 上得到 `618,630` Token、23 次命令和 `248.378 s`；相对 P9 同六次记录少 19.82% Token 与 17.86% 命令，但短/长价格等价仍高 0.20%/0.13%，detached 审计只有 required 5/6、strict 2/6。Provider 已收敛，containing 仍追溯不改变请求职责结论的旁证，最终源码定位未逐项覆盖；HJSON 完整性没有稳定写出正式范围与当前快照。证据见 [iteration-audit-p10-v2.md](evidence/iteration-audit-p10-v2.md)。

## OBS-SQG-018 P10 第三版形成成本净收益但仍未达到封闭质量

- 状态: verified
- 关联: AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-004, AC-SQG-007, DES-SQG-010, DES-SQG-014, OBS-SQG-017

candidate-only identity `7e2bf242…7bef` 得到 `542,658` Token、23 次命令和 `220.346 s`；相对 P9 少 29.67% Token、短/长价格等价低 1.36%/0.80%，耗时基本持平。源码事实均可由当前实现直接支持，但 containing 的最终定位仍未稳定逐项对应三项结论，HJSON 两次都省略快照限定；一次广域实现查询还返回 benchmark corpus 路径，因此该身份在 detached 审计前已经明确不满足封闭验收，没有为已否定候选继续支付独立审计成本。证据见 [iteration-audit-p10-v3.md](evidence/iteration-audit-p10-v3.md)。

正式 v6 oracle 与源码都表明 `FUeAgentStructuredHjsonFormatter::IsBareKey` 定义位于 2655，调用位于 648、868、2037；分支 seed 的旧相反标注已同步纠正，不把 oracle 缺陷误判为候选行为。

## OBS-SQG-019 P10 第四版操作约束引发成本反弹

- 状态: verified
- 关联: AC-SQG-001, AC-SQG-002, AC-SQG-003, DES-SQG-014, UDES-SQG-013, OBS-SQG-018

candidate-only identity `980e4d0d…4104` 得到 `720,707` Token、34 次命令和 `282.026 s`。相对 v3 增加 `178,049` Token、11 次命令和 `61.680 s`；containing 两次为 6/8 次命令，HJSON 一次达到 12 次，最终定位和范围/快照双限定仍不稳定。直接预审已足以否定候选，证据见 [iteration-audit-p10-v4.md](evidence/iteration-audit-p10-v4.md)。这证明把稳定根原则展开为“同次调用、首查全部锚点、已知章节不得列目录”等操作配方会增加模型规划与复核压力；第五版因此撤回这些表层指令，只保留请求职责范围和最终证据保真。

## OBS-SQG-020 P10 全链路归因已形成工具与规则的职责拆分

- 状态: superseded
- 关联: AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-007, DES-SQG-004, DES-SQG-014, UDES-SQG-003, UDES-SQG-013, DEC-SQG-001, OBS-SQG-019

四轮使用同一项目快照，v3/v4 还使用同一 srcq 二进制；因此项目 `AGENTS.md` 是端到端真实成本但不是候选差异。直接投影对照证明固定页本身制造单文件恢复回合：Provider 的 82 行分页结果可在增加 888 个字符后完整覆盖映射，containing 的完整单文件投影与五次分页后重查的累计 stdout 同量级。第一实现让单一来源使用最多 8192 estimated Token 和 1024 字符正文；OBS-SQG-021 已证明该策略没有覆盖真实高成本命令链，不能作为默认合同保留。

## OBS-SQG-021 P10 第五版暴露高级 skill 误触发且成本反向

- 状态: verified
- 关联: AC-SQG-001, AC-SQG-002, AC-SQG-003, DES-SQG-004, DES-SQG-014, UDES-SQG-003, UDES-SQG-013, OBS-SQG-020

candidate-only identity `763f0b78…d21da` 的 6 次运行全部正常退出、usage 完整且无 postflight 漂移，总 Token `823,177`、39 次命令、`309.314 s`，明显差于 v3；确定性 capsule `aa7c118e…18a69` 验证 16 个原始文件和 2 个环境文件。五个 run 在首次普通文本查询前加载 `source-query`，HJSON 一次还预加载 rg/fd 与 LSP 引用；另一个 run 先调用 `srcq rg --help`。v5 的 8192 单文件闭环没有覆盖这些链路，因为 locator 是多文件结果，文件确定后模型改用直接读取。直接答案还缺 containing 逐项行范围和一次 HJSON 范围/快照限定，因此没有进入 detached 审计或 12-run。完整记录见 [iteration-audit-p10-v5.md](evidence/iteration-audit-p10-v5.md)。

## OBS-SQG-022 P10 第七版收敛为同预算闭环和专项 skill

- 状态: superseded
- 关联: AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-007, DES-SQG-004, DES-SQG-014, UDES-SQG-003, UDES-SQG-013, OBS-SQG-021

第七版实现只在完整结果不超过 512 个证据单元且仍落在原 2048 estimated-Token 总预算时越过初始 80 项限制；单一来源可用 1024 字符单行重新评估，但总预算不增加。多来源或更大结果保持 80/2048/240，显式控制面保持调用方精确预算。全局源码路由仍只有一条，`source-query` 收为分页/截断、明确 AST、特殊输出或文本后真实语义歧义的专项入口。组件定向回归通过；随后真实 v7 的结果见 OBS-SQG-023，并证明工具边界成立但规则仍有已知正文重搜问题。

## OBS-SQG-023 P10 第七版把剩余成本收敛到已知正文重搜

- 状态: verified
- 关联: AC-SQG-001, AC-SQG-002, AC-SQG-003, DES-SQG-014, UDES-SQG-013, OBS-SQG-022

candidate-only identity `93931b4c…9eac2` 的总 Token 为 `736,203`、27 次命令、`272.050 s`。Provider 两次稳定为 2/2 命令，HJSON 为 3/5，证明普通高级 skill 误触发基本退出；containing 却为 7/8 个命令、`390,993` Token，并在唯一文件确定后继续用宽泛 anchor 与 context 搜索正文和 fingerprint 上游。确定性 capsule `ed7c7bc4…80d67` 已验证，直接 strict 失败使本身份不进入 detached 审计。证据见 [iteration-audit-p10-v7.md](evidence/iteration-audit-p10-v7.md)。

## OBS-SQG-024 P10 后续迭代区分候选规则与项目规则成本

- 状态: verified
- 关联: AC-SQG-001, AC-SQG-002, AC-SQG-003, DES-SQG-014, UDES-SQG-013, OBS-SQG-023

第八版把全局源码规则压成“srcq 搜索、已知正文直读、文本不足升级、证据保真”，得到 `556,677` Token、22 次命令和 `258.587 s`，但一次广域查询读取 benchmark seed，且最终范围、快照和实现范围仍不稳定，不能采纳。后续身份分别收紧权威范围、普通续页和仅审查规则时的高级 skill 非触发；v19 完整 12-run 又升至 `1,340,388` Token、51 次命令。逐命令证据表明 AgentBase 的只读 case 多次因项目“修改前读取 README”条款加载根 README，这不是 srcq 输出或全局查询路由能纠正的职责。

项目规则因此只补充一个根本范围：纯只读源码定位只读取回答所缺的正式来源，不因修改前置条款加载 README。相同六个受影响 run 在 v20 为 `528,450` Token、20 次命令，较 v19 对应六次的 `778,895` Token 明显下降，且没有根 README 读取；这证明修正位于项目规则适用边界，而不是用 benchmark 特例或查询命令配方吸收。

## OBS-SQG-025 P10 最终候选保持质量并降低总 Token

- 状态: verified
- 关联: REQ-SQG-001, AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-004, AC-SQG-006, AC-SQG-007, AC-SQG-008, DES-SQG-004, DES-SQG-008, DES-SQG-010, DES-SQG-014, UDES-SQG-003, UDES-SQG-007, UDES-SQG-012, UDES-SQG-013, OBS-SQG-024

最终 v21 identity `0cfb891986cb89c96077427564f91720ed52619f82828e05fa84d420174859d5` 完成六类任务各两次：12/12 required、12/12 可见行限和 12/12 evidence complete 通过，45 次命令全部成功，usage 完整且 postflight 无漂移。总 Token `1,066,470`，其中普通输入 `187,534`、缓存输入 `870,144`、输出 `8,792`、推理输出 `3,925`、可见输出 `4,867`；耗时 `480.739 s`，短/长价格等价 `327,300.4` / `628,224.8`。

相对 P9 同为 12/12 的最终候选，Token 少 `84,058`（`-7.31%`），命令少 3 次（`-6.25%`），但耗时增加 `117.576 s`（`+32.38%`）。质量不退化且第二优先级 Token 明显下降，因此采纳；速度没有改善，不外推为全面性能提升。detached auditor 只读取指定 capsule，复算 experiment identity、canonical capsule hash、usage、环境差异和逐案质量后通过；结果见 [iteration-audit-p10-v21.md](evidence/iteration-audit-p10-v21.md)、[audit-result-p10-v21.json](evidence/audit-result-p10-v21.json) 与 [capsule-verification-p10-v21.json](evidence/capsule-verification-p10-v21.json)。最终规则身份又由三个不同 evaluator 完成 69/69 首次路由、69/69 行为策略和 13/13 引用选择，当前 bundle 为 `E721424A…A63DEB`。

## OBS-SQG-026 P11 已接入 scc 指标与主机基准工具

- 状态: verified within deterministic scope
- 关联: REQ-SQG-001, DES-SQG-001, DES-SQG-003, DES-SQG-004, DES-SQG-008, DES-SQG-011

`srcq 0.4.0` 已增加 scc 直接入口、query 控制面、doctor、summary/languages/files/hotspots/lossless/raw、machine、artifact、分页快照和同次捕获协议回退；files 进一步在同一证据页上比较扁平标注、单表头扁平表和可逆保序目录树，当前真实快照选择目录树，hotspots 继续保持扁平排名。指标 parser 与排序保留在 backend 模块，公共网关唯一维护可逆路径树及既有执行、预算和恢复职责。Windows bootstrap 以 `BenBoyter.scc` 与 `sharkdp.hyperfine` 安装并读回两个外部工具；全局规则让普通 scc/hyperfine 无需加载专项 skill，高级 scc 才读取新增引用。hyperfine 不进入 srcq 或发布 payload。

workspace、真实 scc、36 模式/9 oracle、AST 基线、bootstrap、插件、真实 tokenizer、release 和 0.3.1→0.4.0 安装生命周期均通过。1165 文件同快照的完整 files 投影由旧候选 43836 降至 25997 个 o200k Token（-40.6949%），规范化 machine 和分页身份不变。源码快照为 `sha256:008117d737fc377a1cee78bfa76f2faae58200e298edf61db32c1967ac3667a3`；两次 clean build 均得到 2730989-byte 归档和 SHA-256 `b43ad3f1c0fa4404f0f961ffba791cc3dfdfc07dd5641291bd51ded4bee0ba6f`，manifest 明确声明非捆绑 `scc.exe`/3.7.0。

原 P11 实施轮按用户约束未启动独立 Codex；后继增量评估现已形成当前 96/96/26 evidence。本次目录树优化没有改变全局规则、skill 或触发输入，因此不重复运行 evaluator，真实 tokenizer 也不外推为端到端模型行为。只读部署 Status 确认实际用户 srcq 仍为 0.3.1，候选尚未 Publish；这些是已明确暂停或需要逐次授权的外部状态转换，不是未闭合源码实现。

## OBS-SQG-027 P12 已把正常 scc 续页失败定位到页尾动作缺失

- 状态: confirmed
- 关联: AC-SQG-009, DES-SQG-015, UDES-SQG-015

修复后的 evaluator v5 在真实 scc preflight、full access、WebSocket、代理端 DNS 与 ALL_PROXY fanout 均有效且零 retry/fallback 的边界下，第一页成功返回 `@more shown=80 omitted=97 after=<cursor>`；独立 Codex 随后执行 `srcq scc --after <cursor>`，原生 scc 拒绝未知参数，第二页未取得。query owner 已掌握完整续页命令却只投影 cursor 片段，这是可重复的模型交互缺口，不是网络、权限、backend 或 snapshot 能力缺失。

## OBS-SQG-028 P13 v6 已完成可执行续页的真实模型闭环

- 状态: verified
- 关联: AC-SQG-009, DES-SQG-015, UDES-SQG-015

同一 evaluator 边界下的 v6 preflight 读回 `srcq 0.4.1` 与真实 scc `ok`；subject 第一条直接查询返回 `@more shown=80 omitted=97` 和完整 `@next`，第二条命令逐字采用提示中的 `srcq query scc exec --after ... -- <原 argv>`，exit 0 并取得第二页首项 `D:/program/AgentBase/tools/srcq/crates/srcq-core/src/profile/paths.rs`。preflight/subject 均无 WebSocket 失败、sampling retry 或 HTTP fallback，postflight 无身份漂移；experiment identity 为 `27ac16beea6ef195bd443057fc229b17af603d4d5c2aa7f54fcc31ca74ad20f5`，capsule `fce108b55bce2871e2bb153e95725cebb5dd04d2530806aa28c07d31a6257926` 验真通过。

## OBS-SQG-029 P16 快速源码关系已发布为 0.5.0

- 状态: verified within declared candidate scope
- 关联: REQ-SQG-002, AC-SQG-010, AC-SQG-011, AC-SQG-012, AC-SQG-013, AC-SQG-014, AC-SQG-015, DES-SQG-016, DES-SQG-017, DES-SQG-018, DES-SQG-019, DES-SQG-020

`srcq symbol` 已实现 definition、references、incoming/outgoing calls 与 capabilities，内部由 rg 有界候选和 ast-grep 结构适配组成。名称与位置身份、定义/声明、词法角色、虚分派 unknown、循环/节点/深度预算和 model/machine 分面均有直接测试；26 种 ast-grep 语言全部登记，C++ 与九种通用 relation adapter、四种 definition-only outline adapter 按实际 0.44.1 能力声明，其他语言保持 unadapted 或 not-applicable。Go、Python、Rust、JavaScript、TypeScript、TSX、Java、C 与 C# 共用由语言节点表驱动的 generic relation engine；C 与 C# 只新增 grammar 描述、fixture 和边界测试，没有复制关系算法。C++ SourceUniverse 能读取 workspace、compile database 和嵌套 MSVC response file，恢复 GptProjectTest 外的 UE 定义；默认 Source/src/include 投影避免生产源码被计划证据副本污染，树内递归也不再为 `NewObject` 扫描整个 UE/SDK。

完整 workspace 门禁通过；后继 add/only/exclude 测试又发现并闭合“无元数据临时 cwd 把祖先普通 `.vscode` 当作项目根”的范围反例，当前 70 项 srcq-cli lib、12 项关系集成、Clippy 与格式检查通过。C/C# 新增的 references、incoming/outgoing、深度展开和 capability 测试证明公共算法已接入；C 原型、宏，C# overload、partial、extension method、alias 与 file-scoped namespace 等未建模语义继续保持 candidate/unknown 边界。活动 AST、透传、协议、压力与发布验证已统一到 ast-grep 0.44.1；P0 保存的 0.41.1/0.42.0 快照只属于历史证据，不再构成当前支持或发布矩阵。真实 UAI release 路径的五项均值为 0.235–5.076 s，model 输出为 53–161 个 o200k Token；这些只证明当前本机实际命令，不冒充完整模型会话收益。本轮未改变全局规则、skill 或路由合同，因此未重跑模型路由评测。`srcq-v0.5.0` 已于 2026-08-31 发布，标签指向 `ae465953a838b168fe9485ca9e9e6546ad14ba74`，Windows 归档 SHA-256 为 `20a11d2685b286a5c4343c805d40791eb0d54a052ca71c45eb3b9f40fa306fe2`；8 个资产、真实认证下载、隔离安装/Status/卸载均已读回。用户默认安装与 Codex Publish 未执行。

## OBS-SQG-030 C# 无 LSP 关系与静态项目范围已形成 0.6.0 来源

- 状态: verified in 0.6.0 release source
- 关联: REQ-SQG-002, AC-SQG-010, AC-SQG-012, AC-SQG-014, DES-SQG-016, DES-SQG-019, DES-SQG-020, TSQG-109, TSQG-112

0.6.0 来源在既有 relation owner 内增加 C# 专用调用分类：当前词法块或 Lambda/local function 内有效的显式参数/局部、`var = new`、字段/属性、跨 partial 文件的唯一成员、短属性链和源码静态类型可形成 `typed-member-candidate`；相邻块的同名局部分别解析，已离开作用域或 `dynamic` 等未证接收者继续保留，incoming 会排除已证明属于其他接收者类型的同名调用。incoming 复用已知根定义、批量 AST 扫描候选文件并只为命中调用解析接收者，不重复执行定义/范围恢复或解析调用者内全部调用。VMTSingleMachine 的两个 `GetStatusAsync` 已按接收者类型分别收敛为 4 个 client caller 与 3 个 engine caller，`VmtController.MeasureOnceAsync` 的 10 个 `_services.Vmt` caller 全部取得 `VmtController` 类型证据，三项均在默认预算内返回 `candidate_scan=complete`。

同一来源还只读解析 `.sln` 与 Microsoft.NET.Sdk 系列 `.csproj` 的默认 Compile 集、Include/Remove、链接源码和 ProjectReference；SDK 默认隐藏目录及项目根 `bin/obj` 排除已按本机 .NET SDK 9.0.310/10.0.201 正式 targets 校准，MSBuild `*` 不跨目录。VMTSingleMachine 读回 141 个 Compile 文件且 `scope=resolved`。fixture 正例证明移除文件与不属于解决方案的仓库 `.cs` 不再进入定义全集，已解析的空 Compile 集也不会退回仓库扫描；无项目、不可识别 solution、自定义 SDK、条件 item、多 `.sln`/`.csproj`、任一祖先 Directory.Build、显式 import、影响默认输出排除的属性及项目外 wildcard Remove 反例证明无法静态展开时返回 `scope=incomplete`。项目图限制为 4096 个项目与 100000 个 Compile 文件，同项目 wildcard 复用一次候选枚举。实现不调用 LSP、Roslyn、MSBuild 或 dotnet build；重载、扩展方法、继承/接口分派、动态调用、复杂表达式链及 block-scoped/multiple namespace 的完整限定名仍不宣称精确。该能力已随 `srcq-v0.6.0` 发布；用户默认安装与 Codex Publish 未执行。

## OBS-SQG-031 P17 多语言 typed relation 已发布为 0.6.0

- 状态: verified and released within declared candidate scope
- 关联: REQ-SQG-002, AC-SQG-010, AC-SQG-011, AC-SQG-012, AC-SQG-013, AC-SQG-014, AC-SQG-016, DES-SQG-021, SOL-SQG-017, TSQG-113, TSQG-114, TSQG-115, TSQG-116, TSQG-117, TSQG-118

`srcq-v0.6.0` 指向 `9bee175a1005485f6591fffa9ea3bdf0862d0c84`；232 文件的来源快照为 `sha256:9cb34f2343403788270200a1cb00fae8c550a5caad2a441cadb662a5b1861e11`。两次 clean Windows MSVC 构建的全部 5 个候选资产逐项一致，归档 SHA-256 为 `552ff93b24f7bb01d71bfa895f3aa4c766f9024b75a4986d878934bb0d1ee38f`。GitHub Release 共 8 个资产且 digest 与本地一致；真实私有 Release 认证下载、隔离安装、完整性 Status、version、doctor、scc doctor 和卸载均通过。

workspace test/build/lint/fmt、15 个 ast-grep 0.44.1 真实 ignored 测试、Windows 目标 66 个第三方包许可证审计，以及 2026-08-31 更新的 1233 条 RustSec advisory 数据库对 138 个 Cargo 依赖的审计均通过。PowerShell 5.1 的 0.5.0→0.6.0 安装、幂等、完整性拒绝、失败升级回滚、PATH、新进程、升级和卸载生命周期通过；发布归档的 AST、rg、fd、scc、typed symbol、process 与 cache 原生 smoke 也通过。用户默认安装仍为 ready 0.5.0，本次没有执行 AgentBase Codex Publish 或九项模型评测。

## OBS-SQG-032 代码读取 skill 候选未满足逐实验质量与价格门槛

- 状态: verified within declared experiment identities
- 关联: OBS-SQG-012, OBS-SQG-025, OBS-SQG-029, OBS-SQG-030, OBS-SQG-031

[代码读取策略审计](evidence/audit-result-code-reading-strategy-v1.json) 以“每个 case 的完整质量合同成立且价格等价成本严格下降”为晋级条件，速度允许变慢。既有 C++/TypeScript 配对结果在两项 case 上均质量未闭合且短、长价格同时上涨；唯一 C# 配对 A/B 的两个 case 价格也都上涨，后续 C# candidate-only 身份不能与其他 control 拼接为因果结果。最后只对通用的“精确文本定位→有界正文→未决项停止”候选运行一次 TypeScript 配对探针：candidate 遗漏 `getSessions`、`sessionSelected=null` 清理和非传输/运行时证明边界，短上下文价格上涨 2.229%，只有长上下文价格下降 3.722%，因此按停止条件未扩到 C++ 或 C#。

仓库 `source-query` skill 策略已恢复到 Git 历史 `aafefc62187dae845944649a68750f16fe67073e` 的 `SKILL.md` 与 `symbol-relations.md`，并退役只服务未证单文件快路的 `qualified-single-file-incoming-fast-path` 触发合同。该回退不改变 `tools/srcq` 的 0.5.0/0.6.0 实现、Release 或安装状态；原始实验、capsule 与身份继续作为开发证据，未执行 AgentBase Publish。未来候选只有在同身份配对 A/B 中逐 case 通过完整质量并使适用的短、长价格场景均严格下降，才重开矩阵扩量。

[Token 机制与优化线索审计](evidence/code-reading-token-clues-v1.md)进一步复算最终 TypeScript 与早先 C++/TypeScript 的真实命令链。最终探针中 candidate 的一次性工具正文从 18,225 降至 8,450 Token，但 command 从 2 增至 6、聚合 input 增加 74,475、实际总 Token 增加 102.766%；两个 skill 正文合计约 2,083 Token，只占总增量 2.735%。这证明当前主要线索是减少需要模型重新采样的交互轮次，并让高级查询真正替代后续文本链；它不证明每次调用有固定成本，也不证明 rg 永远优于 symbol/AST。逐请求 usage 尚不可得，固定上下文复现仍只作结构性归因。

## OBS-SQG-033 交互轮次线索已形成新反例但仍无可采纳候选

- 状态: verified within three declared experiment identities
- 关联: OBS-SQG-032

[三候选结构化审计](evidence/audit-result-interaction-rounds-v1.json)在同一 TypeScript case、Luna medium/default、两侧 `srcq 0.6.0`、只读且禁用 subject 子代理的边界下，只让 candidate `AGENTS.md` 增加一条通用策略。单阶段批取没有减少 command，价格上涨；两阶段索引/批取因默认 80 个证据单元分页扩成 11 条 command，虽一次性工具正文少 15.902%，实际总 Token 仍上涨 181.752%；显式大页候选把工具正文减少 39.727%、短/长价格减少 25.182%/26.763%，但 command 仍与 control 同为 3，且有一次 argv 错形恢复。三个 candidate 均遗漏适用 required 字段，未扩到 C++ 或 C#。

同一第二阶段 argv 的无模型探针确认：`--model-token-budget 12000` 单独使用仍受默认 80 单元上限分页；再加 `--limit 1000` 可完整返回且无 `@more/@cut`。因此当前不是 srcq 缺少单次大页能力，而是默认投影、命令选择、失败恢复和答案完整性的组合问题。现有证据支持“交互轮次会强烈放大成本”，也证明 raw command 数不是充分指标；当前保持正式源码读取策略，不修改 `global/AGENTS.md` 或 `source-query` skill，不执行 AgentBase Publish。

## OBS-SQG-034 完整 Control 三项重复测试已完成

- 状态: verified within experiments `5163fe826bcce23a0e6c98ae5f71f4188ae1b9e4e9eb78a61c3e005af6f6c579` and `ca61d02261ada08b9e7d1e0dee574c5a072432b2c88c8961cd7561e20ca88182`
- 关联: OBS-SQG-032, OBS-SQG-033

用户把 Control 明确定义为“当前 Codex 正在使用的完整 `AGENTS.md` 链与完整 skill 环境”，测试项才是叠加在该 Control 上的唯一变化。旧 runner 默认只复制查询因果 skill 且关闭插件，因此既往相关实验只保留参考价值。当前 `current-control` 模式会精确复制安装态 `AGENTS.md`、全部 24 个用户/系统 skill 目录，冻结当前 10 个已安装启用插件与 remote-plugin cache，以当前 Codex CLI 安装并读回插件，再从最终 Control 克隆 Candidate；共享 marketplace 与实际插件安装缓存都并入环境树。两侧各 29,354 个环境文件的 tree SHA-256 同为 `7d36e7cb…d33c5`，environment diff 为空。

固定的 C#、C++ 与 TypeScript 三道题均使用 Codex `0.151.0-alpha.7.2`、Luna medium/default、srcq 0.7.0、只读且禁用 subject 子代理，各运行两次。C# 为 `7/8`、`7/8`，共同遗漏 `ValidateUidsUnsafe` 只遍历启用传感器并按 `SlotIndex` 排序；C++ 为 `7/7`、`6/7`，第二次未给出 `BvhTree::rayCastInteral` 定义行；TypeScript 为 `6/6`、`6/6`。六次合计 `39/42`，只有 3 次单次答案完整通过。

六次正式运行总耗时 `342.504 s`、实际总 Token `856,159`，Luna standard 的短/长价格边界为 `$0.06058192—$0.11398244`；两个共享 preflight 另耗时 `47.147 s`、`102,798` Token、`$0.00866016—$0.01705032`。C# 与 TypeScript 都在两次间切换了 `srcq`/裸 `rg` 路线，C++ 第二次还出现一次错误 argv 后恢复；完整 Control 的质量和执行路径均不稳定。

前置诊断发现 v14 oracle 漏记 `TemperatureCollectorSensorReader.Test:58 -> Read`，且旧环境树漏算 `plugins/cache`；历史 v14 不原位修改，v15 与当前 runner 已向前修正。此前把 C# 首项失败当成停止整个 Control 的依据属于错误裁决，C# v2 证据现在只作中间结果；完整审计见 [audit-result-current-control-code-reading-v3.json](evidence/audit-result-current-control-code-reading-v3.json)。后续 Candidate 必须在相同三题各两次的合同下比较，不能复用缩减 Control 或只跑 C#。

## OBS-SQG-035 四类独立读取策略实验均未达到采纳门槛

- 状态: verified within seven declared candidate identities
- 关联: OBS-SQG-032, OBS-SQG-033, OBS-SQG-034

四类测试项分别克隆完整 Control，只改一个候选面，并继续使用固定 C#/C++/TypeScript 三题各两次。`source-query` 正文的两版 symbol 规则均产生 0 次 `srcq symbol`，证明正文处于既有触发描述之外；把适用条件写入 frontmatter 后，symbol 只在两次 C# 中出现 7 次且全部因坐标或 `semantic-unknown` 失败，C++/TypeScript 仍为 0 次。可达版本 required 为 `37/42`，总 Token、短/长价格和耗时相对 Control 分别 `+52.647%`、`+26.425%/+25.395%`、`+28.424%`，因此不采纳。完整机制与三版身份见 [symbol skill 审计](evidence/audit-result-symbol-skill-v1.json)。

“工具已明确时立即调用”候选在六次运行中仍全部先输出可见说明，平均首条长度只从 `61.167` 变为 `60.5` 字符；required 为 `36/42`，总 Token `+76.289%`，两种价格 `+26.990%/+27.430%`，没有观察到目标收益。[工具前推理审计](evidence/audit-result-pretool-reasoning-prompt-v1.json)只对事件顺序与 usage 下结论，不冒充能读取隐藏推理文本。

“内部推理使用精炼书面短句”候选的 reasoning output `-14.425%`、耗时 `-6.091%`，但 required 降至 `37/42`，总 Token `+11.854%`，两种价格 `+1.941%/+2.354%`；低 reasoning Token 不足以证明内部措辞已经符合要求，也不能覆盖质量与价格反例。完整边界见 [精炼推理审计](evidence/audit-result-concise-reasoning-prompt-v1.json)。

只改 `srcq 0.7.0` 默认单页模型预算时，`1024` 产生 8 次 `srcq more`、26 个分页标记，required `38/42`、总 Token `+63.123%`、价格约 `+33%`；`4096` 消除实际续页并让价格与耗时分别约 `-2.3%`、`-8.3%`，但 required 仍为 `38/42` 且总 Token `+9.424%`。按质量、Token、速度顺序保持正式 `2048` 默认值；两份候选二进制只存在于实验 home，没有修改仓库或安装态。完整数据见 [单页长度审计](evidence/audit-result-page-length-v1.json)。

这四类实验没有修改正式 `global/AGENTS.md`、`skills/source-query`、仓库或已安装 `srcq`，也没有执行 Deploy、Release、完整验证或九项评测。后续只有新的工具能力或可观察机制能同时消除失败调用、保持逐项质量并降低总 Token 与两种价格时才重开；不再通过更强规则或更小页长重采样同一输入。

## OBS-SQG-036 普通搜索 argv 修复后的两类提示已独立重跑

- 状态: verified within experiments `7f8e5132…25da`, `4b012f43…c7c1`, `36c1dca9…1381`
- 关联: OBS-SQG-034, OBS-SQG-035

此前 318 个命令执行项中的重复 `srcq rg rg`、把 Windows glob 当原生路径和 fd 多 pattern 误用，来自常驻规则把后端 argv 写成容易再次补入命令名的占位形式。`global/AGENTS.md` 已改成明确的 selector、pattern、options 与 paths 边界，并同步普通 rg/fd 的路由反例；`source-query` 仍不为普通 rg/fd 触发。修复后基础环境的 47 次命令没有重复 selector 或 literal-glob 失败，但有一次猜错 vcxproj 相对路径；六题严格质量为 `36/42`，Token `961,379`，短/长价格 `$0.0563248/$0.1050554`。

在该基础环境上，“工具明确后立即调用”得到 `37/42`，但完整答案从 `4/6` 降至 `3/6`，六次仍全部先发可见说明，平均首条从 63 增至 68.333 字符；Token、短/长价格、耗时分别 `+9.853%`、`+14.944%/+14.932%`、`+11.434%`，不采纳。“精炼书面推理”得到 `36/42` 且完整答案降至 `3/6`，Token、价格、耗时分别 `-12.999%`、`-2.836%/-2.850%`、`-2.977%`，但 reasoning output `+1.666%`，并再次出现一次规则已禁止的 Windows literal-glob 路径，因此也不采纳。原始数据与评分见 [搜索 argv](evidence/audit-result-search-command-grammar-v1.json)、[工具前推理 v2](evidence/audit-result-pretool-reasoning-prompt-v2.json)和[精炼推理 v2](evidence/audit-result-concise-reasoning-prompt-v2.json)。仓库规则尚未部署或发布。

## OBS-SQG-037 修复后 Control 已用逐请求 usage 重算

- 状态: verified within experiment `0aa3c7b…3660`
- 关联: OBS-SQG-034, OBS-SQG-036

修复搜索 argv 后的基础 Control 使用 App Server v2 重新运行固定 C#、C++、TypeScript 三题各两次。C# 为 `7/8`、`6/8`，C++ 为 `6/7`、`7/7`，TypeScript 为 `6/6`、`6/6`；六次合计 `38/42`，3/6 次单次完整。正式运行共 `1,144,729` Token、`389.363 s`、45 次请求和 43 个 command，其中只有 C++ 首次猜错根目录 vcxproj 路径后恢复；没有 `srcq rg rg` 或 `srcq fd fd`。

逐请求 usage 完整，45 次请求均在短上下文档位；按 experiment identity 冻结的 Luna standard 单价，观察用量对应 `$0.06089496`。相对上一份修复后 Control 样本，required `+2`，但完整答案 `-1`、Token `+19.072%`、价格 `+8.114%`、耗时 `+15.952%`，再次证明 Control 输出存在重复波动，不能把重算结果解释为策略改善。

本轮还否定了 runner 的旧 `ideal_cache_report/v1`：六次均报告 cache write 为 0，但后续 cache hit 超过此前事件可证明的 retained prefix，旧算法却把增长误记为合成写入，并得到高于观察价格的 `$0.09893144`。当前 runner 保留可直接计算的逐请求观察价格；只有 cache-write 账目闭合时才给更窄的“不再驱逐已观察前缀”反事实，否则返回 `unavailable`。跨 subject 的全局理想缓存仍缺 prefix identity、breakpoint 和完整写入来源，不能由当前计数推定。完整证据见 [逐请求 Control 审计](evidence/audit-result-repaired-control-appserver-v1.json)。未运行 Candidate、完整验证、九项评测、Deploy 或 Release。

## OBS-SQG-038 控制思考量提示没有降低实际总价

- 状态: verified within candidate-only experiment `a33a9945…0720`
- 关联: OBS-SQG-035, OBS-SQG-036, OBS-SQG-037

独立 Candidate 只增加一条“内部推理应合理控制思考量并与当前决策难度匹配”的规则，不混入精炼书面句式要求。固定三题各两次得到 C# `6/8、7/8`、C++ `6/7、7/7`、TypeScript `6/6、6/6`，合计仍为 `38/42`、完整 `3/6`；单次缺项与 Control 发生交换，没有形成稳定质量改善。

Candidate reasoning output `5,339→5,234`（`-1.967%`）、请求 `45→35`、实际总 Token `-23.907%`、耗时 `-8.859%`，但逐请求观察价格 `$0.06089496→$0.06219432`（`+2.134%`）。价格反向来自普通输入增加 42,464 Token：减少的 315,392 个廉价 cached input 和 738 个 output Token 不足以抵消。六次只有 C++ 第一次和 TypeScript 第一次降价，其余四次上涨。

Candidate 还出现 10 次裸 `rg`、一次 Windows literal glob 失败和两次猜错 vcxproj 路径；Control 对照样本为 2 次裸 `rg` 和一次路径失败。该提示只在隔离 benchmark home 中存在，不进入仓库或安装态。对照复用紧邻的修复后 Control：Control tree、corpus、Codex 与 runtime projection 相同，但 runner 因逐请求价格/缓存后处理修正而具有不同源码 identity，因此这是 candidate-only 相邻样本比较，不冒充同 experiment 的精确配对因果 A/B。完整证据见 [思考量提示审计](evidence/audit-result-thought-budget-prompt-v1.json)。

## OBS-SQG-039 三项 Control 题面与评分合同已按 v17 校准

- 状态: verified without model rerun
- 关联: OBS-SQG-034, OBS-SQG-037, OBS-SQG-038

用户确认搜索 argv 修复后的环境进入当前 Control 基线。逐项复核发现，v16 除 Enabled/SlotIndex 外仍有三类合同缺陷：C# 把题面未要求的 `ValidateUid` ExpectedUid 内部分支升级为 required，C++ 要求题面未要求的 `root` 与全部参数展开，TypeScript 则漏掉题面要求的宿主清理状态和多个不同消息边界；三个 case 还把可独立漏答的事实合并为单项，导致失败原因不稳定。

`v17.json` 不改写已绑定历史语料，向前把三个外部项目拆为 C# 31、C++ 13、TypeScript 23 个 required。C# 的 ExpectedUid 行为与 C++ 的 root/完整参数转发降为 supporting；`Test -> Read` 成为显式 required；TypeScript 题面改问“是否以及如何清理”，并补入宿主未保存 Disposable、没有显式清理及完整消息边界。三个项目源码快照校验通过。现有 v16 Control 答案只作追溯投影：C# `29/31、30/31`，C++ `13/13、13/13`，TypeScript `23/23、23/23`，合计 `131/134`、完整 `4/6`。两个真实失败分别是 C# 第一次漏 `Test -> Read` 及整体调用完整性、第二次把未知型号行号 `125` 写成 `124`。Token、价格和耗时未变；该投影不是 v17 模型运行。结构化证据见 [v17 合同校准与追溯重评分](evidence/audit-result-repaired-control-rescore-v17.json)。

## OBS-SQG-040 共享双向调用与显式清单范围已完成隔离验证

- 状态: verified in isolated prototype
- 关联: AC-SQG-011, DES-SQG-016, DES-SQG-018, DES-SQG-019, DES-SQG-021

外部隔离 worktree 已证明单次 `calls --direction both` 可以复用同一查询、`SourceUniverse` 与 deadline，并用一个共享 root 加两个独立方向分支保持节点、边、截断和时间限制状态；既有 `srcq.symbol.calls/v1` 可从各分支机械还原。优化投影相对两次独立调用在 C++、C#、TypeScript 的 machine/model 面均下降，同时保持关系等价；TypeScript outgoing 的截断状态也未丢失。

同一隔离实现增加通用 `--source-manifest PATH` 入口及首个 `vcxproj-direct-items/v1` adapter，只把直接 `ItemGroup` 源码项解释为 `bounded` 范围，不冒充完整 MSBuild。FaceCutting3D 的 93 个直接项配合限定名查询时，双向关系与两次独立调用等价，machine Token 从 `1018` 降至 `854`、model Token 从 `271` 降至 `260`，耗时从 `4.970 s` 降至 `4.401 s`。

三轮只读模型实验均保持 C++ 质量 `26/26`，但 body-only A/B 的候选价格从 `$0.02516840` 升至 `$0.02551624`；加强触发后出现 8 次错误命令；限定名候选虽实现 `2/2` bundle 成功，仍相对邻近 Control 增加 `47.2%` Token、`22.5%` 价格、`29.4%` 时间和 `50%` 请求。工具架构因此只在隔离层成立，skill 候选全部拒绝，仓库 srcq、已安装环境与部署 payload 均未改变。完整证据见 [共享双向调用审计](evidence/audit-result-shared-calls-bundle-v1.json)。

## OBS-SQG-041 正式仓库候选闭合工具合同但模型 skill 再次被价格反例拒绝

- 状态: verified in repository candidate and isolated model experiments
- 关联: AC-SQG-011, DES-SQG-022, SOL-SQG-018, TSQG-119, TSQG-120

仓库 `srcq-cli` 候选现已增加 `--source-manifest PATH` 与 `--direction both`。单方向 incoming/outgoing 的冻结 v1 JSON 在改动前后字节相同；bundle/v1 可在 C++、C#、TypeScript 机械还原 root、nodes、truncation、timeout、scan 与 evidence。FaceCutting3D 的 93 个直接项为 `bounded`，machine Token `821→651`、model Token `217→187`；3000 ms 时两支完整，1500 ms 时退出 124 并分别保留 partial 状态。格式、check、全 target clippy、25 项符号集成测试和 16 项 scope 单元测试通过。

模型侧先证明只改引用不会被读取：Candidate 为 `12/13、13/13`，Control 为 `13/13、13/13`，且 Candidate 两次价格都更高。强化 description 的单次 preflight 曾以 4 个命令达到 `13/13`，但正式配对中四条答案虽均为 `13/13`，Candidate 价格为 `$0.01385928/$0.01572924`，Control 为 `$0.01075160/$0.01066468`；Candidate ordinary input 为 `37,014/39,869`，Control 为 `24,360/24,063`，并且两次都猜错 manifest 路径、在行为大页后补查。该结果拒绝正式 skill 晋级，不部署、不安装、不发行；完整数据见 [共享 bundle 审计](evidence/audit-result-shared-calls-bundle-v1.json)。

## OBS-SQG-042 v18 已加入工具中立的完整实现范围，位置批量 symbol 未通过资格门槛

- 状态: corpus verified; symbol candidate rejected in qualification
- 关联: OBS-SQG-039, OBS-SQG-041

`v18.json` 把 C++、C#、TypeScript 三个既有代表题中已要求定位的可调用实体升级为相对文件与 1-based inclusive 完整实现范围，题面不提 `rg`、`symbol`、skill 或其他工具。标准答案先由冻结源码独立审计并写入 oracle；三个工作区快照的语料校验通过。

外部隔离的重复位置批量 definition 原型可覆盖 C++ `3/3`、C# `6/6`、TypeScript `2/3`，但 effect 内局部箭头函数仍不能解析。首个有效 C++ 资格样本中，Control 与 Candidate 均为 `13/13`，Candidate 的价格、Token、请求、耗时和工具项却分别增加 `39.565%`、`64.933%`、`50%`、`23.470%`、`57.143%`；缩减路线仍有不支持参数、help 恢复、重复读取，并因网络退化不具晋级效力。按全指标先资格后扩量的合同，三题各两次没有执行；仓库 srcq、正式 skill、规则、部署与发行均未改变。完整证据见 [v18 完整实现范围审计](evidence/audit-result-v18-definition-range-v1.json)。

## OBS-SQG-043 同请求批量工具提示已触发并取得单次收益，稳定性仍未成立

- 状态: mechanism verified; benefit observed once; stability blocked by transport degradation
- 关联: OBS-SQG-032, OBS-SQG-033, OBS-SQG-042

隔离 Candidate 只增加通用同请求工具批量提示，不修改题面、skill、工具或正式环境。三个 C++ 尝试中 Candidate 都产生了真实的同请求多 tool item，最大批量分别为 4、3、3；复合 PowerShell 命令始终只计一个 item，因此没有把 shell 拼接误报为批量。事件只能证明同次模型请求输出多个工具项，不能证明 harness 并发执行。

唯一有效配对保持 `13/13→13/13`，请求 `6→5`、价格下降 `17.491%`、总 Token 下降 `12.903%`、耗时下降 `3.895%`，尽管工具项增加 `40%`。两个恢复配对分别因 Control、Candidate 网络传输退化而失效；答案均为 `13/13` 且机制仍触发，但不能用于收益稳定性判断。达到有界恢复次数后未扩量到 C#、TypeScript，Candidate 未晋级，正式规则、skill、工具、部署与发行均未改变。完整证据见 [同请求工具批量审计](evidence/audit-result-v18-tool-call-batching-v1.json)。

## GAP-SQG-010 P16 仍缺部分语言依赖 resolver 与关系同快照续页

- 状态: open
- 关联: AC-SQG-002, AC-SQG-007, AC-SQG-009, AC-SQG-012, AC-SQG-014, AC-SQG-015, OBS-SQG-029, OBS-SQG-030

0.6.0 已为 C# 恢复解决方案内 SDK 项目的默认 Compile 集、Include/Remove、链接文件和 ProjectReference，并在静态不能判定条件、显式 import 或属性时降级为 `incomplete`；它仍不解析 NuGet 源码或执行完整 MSBuild。TypeScript/TSX/JavaScript、Rust、Go、Python 也已分别从 tsconfig/jsconfig/package 本地引用、Cargo workspace/path、go.work/go.mod 本地路径和 pyproject 静态 source/path 恢复项目外源码根，损坏、缺失或不支持的配置显式产生 issue；Java 等其余非 C++ adapter 仍只有项目递归或显式根。关系大结果仍只报告省略量并允许提高 limit/预算重跑，尚未复用 query spool 的短句柄、snapshot 和无重扫恢复。当前输出不会把这些缺口伪装为完整或精确，但 TSQG-110/112 因而仍不能整体完成。后续范围验证应选真实外部依赖消费者，不机械展开全部语言×依赖管理器矩阵。

## GAP-SQG-011 常用语言缺类型、限定名与 callable owner 适配

- 状态: resolved
- 关联: REQ-SQG-002, AC-SQG-010, AC-SQG-011, AC-SQG-012, AC-SQG-013, AC-SQG-016, DES-SQG-016, DES-SQG-017, DES-SQG-018, DES-SQG-021, OBS-SQG-029, UDES-SQG-020

0.6.0 已在既有查询、缓存、图遍历和输出 owner 内增加共享 typed relation 中间层，并由 Go、Python、Rust、JavaScript、TypeScript/TSX 适配器声明自身调用、绑定、词法范围、当前类型与 callable AST。五种语言可以从显式类型、构造或复合字面量、当前接收者、字段和静态限定生成 `typed-member-candidate`；Go 方法 receiver 会进入限定定义身份，适用的 function/method、arrow/function expression、lambda 和 closure 不再借外层参数类型。incoming 保留观察到的调用形式，并排除已证明属于其他接收者类型的同名调用。

语言项目 resolver 已接入 `SourceUniverse` 唯一入口，只读解析本地静态元数据，不读取 dependency cache、不下载或启动语言工具。当前没有证据支持重载、trait/interface 或动态分派、函数值、复杂泛型/union、宏/生成代码和运行时属性的精确绑定；这些机制不属于本差距的候选精度承诺，仍由 `semantic-unknown` 与按需 LSP/领域工具承担。该能力已随 0.6.0 发布；用户默认安装仍为 0.5.0，AgentBase Codex Publish 未执行。

## GAP-SQG-012 双向 bundle 与显式 source manifest 已进入正式仓库候选

- 状态: resolved
- 关联: AC-SQG-011, DES-SQG-019, DES-SQG-021, OBS-SQG-040, OBS-SQG-041

当前仓库 srcq 0.7.0 候选保留单方向 `srcq.symbol.calls/v1`，并以独立 `srcq.symbol.calls/bundle/v1` 共享 query、范围、root 与 deadline，incoming/outgoing 分支分别持有完整性和预算状态；`--source-manifest` 的首个 `vcxproj-direct-items/v1` adapter 只承诺直接项集合的 bounded 完整性。TSQG-119 的 schema、跨语言等价、范围边界、Token 与受影响组件验证已覆盖，差距在仓库候选层闭合。该状态不表示已部署、安装或发行；TSQG-120 的 skill 候选因实际价格反例被拒绝。

## GAP-SQG-009 query model 续页动作已经闭环

- 状态: resolved
- 关联: REQ-SQG-001, AC-SQG-007, AC-SQG-009, DES-SQG-015, UDES-SQG-015, OBS-SQG-027, OBS-SQG-028

P13 已在现有 query renderer 内把旧 cursor 片段替换为数量 `@more` 与完整 `@next`，正式 skill 只执行该动作。PowerShell 特殊 argv 往返与 fixture 调用日志证明续页保持 fingerprint 且 scc 只扫描一次；有效 v6 独立 Codex 原样执行 `@next`、取得第二页并正确报告首项，网络与 postflight 均有效。machine、cache/process、snapshot 状态、offset/length 和公共命令集合未改变，因此差距关闭。

## GAP-SQG-008 高成本查询的共享明显改进已经收敛

- 状态: resolved
- 关联: REQ-SQG-001, AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-007, DES-SQG-014, UDES-SQG-002, UDES-SQG-003, UDES-SQG-012, UDES-SQG-013, OBS-SQG-013

OBS-SQG-014 的早期纯规则结论已由后续命令链推翻；v1-v4 证明微观操作配方在质量与规划压力之间摆动，v5 否定高预算默认与过宽高级 skill，v7-v8 暴露已知正文重搜和权威范围污染，v19-v20 又把项目规则误用与候选规则成本分离。最终职责是：srcq 只在原总预算内承担机械可证有界闭环；全局规则承担权威范围、已知正文直读、按证据升级与充分即停；项目规则不把修改前置读取外推到纯只读定位。

v21 以 12/12 独立质量和 `1,066,470` Token 关闭本缺口。重复运行仍有正常命令选择波动，且耗时较 P9 上升；但当前记录没有共享失败、错误入口、截断或缺失能力能支持另一项低风险高收益修改。继续增加锚点、固定次数、阅读顺序或更大默认输出会重复已证实的反作用。因此“收益边缘”只在当前 corpus、模型、项目快照和 Provider 条件内成立；新失败、协议变化、新消费者或可重复共享机制出现时重新打开，不把当前数值固化为运行规则。

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
