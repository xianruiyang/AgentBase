# Task 合同 authoring 交互面完成审计

## 审计结论

本子计划已在 Task Table Manager 的正式 add/update/draft owner 闭合：模型 authoring 文件保留稳定任务 ID 与交付语义，不再维护 schema/revision；工具生成唯一完整永久 `task.record` 并拥有 revision 生命周期。默认 draft 与 machine draft 从同一 canonical 任务派生，分别服务模型检查和程序解析。上一版完整输入只在同一写入口单向规范化，没有第二任务格式或第二入口。

## 目标覆盖

| 对象 | 直接证据 | 结论 |
| --- | --- | --- |
| REQ-001、AC-001 | 常规 add/update 测试输入不含 schema/revision，永久文件读回完整 | satisfied |
| AC-002 | add revision 1、update revision 2、历史任务读取和 84 项回归 | satisfied |
| AC-003 | 同一 draft 的默认 model 省略机器字段，machine 保持完整 canonical | satisfied |
| AC-004 | 上一版 add/update envelope、非初始 revision、部分写恢复和混合输入拒绝场景 | satisfied |
| UDES-001、DES-001—DES-004 | ID 语义消费者保留，schema/revision owner、CAS、兼容与 renderer 分层均验证 | satisfied |
| CON-001 | 未执行 Publish、插件迁移或其他无证据格式迁移 | satisfied |

## 影响闭合

| 消费者 | 裁决 |
| --- | --- |
| 模型 authoring | 默认 draft 与新 JSON 输入只承担语义；空字段可省略 |
| `taskctl add/update` | 唯一规范化、revision、原子写入和 CAS owner |
| `tasks/*.json` 与 machine draft | 继续使用完整 `task.record`，无 schema 变化 |
| state/result/query/workctl | 继续读取永久 task 记录；35 项 Delivery Workflow 回归通过 |
| 上一版完整输入 | 自动识别、校验、规范化并诊断，不成为新 authoring 合同 |

## 完成边界

[验证记录](verification.md)覆盖原场景、同类变体、相近非触发场景、兼容和直接消费者；当前子计划没有已知适用失败。该结论不证明其他 owner 的模型交互面已经最优，后继审计仍需以真实读取或修改责任逐项裁决。没有执行正式发布；以后每次 Codex Publish 仍需用户当次明确同意。
