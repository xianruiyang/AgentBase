# Task 合同 authoring 交互面验证

## 验证结果

- Task Table Manager：84 项回归通过。
- Delivery Workflow：35 项回归通过。
- Python 语法：`taskctl.py` 与 `test_taskctl.py` 通过 `py_compile`。
- 静态合同：76 个场景、34 个严格路由、5 个严格引用和 11/11 skill 正反向覆盖通过。

行为场景覆盖：

- 新 add/update 输入只包含稳定任务 ID 和语义正文；永久 `tasks/*.json` 仍注入 `task.record` 与正确 revision。
- 语义 add 固定 revision 1，语义 update 在 CAS 后写入 `current + 1`。
- 默认 model draft 保留 ID 与语义字段并省略 schema/revision；显式 machine draft 仍返回完整、可直接程序消费的 canonical JSON。
- 上一版完整 task envelope 在 add/update 中继续规范化并返回迁移诊断；非初始旧式 add revision 仍按上一版保存并诊断。
- 只混入 schema/revision 等部分机器字段的输入被拒绝，任务和状态目录不产生记录。
- 匹配的部分 task 写入仍可恢复，CAS、任务语义诊断、历史永久任务、状态、结果和查询行为未退化。

## Token 证据

使用本机 `tiktoken 0.13.0`、`o200k_base` 对同一任务正文比较：语义 compact JSON 111 tokens，上一版完整 compact JSON 120，语义 pretty JSON 174。移除 schema/revision 的主要价值是职责和修改正确性；当前样本的直接节省为 9 tokens，不把它夸大成固定压缩收益。默认 model draft 还会省略空值并使用既有 HJSON 风格 renderer，machine 仍保持完整 JSON。

## 边界

本轮未刷新 detached Routing、Policy、References evidence，未运行部署 `Validate` 或 Codex `Publish`。后续最终候选如需发布，必须基于全部累计改动刷新独立证据并取得当次明确同意。
