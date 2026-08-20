# 实施方案

## SOL-001 以 Windows v2 corpus 替换 Pier 草案

- 状态: implemented
- 解决: GAP-001
- 关联: DES-001, AC-001, AC-002

九题 corpus 固定来源、难度证据、任务/上游身份、asset 哈希、profile、suite、patch allowlist、依赖与测试 argv；schema 与 Python validator 同时拒绝任务漂移、shell 组合和退休运行时。

## SOL-002 建立候选/Verifier 双工作区与权限 preflight

- 状态: implemented
- 解决: GAP-002
- 关联: DES-002, DES-003, AC-003, AC-006, AC-007

候选把全局 AGENTS/config/agents 投影到 denied state root 内的临时 Codex home，把完整 skill 树投影到候选根 `.agents/skills`；使用宿主默认 deny、最小运行时 read、workspace read/write、skill read-only、attempt tmpdir write、state/project/installed-root 精确 deny、network false 的 elevated profile。模型前用同 profile 验证 state/project canary、staged/installed auth、skill 全树哈希/可读/不可写、workspace 写入、temp/appdata 精确范围、由运行身份单向派生的精确路径/可执行文件哈希工具清单、全部基础 CLI、任务 venv Python 或 package manager及同一 `srcq` 的关键工作流。候选结束后才创建 Verifier；唯一输入是按题目路径、文件数、字节数和 Git mode 校验的 binary patch。

## SOL-003 接入 Windows dependency、report 与固定 grader

- 状态: implemented
- 解决: GAP-002
- 关联: DES-005, AC-004, AC-005

每个候选、no-op、reference 与 Verifier 都从固定基础提交建立独立依赖；安装后清理已知 lock 漂移并要求 tracked tree 干净。测试通过 verifier permission profile 运行，报告适配后交给原始 grader；实际 dependency inventory 纳入资格匹配。

## SOL-004 实现身份、不可变收据、有限重试与无模型恢复

- 状态: implemented
- 解决: GAP-002
- 关联: DES-006, DES-007, AC-007, AC-008

Qualification、candidate、attempt、patch、日志与结果均有稳定 schema/哈希；缺少资格不消耗重试，同身份基础设施失败仅允许一次带理由重试。已有候选输出时 run 强制转向 Recover；Recover 不包含候选调用路径，重核当前冻结身份与 patch，优先复用不可变候选/Verifier 收据。单题锁可回收已证明死亡的 PID owner，终态工作区默认退出。

## SOL-005 接入零模型门禁与项目消费者

- 状态: implemented
- 解决: GAP-001, GAP-002
- 关联: AC-009, AC-010

确定性测试覆盖封闭语料、宿主默认拒绝的权限 TOML、正确 native sandbox 命令、PowerShell 语法、能力分层、模型禁用、项目/state/安装/workspace/tmpdir 边界、完整 skill 投影及保留路径、temp/appdata、真实固定路径 srcq 工作流、上游空 context 归一化、依赖与 Verifier 工具身份、死锁回收、报告转换、不可变收据、阻塞语义和无模型恢复合同。部署 Validate/Publish 前置调用该入口，但测试脚本不包含 sandbox-check/oracle/run。

## SOL-007 对固定上游 patch 做单向机械归一化

- 状态: implemented
- 解决: GAP-004
- 关联: DES-005, AC-004, AC-005

适配器在校验原 asset SHA-256 后解析 unified hunk 计数，只给 hunk 内完全空白且缺失语法前缀的 context 行补一个空格；其他字节保持原样，不生成仓库内修订副本。应用收据同时保存源/应用哈希、字节数和补齐数。九题十八份 patch 的离线审计证明只有 SQL Formatter reference 需要 20 次补齐，归一化后全部能被严格 `git apply` 解析。

## SOL-008 建立能力合同与真实权限 acceptance

- 状态: implemented
- 解决: GAP-005, GAP-007, GAP-008, GAP-009, GAP-010, GAP-011, GAP-013
- 关联: DES-003, DES-008, AC-006, AC-009

