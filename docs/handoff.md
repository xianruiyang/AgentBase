# AgentBase 当前接手状态

状态截点：2026-08-23（Asia/Shanghai）。

## 一句话状态

执行控制与 Skill 上下文生命周期第二版仓库候选已经形成：受支持场景中的可预防模型错误纳入 AgentBase 质量，任务原 owner 可保存证据前沿、验证维度和实际覆盖，srcq 现态诊断、领域 runner 升级与路由 oracle-only 零 Token 恢复已接入。候选尚未 Publish，真实 Codex 仍使用上次已发布版本；接手时已有的 Windows SWE 评测候选继续留在 dirty worktree，属于另一工作边界。

## 当前源码、安装与未提交边界

- 本文件所在提交是执行控制第二版源码版本；私有 `origin/main` 由项目持续 Git 授权非强制同步。不得用历史 HEAD、Release 或已安装副本反推当前源码。
- 真实安装最后一次正式发布仍是 Windows sandbox owner 修复与 srcq `0.4.2`：portable source 不再拥有 `windows.sandbox`，宿主保持 `unelevated`。第二版规则、skill 与路由 evidence 尚未安装；每次新的 Publish 必须另取当次明确同意。
- 必须保留并排除于本版本提交：根 `README.md` 的 sandbox 导航 hunk、`development/agent-evaluation/` 的 Windows SWE 修改与 `vendor/`、以及 `docs/requirements.md` 中 AC-062—AC-065 等评测合同 hunk。本版本只拥有 `docs/requirements.md` 的 REQ-002→AC-066 关联和 AC-066 条目。
- Windows SWE 仍是 9 题、Sol medium/Luna max 的独立评测边界；elevated sandbox setup、qualification、候选模型和外部 Verifier 未因本版本执行。不得通过全局 portable config 间接启用 elevated 后端。

## 第二版职责与完成边界

- `global/AGENTS.md` 只保存跨项目不变量：维度化最小验证、反例熔断并先写回、模型错误归责、反复脆弱接口升级领域 runner、工具缺陷先重放现态。
- `execution-governor` 持有运行期前沿和扩量；`delivery-workflow` 持有阶段回流；`task-table-manager` 在既有 task/state/result 中分别保存 `validation_dimensions`、执行检查点和 `validation_coverage`，`context` 同源投影关联 DCR；没有新增恢复真源。
- `source-query` 只在当前 srcq 能力、错误、降级或恢复协议待裁时读取 `diagnostics.md`；普通 rg/fd/scc/hyperfine 仍不加载该 skill。
- `development/skill-routing` 的 `oracle_revalidation` 只接受当前 oracle 已通过且与一份旧 `oracle_violation` 收据在文件、可见输入、capsule 和 evaluator 上精确相同的结果；零 Token、不占采样次数，但占有界收据并通过历史与 merge 校验。
- 仓库候选完成不等于真实行为完成。发布后必须在新任务用相近 UE 场景验证反例写回、维度覆盖和正式 runner 选择；没有该证据时只能称仓库合同已验证。

## 当前验证证据

- `skills/task-table-manager/tests/test_taskctl.py`：98 tests passed，覆盖旧状态兼容、检查点 CAS/清空、关联 DCR、维度与结果覆盖分离。
- 四个受影响 skill 的 `quick_validate.py`：全部通过。
- `development/skill-routing/validate_contract.ps1`：101 cases、60 strict routing、15 strict references、12/12 skills 正负触发覆盖。
- `development/skill-routing/test_routing_infrastructure.ps1`：6 suites、22 PowerShell syntax files、0 模型调用；最终全量结果以本文件所在提交的验证记录为准。
- 从 Git 暂存索引构造的独立临时 worktree 通过正式部署 `Validate`：46 项基线 Windows SWE 测试、`valid:true`；当前组合工作树另有 67 项通过，dirty 评测候选不属于本版本。
- 当前路由 generation：`D0B41EA251A5E264D55ECC7447A24C0E5D987B806FE4F21A504483AD921DDE61`；Routing 101/101、Policy 101/101、References 38/38。最后刷新从两份 passed staging 恢复，并对原 References 结果执行一次零 Token oracle revalidation：evaluator run 0、input/output tokens 0。
- 完整事实、方案、证据上限和完成审计见 `docs/work/20260818_execution_control_lifecycle/`；不要把本 handoff 当历史日志或第二真源。

## 下个对话的最小恢复步骤

1. 读取根 `README.md` 与本文件，运行 `git status --short`；保留上述 Windows SWE/README/requirements dirty 边界，不清理、不回退、不并入无关提交。
2. 若本文件所在第二版提交已在私有上游且工作树只剩既有 dirty 边界，则没有开放仓库实施项；只有出现真实新任务反例、选择其他子计划或改变跨组件方向时才读取 `docs/plan.md`。
3. 任务依赖真实安装状态时，按部署说明只读运行 `DirectCompatibility + InstallPortableSettings Status`；不要用本文件的最后已知值替代读回。
4. 规则、skill 或触发合同变化时先跑确定性路由入口并读取增量计划；不变输入不重采样，旧 oracle 被修正而原 stage 已通过时应走 `oracle_revalidation`。
5. Windows SWE 的 elevated setup/qualification 仅在相应外部操作授权下运行；普通仓库验证不得初始化 sandbox、克隆任务、安装依赖或启动候选模型。
6. 任何向真实 Codex 根目录的 Publish 都必须重新取得当次明确同意；发布只证明安装文件，行为变化要在新任务或重启会话中验收。
