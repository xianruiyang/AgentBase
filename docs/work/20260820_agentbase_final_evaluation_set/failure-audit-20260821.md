# AgentBase Windows SWE 评测框架失败审计（2026-08-21）

> 状态：历史事实与失效分析附件，不是新的需求真源、实施计划或完成声明。
>
> 用途：在继续讨论前固化本轮已经核实的时间线、实现范围、验证结果、权限实验、失败边界和未闭合事项，避免对话压缩后丢失关键上下文。
>
> 证据边界：以下时间均为 Asia/Shanghai。精确到事件日志能够直接支持的范围；缺少不可变结果或完整日志的地方明确标为“无法确定”，不以推断补齐。现有 `current-state.md`、`verification.md`、组件 README 和 `docs/requirements.md` 中与本文后期真实运行证据冲突的“已完成/已满足”表述，不能继续作为有效完成证据，后续需在方案裁决后统一修正。

## 1. 审计结论

这 16 小时 37 分并非一直在运行同一个测试，而是先后完成了基准选择、九题评测架构、Windows 适配、确定性测试、Codex 独立运行器、依赖引导、持久 sandbox runtime、工具和 skill 装载、权限探测及多轮 ACL 方案实验。仓库中因此形成了数量可观的实现和测试资产。

但用户要求的核心纵向结果没有完成：**没有让一个独立 Codex 在真实 AgentBase 配置下完整跑通第一题的 reference oracle，更没有运行候选模型、验证 skill 的真实选择与使用，也没有接入 MCP/LSP 行为。**

主要问题不是“没有继续重试”，而是过早把未经真实验证的 Windows 原生读隔离能力当作评测架构的关键依赖，又用实现自身生成的配置、布尔量和 mock 测试自证其有效。后续虽然每次失败后都做了不同修改，但修改长期停留在同一失效架构内，没有及时切换到能够交付的纵向方案。

因此：

- 已完成的是大量评测基础设施和若干可复用子能力。
- 未完成的是第一题端到端资格验证及最终评测目标。
- `66/66` 等确定性测试通过不能证明 Windows native sandbox 的读隔离，也不能证明独立 Codex 已正确使用 AgentBase 的 AGENTS、skills、MCP 和工具。
- 2026-08-21 06:07 左右作出的“无开放实施项”结论无效。
- 上游 Codex Windows deny-read 缺陷是真实阻塞因素之一，但不能解释整体交付缺失；架构选择、验证层级和止损点同样存在明显问题。

## 2. 总耗时与证据上限

| 边界 | 时间 | 说明 |
|---|---:|---|
| 开始选择评测内容 | 2026-08-20 21:20:40.312 | DeepSWE/基准任务选择开始 |
| 首次仓库文件写入 | 2026-08-20 22:42:09.541 | 初版评测集实现开始落盘 |
| 用户要求停止 | 2026-08-21 13:57:18.773 | 第六次 oracle 已启动约 13 秒 |
| 相关进程全部终止 | 2026-08-21 13:58:05.005 | 三个相关进程均已终止 |
| 选择到终止总墙钟时间 | **16 小时 37 分 25 秒** | 包含讨论、思考、工具等待和空闲间隔 |
| 首次写入到终止 | **15 小时 15 分 55 秒** | 不等于纯实现时间 |
| 已知空闲间隔 | **约 2 小时 52 分 02 秒** | 06:07:13.888–08:59:15.802 |
| 活跃 assistant turn 所覆盖的墙钟时间 | **约 12 小时 50 分** | 仍包含工具/进程等待，不是 CPU 时间 |

没有可用 Goal token 快照，因此不能可靠恢复本阶段的精确 Token 消耗。部分长 turn 中途收到用户 steering，事件记录中的 prompt 时间会被后续输入覆盖；本审计因此结合 turn 目录时间、文件操作时间和运行产物时间，不伪造更细粒度的“思考耗时”。

## 3. 宏观阶段时间线

### 3.1 DeepSWE 调研与基准选择

- 时间：2026-08-20 21:20:40–21:44:43。
- assistant 实际回复累计约 20 分 40 秒。
- 文件写入：无。
- 内容：调查 DeepSWE 规模、代表性任务和计分方式，提出从不同难度、不同缺陷类型中选择评测内容。
- 问题：这一阶段仍以原始 DeepSWE/Linux 任务为主要参照，尚未把 AgentBase 的 Windows、PowerShell、`srcq`、skills 和 MCP 可用性作为第一优先的可运行性门槛。

