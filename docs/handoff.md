# AgentBase 当前接手状态

状态截点：2026-08-22，Windows sandbox 宿主所有权事故已完成运行恢复、仓库修复和正式发布；未运行真实 elevated sandbox/qualification/候选模型（Asia/Shanghai）。

## 一句话状态

Codex 因全局 portable config 错误拥有 `windows.sandbox = "elevated"` 而出现 Windows 设置未完成；用户切回 `unelevated` 后恢复启动。仓库已把该键从 source 移除并以稳定身份迁移为 `transferred`，配置、生命周期、完整部署消费者与正式 Validate 均通过；正式 Publish 为 changed 0，发布后宿主仍为 `unelevated`、formal Status gap 0。接手时已有的 Windows SWE 评测候选仍保留在 dirty worktree，外部 elevated sandbox acceptance 与九题 qualification 仍是另一工作边界。

## 当前源码、安装与发布边界

- 当前源码与真实安装的 srcq 版本均为 `0.4.2`；源码提交 `ef65946f` 已推送私有 `origin/main`，私有 Release 为 `srcq-v0.4.2`。不得把旧交接中的 0.4.1、历史 HEAD 或已安装副本当成当前完整源码。
- AgentBase Windows SWE 的唯一 owner 是 `development/agent-evaluation/`；正式目标和外部缺口见 `docs/work/20260820_agentbase_final_evaluation_set/`。最终集固定 9 个任务、2 个 profile（Sol medium、Luna max）、18 个候选结果槽位。
- 执行控制第一版由 `skills/execution-governor/` 持有运行期算法，`global/AGENTS.md` 只持有共享未知先证实、成立前不扩量与反例熔断；`delivery-workflow`、`task-table-manager`、`change-governance`、`reasoning-governor` 分别只保存交付投影、任务依赖、长期治理和线程设置。正式证据见 `docs/work/20260818_execution_control_lifecycle/`。
- 用户意图重组的跨项目不变量由 `global/AGENTS.md` 持有，`skills/delivery-workflow/` 只维护交付链中的澄清与投影：用户明确指定且经澄清的技术约束仍进入 `UDES`，仅用于表达期望结果或尚未经证据支持的原因、解法才保持为候选，不得据此静默替换用户目标或扩大授权。
- taskctl 起止时间的唯一 owner 是 `skills/task-table-manager/scripts/taskctl.py` 的 `task.state` 生命周期：第一次真实开始后保留 `started_at`，进入 `done/retired` 写 `ended_at`，离开终态只清空结束时间；旧状态缺字段时保持未知，不推测历史时间。skill 合同、model/machine 投影、render 和回归测试已经迁移。
- 本轮通过私有 Release 从 srcq 0.4.1 Upgrade 到 0.4.2；Status 为 ready、完整性 verified、PATH 条目 1，AST/scc doctor 与已安装 `srcq more q2` 续页正常。随后以 `DirectCompatibility + InstallPortableSettings` 正式 Publish，发布后 `managed_payload_formally_published:true`、gap 0；变更 3 个受管资产，回滚备份为 `C:\Users\gzxt\.codex\backups\AgentBase-20260822-153600-61708e97`。
- 上述发布没有写 `config.toml`，但此前 portable settings 长期拥有 elevated Windows 后端。修复发布同样没有改写安装文件（changed 0），只把 `config:windows/sandbox` 的 `transferred` 状态写入新 manifest；当前安装保持 `sandbox = "unelevated"`，formal Status 为 published、gap 0，收据目录为 `C:\Users\gzxt\.codex\backups\AgentBase-20260822-173018-7cdc4621`。
- 每次新的 Codex Publish 仍必须取得用户针对当次操作的明确同意；持续 Git 维护与私有远端非强制推送授权不替代发布授权。
- 仓库验证资产、语料、runner、测试和收据不进入 Codex payload；正式 `Validate` 已证明 Plugin payload 为 12 skills、2 custom agents、96 routing cases。

## 最终评测与权限状态

