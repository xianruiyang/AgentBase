# AgentBase Windows SWE 最终评测集需求

## REQ-001 建立可逐题选择的差异化最终评测集

- 状态: confirmed
- 来源: 用户 2026-08-20 要求把难度有分级、内容有差异且容易移植到 Windows 的任务接入整体项目最终评测
- 关联: AC-001, AC-002, AC-003, UDES-001

AgentBase 应保存一份固定、可审计、可按 smoke/core/rotation/all 或单题选择的仓库级评测语料，覆盖不同难度与工程能力；选择、资格和缺失状态必须直接可见。

## REQ-002 候选与 Verifier 保持独立信任边界

- 状态: confirmed
- 来源: 用户确认“独立代理与 verifier 环境”指不同工作环境而不是另一个裁判代理，并授权按此完善
- 关联: AC-003, AC-004, AC-005, AC-006, UDES-002

候选只读取任务说明、基础源码和公开测试；Verifier 在候选结束后从同一基础提交创建另一份干净工作区，只接收候选 Git patch，再注入隐藏测试并确定性计分。参考答案、隐藏测试、依赖目录、测试配置与运行残留不得从任一方向越过边界。

## REQ-003 评价可恢复且日常验证不消耗模型

- 状态: confirmed
- 来源: 用户此前要求解决独立验证过慢、重复触发、网络配置遗漏、边界错误和失败原样重跑
- 关联: AC-004, AC-007, AC-008, AC-009, UDES-003

外部评测必须冻结当前 AgentBase、源码、任务、依赖、模型和运行环境身份，运行前登记尝试；有效零分不重采样，基础设施失败有界重试，中断后只恢复已有候选产物。日常 Validate/Publish 前置只运行零模型确定性测试。

## REQ-004 最终报告保持证据边界

- 状态: confirmed
- 来源: 用户要求将任务接入评价并作为以后评价最终成果的基础
- 关联: AC-005, AC-010, UDES-004

报告应分别呈现 Windows 原生合同、候选能力及权限验收、路由 evidence、题目资格、有效 reward、覆盖、难度、Token/耗时和基础设施健康；失败、宿主前置条件阻塞与待补证据分开，不用任意权重合成总分，也不把 Windows 派生结果冒充官方 DeepSWE leaderboard 成绩。

## AC-001 固定九个 Python/TypeScript 任务

- 状态: confirmed
- 关联: REQ-001, UDES-001