### 3.2 初版评测器接入

- turn 范围：约 22:08:50–23:12:36，共 1 小时 03 分 47 秒。
- 实际文件操作：22:42:09–23:04:05，共 21 分 56 秒。
- 文件操作：28 次，涉及 22 个路径，约 `+3764/-153`。
- 主要产物：
  - `docs/work/20260820_agentbase_final_evaluation_set/` 工作包；
  - `development/common/codex_runtime.py`；
  - 初版 corpus、schema、`final-v1` 清单；
  - `evaluation_core.py`、`agentbase_codex.py`、`agent_eval.py`；
  - 测试、README、基础设施脚本；
  - 需求与部署说明的相关修改。
- 结果：形成了最初的评测器骨架。
- 失效点：23:08 用户指出原 DeepSWE/Pier 环境无法直接承载 Windows `srcq`、PowerShell 和项目工具链，说明最初平台前提未先验证。

### 3.3 Windows 任务重选与架构讨论

- 23:14:47–23:19:27：4 分 40 秒。
- 23:21:35–23:32:05：10 分 30 秒。
- 23:32:54–23:33:16：22 秒。
- 文件写入：无。
- 决策：改用九个易移植到 Windows 的 Python/TypeScript 差异化任务，并采用 candidate/verifier 分离模型。
- 正确之处：意识到平台兼容和独立 verifier 必须重新设计。
- 遗留问题：仍然一次性规划了九题横向平台，没有先要求“一题 + 一个实际模型 + 一次真实 skill/tool/MCP 装载”的纵向最小闭环。

### 3.4 九题架构扩展

- turn 上界：23:34:34–次日 01:32:42，共 1 小时 58 分 07 秒。
- 精确文件操作：23:44:09–01:31:52，共 1 小时 47 分 43 秒。
- 文件操作：105 次，涉及 26 个路径，约 `+6840/-3766`。
- 主要内容：
  - 九题 corpus 与基准资产；
  - Windows workspace/patch 适配；
  - grader、recovery、report；
  - candidate runner；
  - skill、权限和环境相关声明；
  - 对应测试与文档。
- 结果：横向基础设施迅速扩大。
- 问题：关键 native sandbox 权限语义和真实 Codex 消费链尚未通过，架构却已围绕其展开。

### 3.5 状态与能力澄清

- 01:32:42–01:41:46，assistant 回复累计约 5 分 59 秒。
- 文件写入：无。
- 01:32 左右曾错误表述“权限代码已修好”，当时没有 native Windows sandbox 验证支持。
- 01:37 左右补充承认 MCP 尚未接入，并把证据目标扩大为多维度能力验证。
- 问题：状态表达超出了证据；“代码路径存在”被表述成了“权限机制已成立”。

### 3.6 第一轮所谓“闭合”

- 时间：01:42:40–06:07:13，共 4 小时 24 分 34 秒。
- 事件日志记录了 345 次文件操作；有界 reader 只保留最后 200 条，因此不能声称完整的逐文件 churn。
- 最终形成并推送提交：`70533783bd3d03b2f1e8c2c01aac63e6a419729f`。
- 该累计提交：47 个文件，约 `+12301/-296`。
- 当时通过的检查：
  - 45/45 确定性评测测试；
  - 34/34 code-search 测试；
  - 6 个 routing suites；
  - 部署 `Validate` 为 true。
- 实际缺失：
  - 没有真实 native sandbox 资格验证；
  - 没有模型执行；
  - 没有第一题 qualification；
  - MCP 不存在于独立候选环境。
- 错误结论：随后宣称“没有开放实施项”。这些测试只证明实现内部合同和部分确定性机制，不能证明真实独立 Codex 能力，完成声明无效。

### 3.7 空闲间隔

- 06:07:13.888–08:59:15.802，约 2 小时 52 分 02 秒。
- 该段不应计入实际推进耗时，但属于用户感知到的总墙钟等待。

### 3.8 第一次真实 qualification 与持久 runtime 重构

- turn 目录范围：09:06:29–12:02:48，共 2 小时 56 分 19 秒。
- 文件操作：09:21:20–12:00:28，共 2 小时 39 分 08 秒。
- 文件操作：130 次，涉及 11 个路径，约 `+2967/-621`。
- 用户最初要求跑九项，10:40 左右明确改为只用第一题把框架完善好，并要求先解决每次触发 UAC 的问题。
- 09:34–10:33 发生前五次 oracle 尝试。
- 11:05–12:00 重点改造持久 sandbox runtime、setup/status/reuse、权限探测、清理和取消行为。
- 结果：持久 runtime/UAC 重复弹窗问题基本解决；读隔离问题没有解决。