- 候选能力按 projected/configured/identity/probed/separate/excluded 六层表达。完整项目 `skills/` 每次派生到候选根 `.agents/skills/`，清单固定全部 `SKILL.md`、references、scripts 与 assets，preflight 必须证明逐文件可读且整个投影不可写；它通过 Git exclude 和 patch owner 排除于题目改动。
- 基础 CLI、Codex 和任务依赖运行时先冻结真实路径/哈希/版本；sandbox preflight 再消费 workspace 内哈希固定的“绝对路径 + 可执行文件 SHA-256 + argv”清单，不维护第二套工具名映射。除 doctor 外，同一 `srcq` 还实际运行 AST/cache、三页 rg 续读、fd tree、scc machine 和 artifact 往返。
- 每次候选把实际 venv Python，或 Node 题的实际 npm/pnpm（以及任何不同于基础身份的任务 Node）加入同一清单。`srcq doctor` 与 `srcq query scc doctor` 复用清单中已经验证哈希的同一 `srcq`。
- `development/common/codex_shell_environment_policy.json` 是 benchmark、路由 evaluator 与 Windows SWE 共用的模型 shell 过滤真源；policy SHA-256 进入各自运行身份，当前原生 Codex 已无模型实测接受全部 33 个严格 config overrides。Codex 服务进程只消费冻结网络投影；模型 shell 过滤 proxy、OpenAI/Codex、Git/SSH、云/包管理器凭据命名空间、语言注入与工作流控制变量，无模型 sandbox-check 由共享 runtime owner 构造空投影净化环境。候选 prompt 明确使用该题已经准备并固定身份的 Python venv 或 npm/pnpm scripts，并从同一 corpus allowlist 展示逐题合法修改范围，避免通用禁令误伤 Bandit `setup.cfg` 或 Meriyah snapshot；这些配置仍不冒充真实模型 shell/公开测试行为证据。
- child 从 stdout 返回 preflight；launcher 校验并持久化。候选可写 workspace 副本只供诊断，只有 launcher 在模型启动前写入 denied state 的受信结果才能形成 `blocked-precondition`，因此候选后续修改不能伪装成未调用模型。
- 安装 Codex 根目录是 `run`/`recover`/`sandbox-check`/`assess` 的同一显式输入，默认取 `CODEX_HOME` 或 `%USERPROFILE%\.codex`；候选配置和身份整体拒绝该根，launcher 不再另由 `USERPROFILE` 推导认证来源。使用非默认根时，恢复必须传入同一值。
- 正式权限合同固定 native Windows `elevated`：显式 profile 以 `:root = deny` 默认拒绝宿主读取、`:minimal = read` 保留公共运行时、候选根 write、`.agents/skills/.git/.codex` read，并以 `:tmpdir = write` 只重开 denied state 内的当前 attempt 临时面；完整 project/state/installed Codex root 继续显式 deny。preflight v9 要求 state/project canary、staged/installed auth 均不可读，核对 skill 全树只读、workspace 写入与 `TEMP/TMP/TMPDIR/APPDATA/LOCALAPPDATA` 范围。最后一次真实无模型探测在管理员 setup helper 处以 Windows 1223 取消；`unelevated` 又明确拒绝所需 split policy。没有环境变化时不得原样重跑，不能用 weaker fallback 或 mock 声称权限通过。
- shell、`apply_patch`、公开测试和自定义 subagent 已在能力合同 v4 中作为候选模型动作表达，但没有被无模型 preflight 标记为行为通过；需要 host/thread/MCP 的 skill 也由对应组件 owner 另行验证。hooks、网络、安装与发布仍排除于 SWE 候选权限。
- `sandbox-check` 不运行模型、网络、安装或 Publish，但首次成功建立 elevated backend 可能请求管理员批准并改变本机 sandbox 配置，必须在获得相应外部操作授权后显式运行。通过/真实 acceptance 失败/已知宿主前置阻塞分别退出 0/2/3。
- 九题源码当前均未 prepare，qualification 全部 pending，18 个 task/profile 行全部 unqualified，候选结果为 0。`prepare`、`oracle`、`run` 都不是日常门禁；以后先完成真实 sandbox acceptance，再逐题明确运行 qualification。

## 当前验证证据

