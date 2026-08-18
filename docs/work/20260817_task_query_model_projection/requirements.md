# Task 查询模型投影需求

## REQ-001 查询输出保留结论而非机器包装

- 状态: confirmed
- 来源: 用户要求模型阅读面使用最小充分表示，同时不能片面删除改变结论的信息
- 关联: AC-001, AC-002, AC-003, AC-004

`show/list/deps/dependents/next/impact` 的默认 model 输出只保留当前查询的任务语义、状态、结果、关系、非零摘要、异常和分页恢复；machine 视图继续返回完整稳定 JSON。

## AC-001 show 不复制 record envelope

- 状态: confirmed
- 来源: REQ-001
- 关联: REQ-001

顶层任务 ID 只出现一次；task/state/result 中省略 schema 与重复 task ID。task/state revision、结果 task revision、结果引用、语义正文、诊断和来源收据摘要继续可见。`current_for_task_revision:true` 由 revision 一致性直接推出而省略，false 仍保留。

## AC-002 列表与关系分页只在需要时返回总数

- 状态: confirmed
- 来源: REQ-001
- 关联: REQ-001

完整可见的非空列表不重复其长度，也不返回 `truncated:false` 或零诊断计数；截断时返回总数和精确 `after_id`。过滤或续页产生空页时保留 matched/dependency/dependent 的数值结论。

## AC-003 语义零不得误删

- 状态: confirmed
- 来源: REQ-001
- 关联: REQ-001

“没有依赖”“没有候选”等零值会改变模型动作，必须明确返回；写入成功场景中的零诊断和 false 恢复标志仍属于默认值并省略。

## AC-004 impact 正式入口可执行且可分页

- 状态: confirmed
- 来源: 真实工作区复现
- 关联: REQ-001

`impact` 作为递归 dependents 正式入口必须注册其 handler 读取的分页参数，默认调用和 `--after-id` 续页均不得因 Namespace 缺字段崩溃。

## CON-001 本轮边界

- 状态: confirmed
- 来源: 当前持续开发授权与单次发布限制
- 关联: REQ-001

只修改 taskctl 查询 model projection、impact 参数合同、测试与正式说明；不改变任务永久格式、machine 字段、图算法、source snapshot 表示或 Codex 安装。