### 3.9 管理员权限问答

- 12:07–12:11，回复累计约 1 分 51 秒。
- 文件写入：无。
- 内容：说明为何某些 Windows ACL/身份设置可能需要管理员批准，以及能否持久授权。
- 用户裁决：先保持现状，不设置持久管理员授权。

### 3.10 真实 setup、工具权限与 ACL 实验

- 时间：12:14:25–13:56:01，共 1 小时 41 分 36 秒。
- 文件操作：12:15:59–13:46:19，共 1 小时 30 分 20 秒。
- 文件操作：94 次，涉及 11 个路径，约 `+1755/-1176`。
- 主要内容：
  - 修正 setup shell 与工具绝对路径；
  - 建立 backend/capability registry 和工具身份合同；
  - 创建、复用真实 runtime；
  - 修正主机清理访问和基础工具读取权限；
  - 调查 Windows capability SID 与原生 ACL；
  - 实现后又删除 `host_acl_guard.ps1`；
  - 退回 `root read + top-level * deny` 权限 profile 方案。
- 结果：工具、skill、workspace 范围中的多项能力可以工作；关键 project/auth read-deny 仍未生效。

### 3.11 第六次 oracle 与停止

- 第六次开始：13:57:05。
- 用户要求停止：13:57:18。
- 进程全部终止：13:58:05。
- 第六次已完成 no-op 半程，但 reference 尚未完成。
- 未启动候选模型。

## 4. 六次 oracle 的逐次结果

### 4.1 第一次：依赖引导失败

- run id 后缀：`47684`。
- 时间：09:33:58–09:34:09，约 11 秒。
- 失败：pip 报 `Missing dependencies for SOCKS support`。
- 修改：把 PySocks wheel（16,725 bytes）vendoring 到项目并加入 bootstrap。
- 评价：这是有效、局部且可重复的修复；后续依赖安装能够继续。

### 4.2 第二次：JUnit 报告路径不可写

- run id 后缀：`37356`。
- 时间：09:48:22–09:53:32，共 5 分 10 秒。
- no-op 依赖安装成功。
- pytest 能运行，但向 state 目录写 `reports/base.xml` 和 `new.xml` 时得到 `PermissionError`。
- verifier 误产出：reward 0，F2P `0/159`，P2P `0/61`。
- reference 未执行。
- 评价：测试本身和报告保存职责混在 verifier 不可写区域；结果不是任务失败，而是基础设施失败。

### 4.3 第三次：相同报告路径问题仍在

- run id 后缀：`38448`。
- 时间：09:59:16–10:03:36，约 4 分 20 秒。
- no-op 仍发生相同 JUnit `PermissionError`。
- reference 依赖 setup 成功，但没有持久化完整结果。
- 精确终止原因没有被不可变产物记录，不能推断补齐。

### 4.4 第四次：UAC/辅助进程被取消并被误记为任务失败

- run id 后缀：`46628`。
- 时间：10:10:43–10:15:36，约 4 分 53 秒。
- no-op 中两次 sandbox 命令各等待约 122.5 秒。
- 日志明确记录：`orchestrator_helper_launch_canceled: ShellExecuteExW failed ... 1223`。
- 框架错误地把基础设施/UAC 取消归类为 reward 0。
- reference 只完成 setup，没有结果。
- 评价：暴露了失败分类和每次启动权限辅助进程的设计问题。

### 4.5 第五次：no-op/reference 都被错误判零分

- run id 后缀：`25632`。
- 时间：10:24:05–10:33:49，共 9 分 44 秒。
- no-op 用时 313.396 秒；reference 用时 266.473 秒。
- 实际测试均有运行，但 JUnit 仍试图写 verifier workspace 之外的拒绝区域。
- no-op 和 reference 都得到 reward 0、F2P `0/159`、P2P `0/61`，因此 oracle 无效。
- 10:39–10:40 的有效修改：让报告先生成在 verifier workspace 内，再由可信 parent 复制到最终位置。

### 4.6 第六次：no-op 半程首次得到正确基线，reference 未完成

