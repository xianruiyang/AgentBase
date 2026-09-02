# Workflow CLI 运行时与模型输入输出：现状

## OBS-001 两套 CLI 的可执行源码仍由 skill 目录持有

- 状态: confirmed
- 来源: `skills/delivery-workflow/scripts/workctl.py`、`skills/task-table-manager/scripts/taskctl.py` 及两项 SKILL/tooling
- 可证明上限: 当前仓库源码与消费者合同

模型必须先定位 skill 安装目录再调用 Python 脚本；两套 CLI 没有独立版本、PATH、安装状态或回滚 owner。skill 部署和 CLI 运行时因此耦合，不能单独验证主机安装身份。

## OBS-002 taskctl model 路径暴露完整内容身份

- 状态: confirmed
- 来源: `task_completion_model`、`context_model_receipt_candidate`、`fit_task_model_with_snapshot` 与对应测试/说明
- 可证明上限: completion-context、context capture 和低预算 model 投影

completion-context 把完整 SHA-256 snapshot ID 放入首页和续页参数；context capture 把完整内容寻址来源 ref 放入 model 收据；低预算兜底仍保留 snapshot ID，并建议模型切到 machine 视图。现有测试把这些长身份当成预期合同。

## OBS-003 workctl model 路径仍投影机器来源与 machine 兜底

- 状态: confirmed
- 来源: `protected_baseline_issue`、`work_protect_model`、`fit_work_model` 与 tooling
- 可证明上限: protect/baseline 和低预算恢复投影

确认引用是无约束文本并直接进入 model 输出，可能携带 UUID、哈希或其他长机器标识；低预算恢复建议改用完整 machine 视图。错误与部分诊断还可能直接携带绝对路径或原始异常文本。

## GAP-001 缺少独立 CLI 运行时与主机身份闭环

- 状态: confirmed
- 关联: REQ-001, DES-001, DES-004, OBS-001

当前无法通过一个正式主机入口证明用户调用的 workctl/taskctl 来自当前项目候选，也不能在不部署 skill 的情况下升级或回滚工具。

## GAP-002 模型恢复协议违反当前交互面规则

- 状态: confirmed
- 关联: REQ-002, DES-002, DES-003, OBS-002, OBS-003

完整机器身份直接进入模型上下文和下一次模型生成；删除字段会破坏分页或完成收据，因此必须由 CLI 提供真实可解析短句柄，而不是只缩短显示文本。
