# 方案

## SOL-001 收敛角色与部署生命周期

- 状态: implemented
- 解决: GAP-001
- 关联: DES-001, REQ-001

把默认子代理改为 Luna/max，在 Luna 与 Sol 文件中分别显式声明 `max`、`medium`，删除 Terra 候选并登记退役生命周期；同步部署说明、portable validator 和部署回归消费者。

## SOL-002 建立 Begin/Finish 唯一入口

- 状态: implemented
- 解决: GAP-002
- 关联: DES-002, REQ-002

把记录器改为 `Begin|Finish` 两阶段入口，先持久化 started 再运行 evaluator；Finish 同时覆盖结果通过、结果失败和执行失败。merge 绑定三份已通过 attempt ID，正式 validator 阻断未完成收据。

## SOL-003 轮换有界活跃账本

- 状态: implemented
- 解决: GAP-003
- 关联: DES-003, AC-005

把账本升级到 schema 2，一个活跃周期最多六份收据；新周期写入前检查旧周期没有 started，并保存旧周期 ID、文件哈希与收据数。迁移脚本通过同一 Begin/Finish 入口导入当前三份 baseline。

## SOL-004 迁移为 evidence/experiment 语义角色

- 状态: implemented
- 解决: GAP-004
- 关联: DES-004, DES-005, REQ-003

用 `evidence` 的 Luna/medium 与 `experiment` 的 Sol/low 替代模型名角色；把未分类子代理回退降为 Luna/medium。全局内核只保存角色选择与主代理责任，新的 `subagent-orchestration` 用渐进引用保存 evidence packet、实验生命周期与成本交接；validator 只校验 schema 和安全边界。部署生命周期把旧 Luna/Sol 声明为退役并安装两个新角色，路由分别覆盖真实取证、路径实验和概念讨论非触发。

## SOL-005 以 should 默认请求闭合 Codex 触发语义

- 状态: implemented
- 解决: GAP-005
- 关联: DES-004, DES-005, REQ-003, AC-010

把全局委派规则从只表达必要条件的 `must` 许可句改为 `should` 默认请求：用户未指定时，必要取证或试路的独立边界与委派净收益同时成立则使用语义角色，否则主代理直接完成。编排 skill 的 description、正文、成本交接和 UI 提示同步支持用户显式要求与这一默认选择，并把并发限制为多个分别合格、无共享未证前提或可写状态且并发净收益成立的子问题。

## SOL-006 扩展 Experiment 到有信息增益的可逆操作

- 状态: implemented
- 解决: GAP-006
- 关联: DES-006, REQ-003, AC-007, AC-009, AC-010, AC-011

把全局内核、`experiment.toml`、编排 skill、实验生命周期与成本交接统一改为可逆操作的信息增益判定：已有方向下的路径确认、错误暴露、真实约束和连续遮蔽问题都可触发，不再要求先有 evidence ID 或穷尽静态分析，也不因整体工作最终需要正式实现而排除。保留独立有界、恢复依据、净收益、主代理生产裁决和一次便宜闭环不委派的边界，并用正反路由用例固定这一语义。
