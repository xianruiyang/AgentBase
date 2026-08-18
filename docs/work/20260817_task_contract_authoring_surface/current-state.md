# Task 合同 authoring 交互面现状

## OBS-001 add/update 输入要求模型维护 schema 和 revision

- 状态: confirmed
- 关联: AC-001, AC-002, DES-001, DES-002

`validate_task` 要求输入包含 `schema == task.record`、稳定 `id` 和正整数 `revision`。`add` 直接保存该 revision；`update` 随后又用当前永久记录的 revision 加一覆盖输入值，因此 update 输入中的 revision 没有语义职责。

## OBS-002 默认 draft 暴露永久机器字段

- 状态: confirmed
- 关联: AC-003, DES-003

`command_draft` 构造完整 task.record，通用 model 投影没有 draft 专用规则，因此默认输出继续包含 schema/revision；正式 tooling 还要求模型为直接保存 JSON 使用 machine 视图，把完整永久 envelope 带回模型修改面。

## OBS-003 稳定 task ID 具有真实语义消费者

- 状态: confirmed
- 关联: AC-001, DES-001

任务 ID 被依赖边、state、result、查询和上游条目关系实际引用；从 authoring 文件删除 ID 会迫使命令和文件维护另一同步关系，不能把它与 schema/revision 一并视为冗余。

## OBS-004 仓库消费者集中在正式入口与回归

- 状态: confirmed
- 关联: AC-004, DES-002

仓库内任务新增和更新通过 `taskctl` 及其测试执行；永久 `tasks/*.json` 被全部历史工作区、查询、状态和结果消费者读取。没有第二 authoring 工具，但当前已发布完整输入是需要单向兼容的真实对象。

## GAP-001 模型任务正文仍混入机器生命周期字段

- 状态: confirmed
- 关联: REQ-001, AC-001, AC-003, OBS-001, OBS-002

模型创建和更新任务时仍需复制 schema/revision，默认 draft 还主动返回它们；这与 completion 已修正的消费者分层原则不一致。

## GAP-002 兼容输入和新 authoring 输入未分层

- 状态: confirmed
- 关联: AC-004, OBS-004

完整永久记录既承担历史兼容又被当作新模型输入，没有明确的一次规范化边界。