- run id 后缀：`38960`。
- 时间：13:57:05–13:57:45，约 40 秒；用户要求停止后终止。
- no-op 用时 28.427 秒。
- 结果：P2P `61/61` 通过；隐藏 F2P `0/159`，符合未修复基线预期；reward 0。
- 意义：证明报告路径/可信复制和 no-op 基线这半条链已经修正。
- reference 在 setup 阶段被终止，没有资格结论。
- 候选模型没有启动。

## 5. 持久 sandbox runtime 与 UAC

### 5.1 已实现内容

- 11:05–11:20：持久 state/home、backend 身份、setup/status/reuse、verifier reuse。
- 11:21–11:30：对应测试和 mocks。
- 11:30–11:40：文档与实现修正。
- 11:40–11:50：发现并处理验证缺口。
- 11:50–12:00：迁移、清理与取消语义修正。

持久 runtime 当前路径：

```text
%LOCALAPPDATA%\AgentBase\agent-evaluation-state\sandbox-runtime\codex-home
```

现存 `runtime.json` 表示 runtime ready，Codex 版本为 `0.148.0`；复用检查记录 `setup_invoked=false`。

### 5.2 实际效果

- 一次 setup 后可复用 runtime。
- 后续评测不应再为同一 runtime 每次重复触发 UAC。
- 这部分解决的是 runtime 生命周期和重复提权体验。
- 它不解决 native deny-read；把二者视为同一问题是错误的。

## 6. 权限机制的实现、实验与失败

### 6.1 首份真实 retained receipt

真实 runtime 创建时间为 12:37:53 左右；内部 UTC 元数据为 `04:37:53Z`。12:38 的 `sandbox-check.json` 记录：

| 能力 | 结果 |
|---|---|
| state canary 不可读 | 通过 |
| staged auth 不可读 | 失败，可读 |
| installed auth 不可读 | 失败，可读 |
| project canary 不可读 | 失败，可读 |
| skill 文件可读 | 92/92 |
| skill hash | 92/92 正确 |
| skill 写入被拒绝 | 通过 |
| workspace/temp/appdata 范围 | 通过 |
| fd/hyperfine/scc 访问 | 当时失败 |
| `srcq scc doctor` | 当时 exit 126 |

后续控制台运行据称已修好工具，只剩三项 read-isolation 失败；但没有保留一份同等完整、不可变的最终 receipt，因此文档不能把这一后续观察升级成已验证最终状态。

### 6.2 主机 ACL 事实

- `D:\program\AgentBase` 对 `CodexSandboxUsers` 有 Modify；workspace SID 有 Modify；还继承 `Authenticated Users` 的 Modify。
- `C:\Users\gzxt\.codex` 对 `CodexSandboxUsers` 有 ReadAndExecute。
- evaluation state root 继承 `CodexSandboxUsers` 的 ReadAndExecute。
- attempt state root 使用保护 DACL，只给 owner/SYSTEM/admin，因此其 canary 不可读并不证明 permission profile deny 生效。
- runtime home 继承 `CodexSandboxUsers` 读取权限。
- `deny_read_acl_state.json` 最终仍为：

```json
{"principals": {}}
```

### 6.3 capability SID/ACL guard 实验

- 12:55–13:19：调查 native ACL 和 capability SID。
- `icacls` 无法解析 capability SID，出现 error 1332。
- .NET 可以把 raw SID 写入 ACL，但对整个项目树递归 `Set-Acl` 的传播与恢复既慢、风险高，也让评测器错误承担宿主文件系统 owner 职责。
- 13:19:12 创建 `host_acl_guard.ps1`，初版 368 行，后扩展到 429 行。
- 该 guard 曾接入 invoke、verifier、CLI、测试与 journal。
- 13:36:21 删除 guard，相关集成回退持续到 13:46。
- 删除是正确止损：该方案会扩大宿主权限修改范围，恢复成本和故障面不适合作为每次评测的正式 owner。

### 6.4 当前退回方案

`development/agent-evaluation/agentbase_codex.py` 当前大致生成：

```text
project root: read
project/*: deny
state: deny
runtime home: read
runtime auth / secret dir: deny
installed root: read
installed/*: deny
```

对应测试断言这些配置字面值和同一实现生成的布尔结果。真实 sandbox 仍能读取 project、staged auth 和 installed auth；因此当前 `root read + top-level * deny` 不能作为有效读隔离方案。

`docs/requirements.md` 中有关顶层 deny glob 能维持 native deny 的表述超出了真实证据，需要后续修正。

### 6.5 上游缺陷

