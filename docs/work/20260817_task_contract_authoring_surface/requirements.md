# Task 合同 authoring 交互面需求

## REQ-001 模型只维护任务合同语义

- 状态: confirmed
- 来源: 用户要求模型直接读取和修改的内容采用最小充分设计，程序表示保持完整
- 关联: AC-001, AC-002, AC-003, AC-004

模型创建或更新任务时只维护稳定任务 ID、交付语义、真实依赖、修改范围、产出、验证和执行提示；永久 schema 与 revision 生命周期由 `taskctl` 写入入口负责。

## AC-001 新 authoring 输入不包含机器 schema 和 revision

- 状态: confirmed
- 来源: REQ-001
- 关联: REQ-001

`add/update --file` 的新模型输入不要求 `schema` 或 `revision`。稳定 `id` 仍属于模型任务合同，因为它被依赖、状态、结果和上游关系引用；update 的并发前提只通过 `--expected-task-revision` 表达。

## AC-002 永久任务记录保持完整单一格式

- 状态: confirmed
- 来源: REQ-001
- 关联: REQ-001

`add` 注入 `task.record` 和初始 revision，`update` 在 CAS 成功后注入下一 revision；`tasks/<ID>.json`、machine 查询、状态与结果消费者继续只使用一种完整永久格式。

## AC-003 draft 按消费者返回适用表示

- 状态: confirmed
- 来源: REQ-001
- 关联: REQ-001

默认 model draft 只显示可供模型检查和写入的任务语义，不显示 schema/revision；显式 machine draft 保持完整、稳定且可直接作为程序的永久记录候选。

## AC-004 已发布上一版输入单向兼容

- 状态: confirmed
- 来源: 项目迁移与唯一入口约束
- 关联: REQ-001

完整 `task.record` add/update 输入仍由相同入口校验并规范化，返回迁移诊断；兼容不产生第二种永久记录或第二写入口。部分字段混合不得被静默接受为新语义输入。

## CON-001 本轮边界

- 状态: confirmed
- 来源: 用户授权持续开发；Codex 发布仍需当次明确同意
- 关联: REQ-001

只修改 Task Table Manager authoring owner、正式合同、测试和直接消费者，不执行 Codex 发布、插件迁移或无证据的其他格式迁移。
