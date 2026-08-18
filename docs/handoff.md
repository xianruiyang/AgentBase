# AgentBase 当前接手状态

状态截点：2026-08-18 验证溯源、CLI 帮助与 Git 基线闭环并同步，当前源码未再次发布（Asia/Shanghai）

## 一句话状态

`main` 与 `origin/main` 已同步，核心实现提交为 `5814dca`；Agent/Skill/CLI 候选及验证失败尝试合同均已进入 Git，当前没有开放实施项。真实 Codex 仍是本轮源码改进前的 `DirectCompatibility + InstallPortableSettings` 发布，不能把此前 `published:true` 外推到当前源码。

## 仓库与发布状态

- 当前分支为 `main`，核心实现提交 `5814dca` 已非强制推送到私有 `origin/main`；状态文档由其后续文档提交维护，正常接手时工作区应为 clean。
- “Agent 与 Skill 指令面收敛”与“验证溯源、CLI 帮助与 Git 基线”均已闭环；各自的验证和完成审计是最小恢复入口，总计划只维护索引与重开条件。
- 2026-08-18 上一次真实 Codex 发布使用 `DirectCompatibility + InstallPortableSettings`，改变 18 个受管理项，回滚备份为 `C:\Users\gzxt\.codex\backups\AgentBase-20260818-180544-7f1850ae`。
- 本轮增加验证尝试合同和 taskctl 二级帮助后，只读 `Status` 返回 `published:false`，缺口为 `installed_payload_differs_from_source` 与 `published_manifest_source_is_stale`；没有再次运行 Publish。
- 独立 `srcq` 安装仍为 0.3.1；新版本构建、安装和插件迁移继续延后。
- 上一次 Publish 授权已经消耗；任何再次 Publish 必须取得用户针对那一次操作的明确同意，Git 同步不能替代。

## 当前源码能力

- Luna、Terra、Sol 使用中文角色语义与明确升级边界；角色正文只由 `global/agents/*.toml` 维护，部署 validator 不复制正文。
- taskctl 协议拆为共享入口与 authoring、query、execution、completion 四个动作族；全部子命令参数具有中文职责说明，复杂上下文与完成命令包含最小示例。
- 正式路由 merge 通过唯一登记入口维护有界尝试收据：失败保留分类，相同 phase/candidate/input/capsule 的新 evaluator 运行必须显式说明理由且至多一次，完全相同的通过结果只幂等复用。
- 当前三阶段 evidence 以三份 `baseline_import` 收据接入 `evidence/attempts.json`，明确声明更早失败尝试没有被重建；后续正式尝试才受完整新合同覆盖。
- skill description 与案例合同已收紧需求校准、QQ 根因协同、任务状态更新、固定推理档位和最终复核边界；`global/config.toml` 的 Luna/max 默认值没有改变。

## 验证边界

- `validate_contract.ps1`：93 cases、52 strict routing、10 strict references，11/11 skill 具有正向与非触发覆盖。
- detached evidence：Routing 93/93、Policy 93/93、References 26/26；candidate bundle `F29BEE77353CCB144A6DAD5EBE9EC054A72D8A7116ADC175ECEA1740C09A1836`。
- 路由尝试历史测试覆盖 baseline、失败收据、同输入理由、两次上限、幂等复用、正式 merge 和跨阶段 evaluator 身份；当前历史为 3 份通过 baseline 收据。
- Task Table Manager 92/92；部署 Validate、部署回归、custom agent 合同、路由 capsule/fingerprint、PowerShell 语法、插件构建和差异检查均通过。
- 未执行 custom agent 的真实宿主质量与成本比较；这仍是改变默认 Luna/max 前的证据边界。

## 下个对话的最小恢复步骤

1. 读取根 `README.md` 和本文件，运行 `git status --short`；若出现 dirty 内容，先确认其归属，不把任何旧 HEAD 当成当前完整源码。
2. 当前没有开放实施项。只有需要选择、替代或重开子计划时读取 `docs/plan.md`；普通组件工作从 README 定位 owner。
3. 任务依赖真实安装状态时，按部署说明只读核对 `DirectCompatibility + InstallPortableSettings Status`。当前源码尚未再次发布。
4. 安装、插件迁移与 srcq 新版本继续延后；任何再次 Publish 都必须重新取得针对当次操作的明确同意。