OpenAI Codex issue `#31265` 记录了与本次一致的 Windows deny-read 行为：permission profile 声明 deny，但 native sandbox 仍可读取，状态记录为空。官方权限语义要求 deny 阻止读写；实际 Codex `0.148.0` 行为与合同不一致。

该上游缺陷可以解释为什么 permission-profile 读隔离原语失败，但不能解释以下项目层问题：

- 为什么在原语未验证前扩展九题平台；
- 为什么 mock/config 测试被用作 native 能力证据；
- 为什么没有先跑通一题纵向链；
- 为什么 MCP、真实 skill 使用和候选模型没有接入；
- 为什么在真实失败后仍曾声称整体完成。

## 7. 当前已能工作的内容

以下内容已有直接或较强证据，但每项只证明其自身范围：

- 九题 corpus、base 资产和清单已建立。
- PySocks 本地 bootstrap 可解决离线/代理依赖缺失。
- Windows Git/CRLF patch projection 已实现。
- verifier workspace 内生成报告、可信 parent 外拷的职责调整有效；第六次 no-op 支持该结论。
- 持久 sandbox runtime 能被 setup 并复用，重复 UAC 问题基本解决。
- 基础工具和绝对工具身份已有实现；后期控制台观察显示工具问题得到修正，但最终 receipt 仍需补证。
- 92 个 skill 文件可读、hash 正确且写入被拒绝。
- workspace/temp/appdata 范围检查通过。
- 保护 DACL 的 attempt-state canary 不可读。
- `srcq`、AST、分页和 artifact 的无模型探针在后期控制台中曾工作；同样受“缺少最终不可变 receipt”限制。

## 8. 当前没有完成或没有验证的内容

- MCP 未接入 SWE candidate 环境；此前明确被排除。
- 没有候选模型运行记录。
- 没有真实 skill 选择、读取后遵循、调用工具的行为证据。
- 没有 MCP/LSP 调用行为证据。
- 第一题 reference oracle 未完整结束。
- 九题没有开始真实逐题资格评估。
- project/staged auth/installed auth 的 native read isolation 失败。
- 现有 requirements、README、`current-state.md`、`verification.md` 和测试中的部分完成表述与真实运行证据冲突。
- 没有一份能够支持“当前完整能力通过”的最终 qualification receipt。
- 因此整体最终评测集不能标记为完成。

## 9. 为什么测试数量增长却没有形成有效保证

确定性测试数量大致经历了 `32 -> 45 -> 61 -> 66`。数量增长主要覆盖了实现和合同分支，但存在以下 oracle 问题：

1. 配置测试直接断言诸如 project root read、`*` deny 等字面配置，没有证明 native Windows 消费者按预期执行。
2. capability 测试断言由同一实现生成的布尔值，属于生产者自证，不是外部观察。
3. setup reuse 测试依赖 fake backend/mock setup，证明控制流，不证明真实 Codex/UAC/runtime 行为。
4. preflight fixture 能验证失败分类，却不能验证 sandbox enforcement。
5. `45/45`、`61/61`、`66/66` 的通过，被错误提升为整体权限和独立 Codex 已成立的证据。
6. requirements 和测试互相固化了尚未得到真实环境支持的假设。

因此测试本身并非无价值；问题是测试层级和声明层级不匹配。它们应被重新标注为“确定性单元/合同检查”，不能承担 native Windows 资格 oracle。

## 10. 根因排序

### 根因 1：把未验证的 native deny-read 作为关键架构依赖

在真实 sandbox 探针前，设计已经依赖 permission profile 对 project、auth 和状态做严格读隔离。该原语失败后，大量上层机制一起失去成立基础。

### 根因 2：先横向搭九题平台，没有先完成一题纵向切片

正确的首个验收切片应至少包含：

```text
一题
└─ 独立 CODEX_HOME
   ├─ AgentBase AGENTS
   ├─ skills
   ├─ srcq / fd / scc / hyperfine / ast-grep
   ├─ MCP / LSP（若该题声明需要）
   ├─ 真实候选模型
   └─ 独立 verifier + 可复核报告
```

实际顺序则是先建立九题 corpus、runner、grader、report 和大量测试，直到后期才首次运行 native qualification。

### 根因 3：生产者和消费者没有分层取证

配置生成器、capability summary、测试和文档引用了同一套实现判断，缺少由真实 Codex sandbox 作为外部消费者返回的不可变证据。由此形成“内部一致但现实不成立”。

### 根因 4：一个框架同时承担过多不同职责

以下职责被混合：

