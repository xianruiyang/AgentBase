# 当前状态与差距

> 生命周期：2026-08-21 失败现场记录，不是当前状态 owner。当前实现与状态由 [`development/agent-evaluation/README.md`](../../../development/agent-evaluation/README.md) 和[开发环境治理任务表](../20260830_development_environment_governance/TASK_TABLE.md)维护。

## OBS-001 旧草案使用 Pier/Linux，不能评价完整 AgentBase

- 状态: confirmed
- 来源: 本轮修改前 \`development/agent-evaluation/\` 直接源码审查

原未提交草案把候选放进 DeepSWE Linux/Pier 环境，却又投影 Windows-only AgentBase 规则；\`srcq\` 与真实 Windows PowerShell 无法等价使用，环境失败会混入能力分数。该草案没有正式发布或提交消费者，因此本轮可直接替换而无需兼容入口。

## OBS-002 九题官方资产适合首批 Windows 迁移

- 状态: confirmed
- 来源: DeepSWE 固定提交中九题 task.toml、instruction、solution、tests、config 与共同 grader 的逐项审查

九题均为 Python/TypeScript，使用 pytest、Jest 或 Vitest；不存在所排除任务中的 Unix owner、signal、pseudo-TTY、可执行位或 \`/proc\` 主合同。每题六项资产和基础提交已取得 SHA-256/Git 身份；九份 grader 字节一致。

## OBS-003 上游测试脚本可投影为无 shell 的 Windows argv

- 状态: confirmed
- 来源: 九题 \`tests/test.sh\`、environment Dockerfile 与 config 的逐项对照

任务特有 base/new 选择、build/codegen gate、环境变量、报告格式和 Meriyah whitespace fixup 都能用 argv、pytest JUnit、Jest JSON 或 Vitest JUnit 表达。依赖安装仍有外部包漂移风险，因此 qualification 与候选必须比较实际 dependency inventory，而不能只相信命令文本。

## OBS-004 Codex 原生 Windows sandbox 支持所需权限边界

- 状态: confirmed
- 来源: OpenAI 官方 Windows sandbox、CLI 与 config reference，2026-08-20/21 查阅

Native Windows 支持 elevated/unelevated sandbox、自定义 permission profile、workspace 扩展、目录 deny 与 network disabled；当前 CLI 的实际命令是 \`codex sandbox -P ... -C ... -- <command>\`。官方权限文档明确说明 elevated 最强，unelevated 不能执行全部 split read/write carveout，遇到不支持的策略会拒绝而不是静默放宽。Codex service traffic 与 sandbox command network 分属不同控制面，因此不需要给候选工具开放网络。

## OBS-005 一份固定参考补丁使用 permissive 空 context 行

- 状态: confirmed
- 来源: DeepSWE 固定提交九题 solution/test patch 的逐项 `git apply --numstat` 与 hunk 计数审计，2026-08-21

十八份固定 patch 中十七份可被严格 `git apply` 直接解析；SQL Formatter 的 `solution.patch` 在已声明 hunk 内有 20 个空 context 行缺少前导空格，原始字节因此报 `corrupt patch`。只补这 20 个语法前缀后，十八份 patch 均可被 `git apply` 解析；九份参考补丁的全部变更路径也都落在各题 allowlist 内。

## OBS-006 当前宿主尚未完成 elevated sandbox 初始化

- 状态: confirmed
- 来源: 2026-08-21 当前 npm Codex CLI 0.148.0 的真实无模型 sandbox preflight

修正 CLI 语法后，elevated 启动在管理员 setup helper 处以 Windows 1223（操作被取消）退出；切换 unelevated 后，CLI 明确拒绝 required read-only/split policy。重复运行相同输入不会改变该宿主事实，且批准 elevated 初始化会改变宿主 sandbox 用户、ACL/防火墙或本地策略，不能由确定性门禁静默触发。

## OBS-007 预检曾重复决定工具可执行入口

- 状态: confirmed
- 来源: 2026-08-21 `check` 的真实宿主工具身份与 preflight v6 源码对照

运行身份 owner 已把当前 `ast-grep` 解析为 npm 的 `ast-grep.CMD`，但 sandbox child 当时仍按工具名维护另一份 `.exe`/`.cmd` 映射；任务依赖身份也没有直接成为同一 preflight 输入。由 PATH 名称再次解析只能证明某个同名命令可运行，不能证明 sandbox 使用了候选身份已经冻结的同一个二进制或 Python venv。

## OBS-008 workspace 回执曾参与模型前置条件分类

- 状态: confirmed
- 来源: 2026-08-21 `invoke_candidate.ps1` 与 `agentbase_codex.py` 失败路径直接审查

child 的 stdout 由 launcher 校验后写入候选可写的 `.agentbase/preflight.json`；候选启动后的 launcher 故障也会使 Python 查看该文件并尝试解释为模型前置条件失败。虽然正常 preflight 失败时模型尚未启动，但该位置在模型运行阶段不再是受信状态，不能拥有“模型是否已经启动”或是否消耗尝试的分类权。

## OBS-009 原始安装 Codex 根目录曾不在显式拒绝与探测合同中

- 状态: confirmed
- 来源: 2026-08-21 `agentbase_codex.py`、`invoke_candidate.ps1` 与 preflight 直接审查

候选临时 home 的 staged `auth.json` 位于 denied state 内，但 launcher 仍从宿主默认 `.codex` 读取真实认证与模型目录；旧配置没有把该原始安装根加入 candidate deny，preflight 也只尝试读取 staged auth。`:workspace` 基线没有为该原始凭据路径提供直接拒绝证据，因而不能证明“候选只看到公开输入”的显式合同；自定义 `CODEX_HOME` 还会与 launcher 的 `%USERPROFILE%\.codex` 推断分裂。

## OBS-010 继承 workspace 不等于宿主默认拒绝

- 状态: confirmed
- 来源: 2026-08-21 OpenAI Permissions 的 workspace-only 正式示例与生成配置、launcher 直接审查

官方 workspace-only 示例在继承 `:workspace` 后仍显式设置 `:root = deny` 与 `:minimal = read`，前者才拒绝工作区外的默认读取，后者只重开公共工具运行路径。旧候选配置只有 state/installed-root 两条局部 deny，不能证明项目仓库或其他宿主路径不可读；同时 launcher 把 `TEMP/TMP` 放在已经整体拒绝的 state/Codex home 下，新增默认 deny 后会使子进程临时目录与权限合同冲突。

## OBS-011 单文件 skill 探针和 doctor 不能代表候选完整能力

- 状态: confirmed
- 来源: 2026-08-21 OpenAI Build skills/Permissions 正式文档、旧 preflight v8 与 srcq 缓存/分页真实命令对照

Codex 在仓库的 `.agents/skills` 发现 skill，选择后读取完整 `SKILL.md`，再按需读取 references、scripts 与 assets；旧实现只把 `source-query/SKILL.md` 复制为普通 workspace probe，既不证明其他 skill 可发现，也不证明支持文件可读或候选不能改写投影。旧 preflight 的 `srcq doctor` 与 scc doctor 只证明安装与引擎可用，没有实际覆盖 AgentBase 已承诺的 AST/cache、rg 分页续读、fd tree、scc machine 和 artifact 工作流。真实 srcq cache 使用 `LOCALAPPDATA`，把进程临时面放进候选 workspace 还会把运行缓存与待评分源码混在同一写入边界。

## OBS-012 Codex 服务、sandbox launcher 与模型 shell 是不同环境消费者

- 状态: confirmed
- 来源: 2026-08-21 OpenAI Codex config reference 与 `codex_runtime.py`、候选生成配置、sandbox-check 调用链对照

固定 HTTP provider 的 Codex 服务进程需要冻结 proxy 投影以避免连接重试，但 `shell_environment_policy` 才决定模型 shell 继承哪些变量；旧生成配置没有覆盖该独立边界。无模型 `sandbox-check` 也曾以 raw ambient environment 启动 PowerShell launcher，而不是复用其他 evaluator 已采用的共享净化函数。另一方面，dependency identity 能证明 Python venv 或 npm/pnpm 已准备，却不会自动让模型知道公开检查应使用哪一个入口。

## OBS-013 通用 prompt 禁令曾与逐题解法范围冲突

- 状态: confirmed
- 来源: 2026-08-21 候选 prompt、corpus `allowed_patch_paths` 与固定官方 solution path 对照

旧 prompt 一律禁止修改 test infrastructure 与 dependency manifests，但 Bandit 的固定官方解法需要允许的 `setup.cfg`，Meriyah 的逐题范围也明确允许特定 parser snapshot。最终 patch 门禁已经以 corpus 为唯一真源，prompt 再维护一条更宽泛且不同的禁止语义会误导候选，即使机械校验本来允许合法解法。

## GAP-001 旧正式语义与 Windows 目标不一致

- 状态: superseded
- 关联: OBS-001, DES-001, DES-003

旧 corpus、adapter、文档和确定性测试的 Pier/Linux 语义必须整体退出，不能留下同责兼容入口。

## GAP-002 缺少候选/Verifier 隔离与 Windows oracle

- 状态: superseded
- 关联: OBS-002, OBS-003, OBS-004, DES-002, DES-005, DES-006

本轮开始时没有 state deny preflight、双工作区、patch allowlist、原始提交依赖安装、Windows 报告 adapter、重复 no-op/reference qualification 或匹配依赖身份的候选门禁。

## GAP-003 真实九题 qualification 尚无运行证据

- 状态: open
- 关联: AC-004, CON-002

基础设施可以确定性验证，但本轮不授权外部依赖安装与真实 oracle。所有题在新 clone 中仍为 pending；必须以后逐题显式运行 \`prepare\` 与 \`oracle\`，不能在文档中预先写成 qualified。

## GAP-004 上游 permissive patch 会阻断严格 Windows oracle

- 状态: superseded
- 关联: OBS-005, AC-004, AC-005

直接把固定上游 patch 路径交给 `git apply` 会使 SQL Formatter reference oracle 在测试前失败；适配必须保持原 asset 哈希可审计，只修复可机械证明的空 context 前缀，不能维护修改后的第二份参考补丁。

## GAP-005 候选能力与跨 owner 最终证据缺少统一边界

- 状态: superseded
- 关联: DES-008, AC-006, AC-010

仅列出投影文件或已安装工具不能证明独立候选实际可用；原报告也没有把原生合同、权限验收、路由、外部 reward、成本和基础设施健康放在同一证据向量中，容易把配置、缺证、阻塞和失败混写。

## GAP-006 真实 elevated sandbox 宿主前置条件未满足

- 状态: open
- 关联: OBS-006, AC-006, CON-002

仓库可以完整定义并确定性验证权限合同与阻塞语义，但当前宿主尚未取得管理员批准完成 elevated 初始化。本轮授权不允许代为触发该系统配置；因此真实 sandbox acceptance 仍需以后显式授权并在环境变化后运行一次，不能用 unelevated 或 mock 关闭此差距。

## GAP-007 工具身份与 sandbox 可执行性曾有两个决定入口

- 状态: superseded
- 关联: OBS-007, DES-008, AC-006

运行身份与 sandbox preflight 分别解析同一工具会允许路径漂移并遗漏题目专属 Python venv；必须由身份 owner 单向生成绝对路径、SHA-256 与参数清单，child 只验证并执行该清单，不能再维护平行映射。

## GAP-008 候选可写回执曾越过尝试状态的信任边界

- 状态: superseded
- 关联: OBS-008, DES-007, DES-008, AC-008

workspace 回执可保留为诊断，但模型前置条件必须由 launcher 在模型启动前写入候选拒绝访问的 state result；Python 只能用该受信结果形成 `blocked-precondition`，不得从候选可修改副本推断模型未运行。

## GAP-009 原始 Codex 凭据路径曾缺少单一显式边界

- 状态: superseded
- 关联: OBS-009, DES-003, DES-008, AC-006, AC-007

安装 Codex 根目录必须成为 CLI、候选配置身份、launcher 认证来源和 sandbox deny 的同一显式输入；state/work 与其不得重叠。preflight 必须在模型前分别证明 staged 与原始 `auth.json` 均不可读，任一可读都形成精确 acceptance 失败；不得再由 `USERPROFILE` 推导第二个认证入口。

## GAP-010 公开输入边界曾缺少宿主默认拒绝

- 状态: superseded
- 关联: OBS-010, DES-003, DES-008, AC-006, AC-007

候选 profile 必须按正式权限语义默认拒绝宿主根，只开放 `:minimal`、候选 workspace 与一个更窄的 attempt tmpdir，并用真实项目 canary 证明项目真源不可读。preflight 必须核对 `TEMP/TMP/TMPDIR/APPDATA/LOCALAPPDATA` 的精确范围；prompt、结果、临时面及项目/work/state/installed 根的互斥或包含关系也必须由 launcher 自身拒绝越界，而不能只依赖 Python 调用方。

## GAP-011 候选完整 skill 与 srcq 工作流曾只有存在性声明

- 状态: superseded
- 关联: OBS-011, DES-003, DES-008, AC-006, UDES-005

完整 skill 树必须进入 Codex 正式仓库发现路径，以 hash-pinned 全文件清单证明可读并以更窄权限证明不可写；运行临时面应与候选源码隔离并承载 srcq 缓存。srcq 能力必须在模型前以固定工具身份实际通过 AST/cache、分页、tree、machine 与 artifact 工作流，而不是从工具列表或 doctor 推断。模型工具、自定义 subagent 与需要 host/thread/MCP 的 skill 行为仍须分层保留为显式模型或组件证据，不能塞进无模型 preflight 伪造闭合。

## GAP-012 服务连接环境曾泄入模型 shell 合同且 sandbox-check 绕过共享净化

- 状态: superseded
- 关联: OBS-012, DES-003, DES-004, DES-008, AC-006, AC-007

服务连接所需网络投影只能留在 Codex launcher，模型 shell 必须通过正式配置启用默认 secret-name 排除并过滤 proxy、OpenAI/Codex、认证、凭据与 Git 控制变量；无模型 sandbox-check 必须由共享 runtime owner 构造净化环境。候选 prompt 还必须明确使用已经准备并进入身份的题目运行时。三者都只能证明各自配置或入口，真实 shell/公开测试行为仍由显式候选模型证据完成。

## GAP-013 候选提示曾有第二套 patch 范围语义

- 状态: superseded
- 关联: OBS-013, DES-003, DES-008, AC-003, AC-006

逐题 `allowed_patch_paths` 必须同时决定候选可见范围提示与最终机械校验；prompt 只补充清单外禁止项，不能用笼统的测试或依赖禁令覆盖 corpus 已允许的官方解法路径。
