# AgentBase 当前接手状态

状态截点：2026-08-26（Asia/Shanghai）。

## 一句话状态

三角色子代理版本已从干净提交发布到实际 Codex：`evidence` 只读取证与观察既有执行，`experiment` 用可恢复操作探索路径、错误或约束，`operator` 在合同已确认后完成难以脚本化的有界执行。正式 routing evidence、部署 Validate/Publish 和发布后 Status 均通过；本范围没有开放源码实施项，保留的 Windows SWE 工作仍属于独立 dirty 边界。

## 当前源码、安装与未提交边界

- 实现链为 `4dd099f`（三角色配置、skill、部署与路由）、`034ff8f`（权威影响与受保护基线 oracle 解耦）、`234577e`（正式 routing evidence）、`6e61f0d`（评测能力合同消费 `operator`）。
- 实际安装通过 `DirectCompatibility + InstallPortableSettings` 发布，更新 11 个受管对象；回滚备份为 `C:\Users\gzxt\.codex\backups\AgentBase-20260826-120848-8faaed23`，同范围 Status 为 `published:true`。
- 发布从独立干净 worktree 执行，没有消费主工作树的未提交内容。必须继续保留并排除：根 `README.md`；`development/agent-evaluation/` 的 Windows SWE sandbox/runtime/corpus/test/vendor/adapters 候选；`development/common/codex_cli_runtime.ps1`；`development/skill-routing/validate_contract.ps1` 的源码阅读合同 hunk；`docs/requirements.md` 的评测合同 hunk；`global/AGENTS.md` 的源码阅读合同 hunk。
- 上述 dirty 内容未被清理、回退、提交或发布；其中共享 JSONL parser 与当前未提交测试曾使现工作树 Validate 失败，因此后继其他发布仍应先隔离或闭合该边界。

## 当前职责与证据

- `global/agents/evidence.toml`、`experiment.toml`、`operator.toml` 分别唯一维护三种角色的模型、档位和角色指令；当前依次为 Luna/medium、Sol/low、Luna/max。
- 等待时长不决定角色：只观察已启动对象归 `evidence`，启动/等待/分析冻结输入的已知执行归 `operator`，修改后反复运行以发现实现路径归 `experiment`。
- `operator` 只消费冻结输入、精确对象、正式规则、允许动作、oracle、dirty 边界与停止预算；先验收一个代表项，第一处失败、非等价或未知即停止。主代理保留目标、授权、设计、正式验收、完成、Git、发布与外部写入责任。
- Delivery 引用按实际修改类型选择：只有同次修改方案语义和任务/结果合同才双读 planning/execution；只消费已确认方案投影任务时只读 execution。
- 正式 generation 为 `C0241F1D3C319C415F969B3C29D67B34FAE589CFDAFFB5FFDC894C17F1F32F76`：123 cases、82 strict routing、27 strict references，最终计划 0 evaluate/3 reuse/0 blocked/0 pending。每个阶段只取得一次模型结果，没有相同可见输入重采样。
- 干净部署 Validate 与 Publish 各通过 46 项 Windows SWE 基础设施检查，模型 evaluator 保持禁用；九题、qualification、依赖安装、elevated sandbox 和外部 Verifier 均未运行。
- 发布只证明受管文件已安装；Codex 在任务启动时构建指令链，当前已启动任务不会追溯加载新角色。真实分流行为需在新任务观察。

## 下个对话的最小恢复步骤

1. 读取根 `README.md` 与本文件，运行 `git status --short`；保留上述 Windows SWE、共享 runtime、规则和 requirements dirty 边界，不清理、不回退、不并入无关提交。
2. 若上述实现链及本文件所在提交已在私有上游，本子计划没有开放源码实施项；不要因缺少新任务行为观察而自动重开。
3. 任务依赖真实安装状态时，只读运行部署说明中的 `DirectCompatibility + InstallPortableSettings Status`；当前预期为 `published:true`，不得从安装副本反推项目真源。
4. 在新任务观察三路分流、`operator` 代表项/首异常停止、无收益委派和主代理接纳；真实反例再按[完成审计](work/20260826_operator_subagent/completion-audit.md)重开。
5. Windows SWE sandbox 仍是独立评测工作边界；普通验证不得初始化 elevated sandbox、克隆题目、安装依赖、运行 qualification 或启动候选模型。
6. 本次 Publish 授权已经消耗；任何后续正式发布都必须重新取得当次明确同意。
