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
