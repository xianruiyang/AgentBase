# workctl 模型回执投影需求

## REQ-001 交付辅助命令按当前消费者返回事实

- 状态: confirmed
- 来源: 用户要求模型直接读取的工具输出只保留当前动作需要的信息
- 关联: AC-001, AC-002, AC-003

workctl 的 model 视图必须从当前 canonical 命令事实派生，准确表达保护快照状态、写入回执和影响查询，不复制机器细节、默认成功值或同一诊断。

## AC-001 保护快照使用当前 status 合同

- 状态: confirmed
- 来源: REQ-001
- 关联: REQ-001

model 视图读取 `protected_baseline.status`，异常时返回 status、当前周期和确认来源；不得依赖永久合同中不存在的 `aligned`。同一 baseline 诊断在一个响应中只出现一次。

## AC-002 protect/render 只返回动作回执

- 状态: confirmed
- 来源: REQ-001
- 关联: REQ-001

`protect` 返回保护状态、周期、确认来源和覆盖计数，不返回快照路径、历史计数、文档指纹或完整机器资产。`render` 返回输出路径并复用 `status` 的稀疏摘要，不另行展开完整机器 summary。

## AC-003 impact 只在截断时返回额外总数

- 状态: confirmed
- 来源: REQ-001
- 关联: REQ-001

完整可见的 affected 列表不再重复其长度；发生 `--max-items` 截断时必须保留总数与截断标志，支持扩大范围恢复。

## CON-001 本轮边界

- 状态: confirmed
- 来源: 当前持续开发授权与单次发布限制
- 关联: REQ-001

只修改 Delivery Workflow model projection、合同、测试与项目记录；阶段 Markdown、machine 输出、保护快照、索引、生成视图和 Codex 安装不改变。