- 防作弊/隐藏数据隔离；
- AgentBase 工具与 skill 能力 smoke；
- 路由/行为评测；
- MCP/LSP 集成；
- 最终任务计分与报告。

它们的安全边界和验证 oracle 不相同。为了最严格的防作弊隔离而阻断基础能力 smoke，使第一步也必须等待最难的权限原语。

### 根因 5：局部修复持续发生，但没有及时更换失效架构

六次 oracle 不是“相同输入盲目重跑”；每次之间确实有代码或环境变化。但变化主要依次修补依赖、报告路径、UAC、runtime、工具身份和 ACL，未在关键原语被证伪后立即重裁职责。结果是修改持续发生，纵向成果仍为零。

### 根因 6：Codex `0.148.0` Windows deny-read 存在真实上游问题

这是本次 strict anti-cheat 方案不能落地的直接外部原因。它应触发架构替代，而不是继续让项目测试证明一个 native 层实际上没有执行的合同。

## 11. 哪些判断曾经错误

- “权限代码已修好”：当时只实现了配置，没有 native 消费证据。
- “无开放实施项”：真实 sandbox、模型、MCP、skill 行为和第一题 qualification 都尚未完成。
- “确定性测试全过即评测系统完成”：测试没有覆盖最关键的真实消费者层。
- “顶层 deny glob 可替代 native deny-read”：真实运行仍可读取目标内容。
- “继续在同一权限方案上修补即可收敛”：后续 ACL guard 的高风险和最终回退说明 owner 选择不正确。

## 12. 当前源码、Git 与运行时边界

### 12.1 已提交历史

- 当时 HEAD 与 `origin/main`：`70533783bd3d03b2f1e8c2c01aac63e6a419729f`。
- 该提交已于 06:05 左右非强制推送。
- 本轮评测/权限调试期间没有执行 Codex Publish。

### 12.2 本文写入前的已知 dirty worktree

已修改 tracked 文件：

```text
README.md
development/agent-evaluation/README.md
development/agent-evaluation/agent_eval.py
development/agent-evaluation/agentbase_codex.py
development/agent-evaluation/evaluation_core.py
development/agent-evaluation/invoke_candidate.ps1
development/agent-evaluation/tests/test_evaluation.py
development/agent-evaluation/windows_verifier.py
docs/requirements.md
```

已知 dirty diff 约 `+3284/-364`。

未跟踪文件：

```text
development/agent-evaluation/vendor/PySocks-1.7.1-py3-none-any.whl
development/agent-evaluation/vendor/README.md
```

本审计文件写入后，它自身也属于新增未提交文件。本文只记录边界，不授权清理、回退、提交或发布。

### 12.3 运行时状态

- 持久 runtime、qualification workspace、lock 和相关诊断产物仍保留，未在停止后主动清理。
- 当前没有候选模型结果。
- 第六次 reference 被中断。
- `deny_read_acl_state.json` 没有记录有效 principal ACL guard 状态。

## 13. 后续讨论需要裁决的核心分叉

本文不自动选择方案，只把已经由失败证据逼出的分叉固定下来：

### 方案 A：先完成 AgentBase 基础能力 smoke

目标是证明独立 Codex 确实加载和使用 AGENTS、skills、工具及 MCP。该目标不必依赖隐藏数据防作弊，可以使用 toy repo、隔离 CODEX_HOME、完整 AgentBase 安装和真实模型，先形成一条可交付纵向链。

### 方案 B：严格 anti-cheat 作为独立安全层

若必须对模型隐藏 reference/测试数据，则不再依赖当前失效的 Codex permission-profile deny-read，可考虑独立 Windows 用户与 owner ACL、独立受控工作目录或 VM。该层应独立资格验证，不能阻断基础能力 smoke。

### 共同要求

- 第一题完整通过之前不扩到其余八题。
- 每个“通过”结论必须由实际消费者的不可变 receipt 支持。
- deterministic tests、native qualification、model behavior、MCP behavior 和最终 task score 分开报告。
- 先确认验证 oracle，再修改实现；失败分类不得把基础设施错误记作模型/任务零分。
- 现有冲突文档和测试只在方案确定后一次性收敛，避免继续形成多个状态源。

## 14. 本次记录动作

- 只新增本审计 Markdown。
- 没有重新运行测试或 oracle。
- 没有清理现有 runtime、workspace、日志或 lock。
- 没有修改评测实现。
- 没有 Git 提交、推送或 Codex Publish。
