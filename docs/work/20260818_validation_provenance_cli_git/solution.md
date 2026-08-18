# 验证溯源、CLI 帮助与 Git 基线：方案

## SOL-001 增加有界正式尝试收据

- 状态: confirmed
- 解决: GAP-001
- 关联: DES-001

在 `development/skill-routing` 增加尝试记录、结构验证、baseline 初始化和回归测试；正式 merge 逐阶段登记，失败保留分类摘要，相同输入只有一次带理由的重试。部署 Validate 要求当前三阶段成功证据各有唯一通过收据。现有证据只导入三份明确标记的 baseline，不伪造此前失败历史。

## SOL-002 完成 taskctl 二级帮助

- 状态: confirmed
- 解决: GAP-002
- 关联: DES-002

在 parser 唯一 owner 中为通用参数和全部子命令参数加入中文帮助，并为三个复杂上下文/完成命令加入最小示例。通过真实 help 输出与 parser 结构测试固定完整性，不改变命令、存储或 machine 输出。

## SOL-003 形成并同步单一源码提交

- 状态: confirmed
- 解决: GAP-003
- 关联: DES-003
- 依赖: SOL-001, SOL-002

完成受影响验证和跨契约审计后检查全部 dirty 差异，形成覆盖上一轮候选、本轮验证溯源、CLI 帮助及完成证据的职责清晰提交；确认上游没有无法裁决的新历史后执行非强制推送。本方案不运行 Codex Publish。
