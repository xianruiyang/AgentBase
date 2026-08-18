# AgentBase 当前接手状态

状态截点：2026-08-19 Agent 档位与验证尝试生命周期闭环并发布（Asia/Shanghai）

## 一句话状态

`main` 与 `origin/main` 仍停在 `afd6ad8`；当前 dirty worktree 已完成 Luna/max、Sol/medium、Terra 退役和路由尝试 Begin/Finish 有界账本实现、验证及真实 Codex 发布，但尚未提交或同步。

## 仓库与发布状态

- 当前分支为 `main`，`HEAD` 与 `origin/main` 均为 `afd6ad8`；本轮源码、测试和交付文档构成一组未提交改动，不能把该 HEAD 当作当前完整源码。
- 2026-08-19 最新真实 Codex 发布使用 `DirectCompatibility + InstallPortableSettings`，改变 3 个受管理项，退役 `agents\terra.toml`；回滚备份为 `C:\Users\gzxt\.codex\backups\AgentBase-20260819-001202-f1169bf2`。
- 发布后同范围只读 `Status` 返回 `published:true`，当前候选已安装。
- 独立 `srcq` 安装仍为 0.3.1；新版本构建、安装和插件迁移继续延后。
- 上一次 Publish 授权已经消耗；任何再次 Publish 必须取得用户针对那一次操作的明确同意，Git 同步不能替代。

## 当前源码能力

- 默认 spawned agent 为 Luna/max；`global/agents/luna.toml` 显式固定 `max`，`global/agents/sol.toml` 显式固定 `medium`。
- `global/agents/terra.toml` 已从候选删除，`agent:terra` 由部署生命周期标记 retired；下一次获授权的 portable-settings 发布会备份并删除旧受管副本，不触碰无关个人代理。
- 正式路由评估必须在 evaluator 前调用 `record_routing_attempt.ps1 -Action Begin`，随后用同一 attempt ID `Finish` 为通过、结果失败或执行失败闭环；未完成 started 收据阻断 Validate/Publish。
- `evidence/attempts.json` 只保留一个活跃周期，最多 6 份收据；每个不变输入最多两次且第二次需要理由，周期轮换通过上一周期 ID、账本哈希和收据数链接 Git 历史。
- taskctl、skill description、全局规则和 srcq 仍保持上一轮已闭环能力，本轮没有改变其正式语义。

## 验证边界

- portable-agent 合同、路由尝试历史、managed-asset lifecycle 和完整部署回归均通过。
- `validate_contract.ps1`：93 cases、52 strict routing、10 strict references，11/11 skill 具有正向与非触发覆盖。
- 当前路由尝试账本：schema 2，活跃周期 3/6 收据，无未完成尝试，每个不变输入最多两次。
- 最终部署 `Validate` 返回 `valid:true`；正式 Publish 与发布后 Status 均返回 `published:true`。
- 详细目标、首次部署回归失败的归因、修正和完成边界见 `docs/work/20260819_agent_attempt_lifecycle/verification.md` 与 `completion-audit.md`。

## 下个对话的最小恢复步骤

1. 读取根 `README.md` 和本文件，运行 `git status --short`；先把当前 dirty worktree 视为本轮完整候选，不回退或用 `afd6ad8` 覆盖。
2. 当前没有开放实施项。只有需要选择、替代或重开子计划时读取 `docs/plan.md`；普通组件工作从 README 定位 owner。
3. 任务依赖真实安装状态时，按部署说明只读核对 `DirectCompatibility + InstallPortableSettings Status`；当前已知为 `published:true`。
4. 安装、插件迁移与 srcq 新版本继续延后；任何再次 Publish 都必须重新取得针对当次操作的明确同意。