- `development/agent-evaluation/test_agent_evaluation_infrastructure.ps1`：67 tests passed，模型 evaluator 禁用；包含 Python/PowerShell policy 序列化一致性、完整 skill 投影、模型 shell/launcher 环境过滤、题目固定运行时提示、真实 PowerShell `.CMD` 精确路径 probe、五项 srcq 工作流、短句柄三页续读、双清单篡改回执、宿主默认 deny、项目/state/双认证不可读、attempt temp/appdata 和受信失败结果边界。
- `development/code-search-benchmark/tests/test_experiment.py`：34 tests passed；共享 policy/launcher sanitizer、benchmark identity、CLI overrides 与 override 防篡改均通过。
- `development/skill-routing/test_routing_infrastructure.ps1`：`ready:true`、6 suites、22 个 PowerShell syntax files、0 模型调用。
- `development/skill-routing/validate_contract.ps1`：96 cases；55 strict routing、10 strict references、12/12 skills 正负触发覆盖。
- 当前路由 generation 为 `C27D84237B4B8944905C34E1C452D5F460229C81DB76FDFB9922D8437A07F066`；当前 plan 为 0 evaluate、3 reuse、0 blocked、0 pending，refresh 为 `already-current`，本轮没有模型重采样。
- `skills/task-table-manager/tests/test_taskctl.py`：94 tests passed；覆盖开始、阻塞、恢复、完成、render、重开、退休、release、旧状态兼容、任务合同更新不改时间和 model/machine 时间投影。第一次全量回归只暴露旧 7 列 render 断言，修正为 9 列 oracle 后受影响单项与全量均通过。
- 当前组合工作树的正式部署 `Validate` 与 Publish 内置门禁均返回成功并各消费 67 个 Windows SWE 基础设施测试；首次 Validate 暴露预检仍解析旧 `--after` 长命令，迁移到哈希固定 `srcq.exe more q<number>` 并通过聚焦测试后，全量门禁通过。路由 evaluator 只验证引用选择，不证明 skill 已在当前旧任务中追溯加载；已发布行为需新任务使用。
- Windows sandbox 所有权修复中，`test_portable_config.ps1`、`test_managed_asset_lifecycle.ps1`、`test_manage_agentbase.ps1` 和正式部署 Validate 全部通过；完整部署测试证明宿主 `unelevated` 经 Publish/Status/Rollback 保持不变，manifest 生命周期为 `transferred`。所有门禁均未触发模型、UAC 或 elevated setup。
- 只读 host `check` 找到全部必需工具且 `missing:[]`；真实 `ast-grep` 路径为 npm `ast-grep.cmd`。完整验证记录见 `docs/work/20260820_agentbase_final_evaluation_set/verification.md`。

## 下个对话的最小恢复步骤

1. 读取根 `README.md` 和本文件，运行 `git status --short`。仍应保留接手时已有的 `development/agent-evaluation/` 修改与 `vendor/`、根 `README.md` 的 sandbox 导航 hunk，以及 `docs/requirements.md` 的评测合同 hunk；不得清理或并入无关提交。当前分支的已提交版本应与既有私有上游同步。
2. Windows sandbox 修复已经发布闭合，没有开放实施项；Windows SWE dirty 候选属于另一工作边界，评测 elevated setup 不得通过全局配置间接启用。只有处理该重开项、选择或替代其他子计划，或重新裁决跨组件方向时再读取 `docs/plan.md`。
3. 若任务依赖真实安装/发布状态，严格按部署说明只读运行 `DirectCompatibility + InstallPortableSettings Status` 和 srcq `Status`；不要用本文件的最后已知值替代读回。
4. 若用户授权改变宿主 sandbox 配置，先显式运行 `sandbox-check`；通过后再另行取得外部依赖/qualification 授权，按 smoke → core 余项 → rotation 逐题运行 `prepare/oracle`。没有这些授权时只维护仓库和确定性验证。
5. 规则、skill 或触发合同变化时先运行路由确定性入口并读取 evaluation plan，只执行 `evaluate` 阶段；相同身份与 oracle 有效时复用，不为期待不同结果重采样。
6. 任何向真实 Codex 根目录的 Publish 都必须再次取得当次明确同意；发布成功只证明安装文件，行为变化仍需新任务或重启后的运行验证。
