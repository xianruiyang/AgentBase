# Task completion 写入合同验证

## 行为验证

- Task Table Manager：`python -m unittest skills/task-table-manager/tests/test_taskctl.py`，82 项通过。
- Delivery Workflow：`python -m unittest skills/delivery-workflow/tests/test_workctl.py`，35 项通过。
- Python 语法：`taskctl.py` 与 `test_taskctl.py` 通过 `py_compile`。
- 静态合同：`development/skill-routing/validate_contract.ps1` 通过 76 个场景、34 个严格路由、5 个严格引用和 11/11 skill 正反向覆盖。

直接场景覆盖：

- 新语义结果输入省略 `schema/task_id/task_revision/source_snapshot/source_snapshot_ref`，永久结果仍由工具生成完整 `task.result`。
- `complete` 缺少或错用 task revision、缺少或错用 state revision时返回 `TASK-REVISION`，结果目录和状态文件不变。
- 有效收据可以写入；资产缺失、JSON 不可读和内容身份不匹配均在写前返回 `TASK-INPUT-UNREADABLE`，结果和状态零变化。
- 正常完成后再删除快照资产，`show/status/context` 仍保留历史结果并返回资产缺失诊断。
- 上一版完整结果 envelope、内联快照、历史内联结果和部分写恢复继续通过唯一入口或读取器工作；新永久结果只保存引用。
- 缺收据、来源覆盖不完整和逐来源陈旧仍为诊断，没有被错误提升为产品完成门禁。

## 模型输入成本

使用本机 `tiktoken 0.13.0`、`o200k_base` 对同一真实结果正文比较：语义 compact JSON 为 69 tokens，上一版完整 compact JSON 为 85，语义 pretty JSON 为 113，等价 HJSON 风格候选为 62。当前选择先移除机器字段并使用标准 JSON 输入：相对上一版减少 16 tokens，HJSON 只再减少 7 tokens，不足以抵消新增解析依赖、格式合同和错误边界；文档允许省略空列表，模型无需生成 pretty envelope。该数字只证明本场景的相对成本，不设固定比例。

## 验证边界

本轮没有刷新 detached Routing、Policy、References evidence，也没有运行部署 `Validate` 或 Codex `Publish`。静态合同通过只证明仓库候选的规则结构与路由关系；任何后续正式发布仍须先按最终候选刷新独立证据，并取得用户针对该次发布的明确同意。
