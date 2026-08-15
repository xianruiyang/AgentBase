# 统一源码查询网关分支方案

## 1. 文档职责

本文件把 [current-state.md](current-state.md) 的已确认差距投影为可执行方案。任务合同见 `tasks/`，阶段顺序和闭环见 [plan.md](plan.md)。所有方案均受分支隔离约束；通过验证前不改变总体需求、正式 skill 或 Codex 安装态。

## SOL-SQG-001 固定后端、AST 与历史证据基线

- 状态: verified
- 解决: 已闭环的 P0 基线与 benchmark owner
- 满足: DES-SQG-001, DES-SQG-003, DES-SQG-010
- 依赖: AC-SQG-004, UDES-SQG-007, UDES-SQG-008

冻结 rg、fd、ast-grep 的精确版本、公开模式、help/schema、原生 argv、输出和退出 oracle；把现有 sgy AST 可观察合同变成可重复非回退基线，并把历史总 Token 结果登记为带证据上限的只读输入。随后在现有 `development/code-search-benchmark` owner 内建立绑定源码快照的 corpus、隔离 runner/monitor 和 detached audit capsule，不在分支目录或发布 payload 复制第二套执行器。

预期结果是任何实现前都能回答“要兼容什么、AST 什么不能改变、历史数字能证明什么、如何重复测量”。验证覆盖原生版本读回、现有 AST 定向/集成/真实引擎行为、corpus oracle 和 monitor 隔离；环境身份不完整时只降低结论，不伪造可比性。

## SOL-SQG-002 提取不改变 AST 的公共执行原语

- 状态: verified
- 解决: 已闭环的公共执行边界
- 满足: DES-SQG-001, DES-SQG-002, DES-SQG-004, DES-SQG-005
- 依赖: SOL-SQG-001

逐项比较进程、cwd、argv、stdin/TTY、stdout/stderr、退出、spool、snapshot、cursor、预算、诊断和 artifact 的生命周期与失败语义；只把三个后端真正相同的职责提取为内部原语。AST 命令、serializer、cache、profile 和 fingerprint 保持原位，rg/fd 使用新的 EvidenceSignature 与 renderer 注册。完整执行事实先由内存对象持有，默认模型回执只投影总量和三类完整性，异常与分页字段按状态出现；只有分页或显式 `--receipt full` 产生 snapshot 消费者时才计算身份并持久化，避免为完整短查询建立不可访问状态。完整诊断仍来自同一事实对象，不建立第二套事实源。

验证以冻结 AST oracle 无差异为先，并覆盖 rg/fd 的 0/1/N/N+1、native error、转换失败、截断、snapshot 和精确 cursor。不能证明同责的实现留在 backend，不以代码复用率作为验收条件。

## SOL-SQG-003 建立 fd 完整兼容与可逆低成本输出

- 状态: verified
- 解决: 已闭环的 fd 命令域与可逆表示
- 满足: DES-SQG-003, DES-SQG-004, DES-SQG-005, DES-SQG-006
- 依赖: SOL-SQG-001, SOL-SQG-002

实现 `sgy fd exec/defaults/doctor`，透明保留 `--` 后 argv，并按精确版本矩阵把公开模式分类为结构化、有界文本、artifact 或透传。普通路径结果用 NUL 分隔输入建立根别名与可逆 trie，同时生成 flat/tree 候选；只有 EvidenceSignature 相同且预计 Token 更低时选择 tree。

验证覆盖文件/目录、0/1/N/N+1、多根、绝对路径、Unicode、空格、同名目录、ignore/hidden、print0、exec/batch、help/version 和 round-trip。tree 不可还原或不更短时必须回到 flat。

## SOL-SQG-004 建立 rg 完整兼容与按证据单元投影

- 状态: verified
- 解决: 已闭环的 rg 命令域与自适应表示
- 满足: DES-SQG-003, DES-SQG-004, DES-SQG-005, DES-SQG-007
- 依赖: SOL-SQG-001, SOL-SQG-002

实现 `sgy rg exec/defaults/doctor`，普通 batch 通过 ripgrep 原生 JSON 事件解析 match/context/summary/error，并提供 locations、files、grouped、summary、lossless 与 raw 候选；特殊公开模式按矩阵显式进入结构化、有界文本、artifact 或透传，不再由 Python wrapper 猜测 argv 和前缀。每种 view 先形成自己的证据单元再分页：files 对匹配文件去重，locations 排除 context，正文视图保留 match/context，summary 对完整集合聚合且不产生续页。