语料固定 DeepSWE v1.1 提交 \`435ee89ec2f2e2289f33b0da4f992f0b7b7266b9\` 中的 Returns、SQL Formatter、HTTPX、Awilix、Bandit、FastAPI、Meriyah、Clack 和 SuperJSON 九题，并逐题固定基础提交和六项 task asset 哈希。难度仅按 DeepSWE v1 页面公开的成功 rollout/116 分为 2 easy、3 medium、2 hard、2 very-hard，不声称是官方难度标签。

## AC-002 CLI 支持渐进选择且外部动作单题显式

- 状态: confirmed
- 关联: REQ-001

\`list\`、\`next\` 和 \`report\` 提供简洁人读视图与稳定 machine JSON；\`prepare\` 可按 suite 准备固定源码，\`oracle\` 与 \`run\` 必须显式指定一题，不能由日常验证或一次命令无界启动九题模型。

## AC-003 两工作区唯一通道是受限 Git patch

- 状态: confirmed
- 关联: REQ-001, REQ-002, UDES-002

候选与 Verifier 使用互不包含的目录和独立依赖。Verifier 只能在模型完成后创建；候选 patch 限定大小、文件数和题目真实解法路径，拒绝 symlink、submodule、测试、runner、lockfile 和未由该题官方解法要求的依赖 manifest。Verifier 在应用 patch 前从原始提交安装第三方依赖；题目必需的 patch 后 build/codegen/可编辑元数据刷新只能在禁网 Verifier 中执行并留证。

## AC-004 每题先完成重复 Windows qualification

- 状态: confirmed
- 关联: REQ-002, REQ-003

同一 corpus/framework/task/dependency/verifier-runtime identity 下，未修改源码必须得到 reward 0，固定官方参考补丁必须得到 reward 1，且至少重复两次、依赖及 Verifier 工具身份一致，才形成不可变 qualification 收据。未 qualification、依赖漂移或 Verifier 工具漂移的题不得进入候选运行。

## AC-005 固定上游 grader，明确派生评分

- 状态: confirmed
- 关联: REQ-002, REQ-004

每题继续使用 SHA-256 固定且字节一致的 DeepSWE \`grader.py grade\`、原始 \`config.json\` P2P/F2P node ids、missing-as-failed、worst-status-wins 与二值 reward。Windows adapter 只把 pytest/Jest/Vitest 报告转换为 grader 可读输入；上游 patch 若由 permissive writer 省略空 context 前缀，只允许在已声明 hunk 内补该前缀，并同时留存源/应用 SHA-256 和补齐计数。因运行环境和命令层已改变，结果明确标记 \`leaderboard_comparable:false\`。

## AC-006 候选真实消费 AgentBase 与 Windows 工具

- 状态: confirmed
- 关联: REQ-002, UDES-005

候选临时 Codex home 从项目真源投影 \`global/AGENTS.md\`、\`global/config.toml\` 与 \`global/agents/\`；完整 \`skills/\` 则按 Codex 仓库发现合同单向投影到候选根 \`.agents/skills/\`，覆盖所有 \`SKILL.md\`、references、scripts 与 assets。Sol 使用 medium、Luna 使用 max。候选 profile 必须默认拒绝宿主文件系统，只重开 Codex 定义的最小运行时读取、候选 workspace 读写和该 attempt 的 tmpdir，并把 skill 全树收窄为 read-only；模型前在同一 Windows elevated profile 中证明 state canary、项目根 canary、staged auth 与原始 installed Codex auth 都不可读，skill 清单与每个文件哈希全部可读且投影不可写，workspace 写探针通过，\`TEMP/TMP/TMPDIR/APPDATA/LOCALAPPDATA\` 也只能指向 attempt 临时面。launcher 校验 child stdout，并把决定模型未启动与 `blocked-precondition` 的结果写入 denied state，不能由候选可写的 workspace 副本决定尝试分类。模型前已经冻结的 \`srcq/rg/fd/scc/hyperfine/ast-grep/git/pwsh/python/node\` 以及当前题实际 venv Python 或 npm/pnpm 必须由同一 workspace 清单绑定绝对路径、可执行文件 SHA-256 与参数；sandbox child 先验证清单哈希，再按精确路径验证并执行工具。\`srcq doctor\` 与 \`srcq query scc doctor\` 之外还须实际验证 AST/cache、rg model 分页续读、fd tree、scc machine 与 artifact 往返。Codex 服务连接所需 proxy 仅留在 launcher 环境，模型 shell 通过正式 \`shell_environment_policy\` 启用 secret-name 排除并过滤 proxy、OpenAI/Codex、认证、凭据和 Git 控制变量；无模型 sandbox-check 也必须由共享 runtime owner 生成净化环境。候选 workspace 配置允许 shell、\`apply_patch\` 与公开测试，多 agent 配置保持 Luna/max、Sol/medium；Python prompt 指向已准备的 \`.agentbase-venv\\Scripts\\python.exe\`，Node prompt 指向固定 package manager，避免模型误用未 qualification 的依赖。这些模型动作及需要 host/thread/MCP 服务的 skill 行为必须由显式模型或对应组件证据证明，不能由配置或 preflight 冒充。候选工具网络关闭，Verifier 也用独立 elevated profile 关闭网络；unelevated 无法执行完整读写拆分时不得视为通过。

prompt 的逐题修改范围直接投影 corpus `allowed_patch_paths`；合法的配置或 snapshot 解法不得被通用禁令误伤，清单外测试、依赖与 lockfile 仍禁止，最终 patch 校验继续消费同一真源。

## AC-007 网络、认证和运行身份在模型前冻结

- 状态: confirmed
- 关联: REQ-003, UDES-003

从当前 Codex \`.env\` 只投影固定网络 allowlist，清除未冻结网络别名、环境中的 OpenAI/Codex 凭据、常见 token 与 Git 工作区覆盖，且收据不保存值；固定 HTTP transport 避免 WebSocket 重连。安装 Codex 根目录是显式、冻结的运行输入并整体加入 candidate deny；认证只能通过其中既有 \`auth.json\` 的临时 hardlink 与运行期只读锁使用，结束即删除。候选/框架文件、生效候选配置、任务 asset/tree、上游提交、qualification、依赖及其执行工具、Codex/Verifier 工具、模型与档位共同进入身份。

## AC-008 尝试、终态、重试与恢复有界

- 状态: confirmed
- 关联: REQ-003

尝试在模型子进程前原子登记并持有单题/档位锁；锁只在 PID 已证明失活时回收。有效 reward 0/1 与候选越界零分均为不可重采样终态，缺失 qualification 属于不消耗重试额度的前置条件。相同身份基础设施失败最多允许一次带非空理由的重试；已有 candidate-finished/patch-captured 产物时必须转入 \`recover\`。\`recover\` 重新核对冻结身份与 patch，复用已存在的不可变候选/Verifier 收据或重建 Verifier，不得再次调用模型。

## AC-009 日常门禁只运行确定性基础设施测试

- 状态: confirmed
- 关联: REQ-003

语料、权限配置、命令数组、PowerShell 语法、能力投影、权限结果状态、报告转换、patch 边界、收据、生命周期和 evaluator 禁用条件由 Windows 本地零模型测试覆盖，并由部署 Validate 和真实 Publish 前置调用；门禁不得克隆任务、安装题目依赖、执行 qualification、启动模型、运行外部候选 Verifier 或触发 elevated sandbox 初始化。

## AC-010 报告不合成整体质量分

- 状态: confirmed
- 关联: REQ-004, UDES-004

\`report\` 按题目和 profile 保留 qualification、valid、reward、Token/时间、能力合同与基础设施状态；\`assess\` 组合部署 Validate、真实 sandbox preflight、当前路由 evidence 与 SWE 报告，但不刷新或运行模型 evidence。两者的 \`composite_score\` 固定为空。未执行的 qualification 和候选明确显示为缺失，权限初始化阻塞与实现失败分开，不以零或排除后的分母伪装完成。

## CON-001 只维护 Windows 正式入口

- 状态: confirmed
- 来源: 项目长期 Windows-only 约束与用户要求优先选择易移植任务

本组件不维护 Pier、Docker、Bash、Linux runner 或非 Windows 兼容路线；DeepSWE 仅作为任务、隐藏测试和评分语义的固定来源。

## CON-002 本轮不授权安装、真实 qualification、模型运行或 Publish

- 状态: confirmed
- 来源: 本轮用户授权完善仓库内容；项目逐次发布合同仍适用

本轮可以实现代码、文档、确定性验证与 Git 维护；不得安装宿主软件、请求管理员批准以初始化真实 elevated sandbox、执行九题外部 dependency qualification、启动真实候选模型或向实际 Codex 根目录 Publish。