候选能力由项目真源和 corpus 派生为 projected/configured/identity/probed/separate/excluded 六层；能力合同 v4 显式区分完整 skill 投影、Sol medium/Luna max、多 agent 配置、shell/`apply_patch`/公开测试等模型动作、基础 CLI、任务 toolchain 与 host 依赖能力。preflight v9 消费运行身份 owner 的工具清单和 skill owner 的全树清单，逐项复核绝对工具路径/可执行文件 SHA-256 以及每个 skill 文件路径/字节数/SHA-256；skill 投影必须全部可读且不可写，并为候选题加入实际 venv Python 或 npm/pnpm。候选 prompt 同时从 task `allowed_patch_paths` 生成逐题范围提示，使官方配置/snapshot 解法与最终 patch 校验同源。哈希固定的同一 `srcq` 实际完成 doctor、scc doctor、AST/cache、三页 rg 续读、fd tree、scc machine 与 artifact 往返。它同时验证宿主默认 deny 下的 state/project canary、staged/installed auth 不可读、workspace 写入和 attempt temp/appdata；child 通过 stdout 返回机器收据，launcher 校验后把决定模型未启动的失败结果写入 denied state，workspace 副本不拥有尝试分类权，因此写失败、清单/工具漂移及候选后续修改都不会混淆前置条件。正式 corpus 固定 elevated；已知管理员 setup 不可用返回有原因码和恢复动作的 `blocked-precondition`，未知失败不降级。

## SOL-009 建立跨 owner 最终评价投影

- 状态: implemented
- 解决: GAP-005
- 关联: DES-008, AC-010

新增 `assess` 组合部署 Validate 的机器收据、sandbox assessment、当前路由 plan/evidence 和分页 SWE report；各 owner 继续唯一计算自身事实。最终 schema 固定六个维度，分别输出 failed/blocked/pending 集合、已知 Token/时间和基础设施健康，能力合同必须在 sandbox 与 SWE 消费者间完全一致，`composite_score` 为空。原生 Validate 失败也转换为有界证据，而不是使总评丢失；未知结构或来源异常继续阻断。

## SOL-010 关闭宿主默认读取并收敛过程临时面

- 状态: implemented
- 解决: GAP-010, GAP-012
- 关联: DES-003, DES-008, AC-006, AC-007

候选配置改为不继承宽泛预设的显式规则：`:root = deny`、`:minimal = read`、`:workspace_roots` 中候选根 write 与 `.agents/skills/.git/.codex` read、`:tmpdir = write`，并保留 project/state/installed-root 精确 deny。launcher 把 `TEMP/TMP/TMPDIR` 统一置于 denied state 内的 attempt `runtime-temp`，把 `APPDATA/LOCALAPPDATA` 置于其子目录，拒绝 tmpdir 与 project/work/installed-root 重叠、拒绝 state 外 prompt/result，并在结束时清理临时面。Codex 服务进程只消费冻结网络投影；生成配置从共享 JSON policy 取得 `shell_environment_policy`，对模型 shell 启用默认 secret-name 排除并过滤 proxy、OpenAI/Codex、Git/SSH、云/包管理器凭据命名空间、语言注入与工作流控制变量，policy SHA-256 进入配置和能力身份。无模型 sandbox-check 则用共享 runtime owner 的空投影净化环境。候选 prompt 对 Python/Node 分别指向已准备的 venv 或固定 package manager scripts。preflight v9 核对项目根 `README.md` 不可读、全部环境路径和 skill 写拒绝。能力合同升为 v4，sandbox/run assessment 升为 v3；旧能力、preflight 或 assessment 收据不能冒充新 acceptance。

## SOL-006 逐题完成真实 Windows qualification

- 状态: pending-external
- 解决: GAP-003, GAP-006
- 关联: AC-004, CON-002

以后先取得 elevated sandbox 宿主初始化的显式授权并通过 `sandbox-check`，再取得外部依赖资格运行授权，按 smoke → core 余项 → rotation 顺序逐题运行 prepare/oracle；只有 no-op=0、reference=1、两次重复和 dependency identity 全部一致才写 qualification。失败先裁决 Windows adapter 或上游环境，不启动候选模型碰结果。