定向验证增加“summary 不续页、files 总量按文件、locations 不产生 context 空页”的真实反例；完整验证仍须覆盖 fixed/regex、多 pattern、glob、上下文、no-match、count、文件列表、replace、passthru、preprocessor、显式 JSON、sort、help/version、长路径、长行、非 UTF-8 与子匹配。无匹配、原生错误、转换错误和结果省略必须可区分。

## SOL-SQG-005 复核 AST 并收敛三后端诊断、版本与供应链

- 状态: verified_with_advisory_limit
- 解决: 已闭环的 AST 非回退、诊断与候选供应链
- 满足: DES-SQG-001, DES-SQG-002, DES-SQG-009
- 依赖: SOL-SQG-003, SOL-SQG-004

用 P0 oracle 复核 AST 全部当前入口，只在序列化和行为等价时让 AST 复用公共原语；统一读取三个后端的精确版本、缺失、输出不兼容、透传和发布来源，但不统一它们不同的 cache、serializer 或副作用语义。sgy workspace package version 是默认 release、README、Cargo metadata、release helper、SBOM 与运行时版本的唯一来源；显式构建覆盖只制作被调用方主动声明的版本，不能承担候选日常版本真源。当前源码、Windows release、来源、许可证、manifest、payload 与安装 smoke 已统一到 `0.2.0` 并通过影响验证；仅新的 advisory scan 因宿主没有 `cargo-audit` 而未刷新。

任何非必要 AST 公开行为变化都使方案回到公共边界裁决。最终证据必须分别覆盖权威 owner 和三个实际后端，不能用 rg/fd 通过推断 AST 仍有效。

## SOL-SQG-006 建立候选统一 skill 并完成旧入口退出准备

- 状态: implemented
- 解决: GAP-SQG-002
- 满足: DES-SQG-008, DES-SQG-009
- 依赖: SOL-SQG-003, SOL-SQG-004, SOL-SQG-005

在分支验证范围内建立一个精炼的候选源码查询 skill，保留一次精确文件名、已知文件内少量文本和天然有界读取的原生快路径；只有全集、不存在证明、大结果压缩、目录树、AST、缓存或分页确实需要时才承担网关成本，真实符号身份改变结论时才升级 LSP。AST 现有规则完整迁入按需引用后，再准备退出旧 skill 与 rg Python wrapper 的消费者差异。

候选通过独立路由、相近非触发、AST/LSP 边界和写入安全证据前，不改写正式 skill。迁移完成必须证明当前消费者接入、旧同责决定路径退出、无悬空引用且 payload 不含 benchmark 资产。

## SOL-SQG-007 以当前候选身份的隔离总成本证据裁决采纳

- 状态: reopened
- 解决: 已闭环的模型收益差距, GAP-SQG-002
- 满足: REQ-SQG-001, AC-SQG-001, AC-SQG-002, AC-SQG-003, AC-SQG-004, DES-SQG-010
- 依赖: SOL-SQG-001, SOL-SQG-005, SOL-SQG-006

先运行后端定向、公共契约、性质/fuzz、真实版本矩阵和 detached 路由评估，再由正式 monitor 运行相同 experiment identity 的真实 Codex 对照。独立 auditor 逐案裁决质量并复算 `input + output` 总 Token，质量相同后比较 Token，前两项不退化后再比较 wall time；失败、回退和无收益样本都保留。

历史实验先证明只压低工具输出不足以降低总成本，再把普通查询移出 skill 触发面，并以跨根权威范围、关系端点和最小回答约束修复质量。当时候选在核心与严格语义均 12/12、严格整体 11/12 的前提下，实际总 Token 为 `1,146,601`、耗时为 `404,603 ms`；相对不再重跑的历史五-skill 记录方向性降低 `0.91%` Token 与 `20.43%` 耗时。该结论既缺少严格同 identity control，又不覆盖后续稀疏回执、语义投影、按需 snapshot 和单一版本来源改动，只能作为下一轮测试的历史输入。

当前裁决是保留实现方向、撤销“已达收益边缘”和采纳准备状态。先完成当前身份的供应链与受影响质量验证；真实独立 agent 路由和总成本对照按用户前序要求暂缓，未获得新证据前不恢复完成判断。只有随后质量、总 Token、速度依次满足并由用户明确采纳，才另行更新总体项目、正式 skill 和发布候选；实际发布仍需当次用户明确同意。
