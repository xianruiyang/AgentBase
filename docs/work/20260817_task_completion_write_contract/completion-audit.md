# Task completion 写入合同完成审计

## 审计结论

本子计划已在 `task-table-manager/taskctl complete` 的唯一写入边界闭合：模型只编写完成结果语义正文，CLI 以命令目标、task/state 双 CAS 和来源收据生成单一永久机器结果；显式收据身份异常在任何结果或状态写入前阻断。历史结果后来失去资产仍只诊断并保持可读，上一版完整输入和内联快照通过同一入口单向规范化，没有建立第二 schema、第二状态源或第二写入入口。

这是一项仓库开发完成结论，不表示当前 Codex 运行已经加载。未执行插件迁移、猜测式快照回收或 Codex 发布。

## 目标与证据

| 对象 | 直接证据 | 结论 |
| --- | --- | --- |
| REQ-001、AC-001 | 新语义输入测试；永久结果由 `--id` 与 `--expected-task-revision` 注入身份和执行版本 | satisfied |
| AC-002 | machine 历史读取、show/completion-context 与 82 项 taskctl 回归继续消费完整 `task.result` | satisfied |
| AC-003 | 缺失、无效、身份不匹配三类收据均返回结构化写前门禁；缺收据、覆盖不足、陈旧仍诊断 | satisfied |
| AC-004 | 上一版 envelope、内联输入、历史内联结果和写后资产丢失场景通过 | satisfied |
| AC-005 | task/state CAS、收据门禁和冲突恢复场景逐项确认状态与结果目录不变 | satisfied |
| UDES-001、UDES-002 | 模型修改面、机器永久面、兼容、诊断和 Delivery Workflow 消费者分别验证 | satisfied |
| CON-001 | 没有 Publish、插件迁移或快照 GC | satisfied |

## Owner、消费者与旧路径

| 对象 | 裁决 |
| --- | --- |
| `taskctl complete` | 唯一合成模型语义、任务身份、执行 revision、状态 revision 和来源收据的正式入口 |
| 模型结果文件 | 只持有完成结果语义；不再持有机器 envelope 或来源快照字段 |
| `results/*.json` | 保持唯一完整 `task.result`，由查询、历史和 machine 消费者读取 |
| 上一版完整输入 | 作为已发布输入合同的真实兼容对象由 `complete` 校验和规范化，并返回迁移诊断 |
| 历史结果 | 不迁移、不改写；资产异常在读取时隔离诊断 |
| Delivery Workflow | 35 项回归证明任务状态、永久结果与诊断摘要消费未退化；未复制 completion 写入语义 |

## 完成边界与后继

[验证记录](verification.md)覆盖直接行为、同类变体、相近非触发场景、兼容和消费者。当前子计划没有已知适用失败。

后继审计已发现 `taskctl add/update` 的模型输入仍要求 `schema` 和 `revision`，且 update 的任务身份仍藏在永久 envelope 中；这属于同一根需求下的独立任务合同 authoring 边界，不回写本子计划的 completion 目标。它应由 Task Table Manager 继续以语义输入、命令身份、单一永久记录和真实上一版兼容闭合。任何最终候选发布仍需刷新独立评估并取得当次明确同意。
