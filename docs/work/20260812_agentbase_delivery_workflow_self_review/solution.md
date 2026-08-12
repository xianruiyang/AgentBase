# AgentBase 交付链自审与改进：方案设计

## SOL-001 收敛 taskctl 的任务存储与即时诊断职责

- 状态: confirmed
- 解决: GAP-003, GAP-004, GAP-005, GAP-006, GAP-008
- 满足: DES-003, DES-004, DES-005
- 依赖: 无
- 风险: 任务状态与结果校验变严格，必须用反例测试区分损坏记录与允许的软诊断
- 验证: taskctl 单元测试覆盖 manifest 身份、add/update 诊断、备注清空、release、历史 revision 和既有完整流程

在 `taskctl` 提供唯一的严格任务存储摘要函数，并让其自身 `status` 复用；绑定 workflow/task-table ID；让 `add/update` 在写入前验证诊断所依赖的完整存储集合，成功写入后立即返回上游与合同软诊断；修正确定性状态边界并限制明显超前的结果历史文件。依赖未完成、上游未决或语义不足仍不阻止保存和执行。

## SOL-002 让 workctl 的公开命令和组合摘要忠实于真实动作

- 状态: confirmed
- 解决: GAP-001, GAP-002, GAP-003, GAP-004
- 满足: DES-002, DES-003, DES-005
- 依赖: SOL-001 提供的严格任务摘要职责
- 风险: 动态加载兄弟 skill 失败时必须给出有界、可理解的错误，不得静默退回弱统计
- 验证: workctl 单元测试覆盖初始化返回值、公开阶段名、统一 work-dir、跨 manifest 身份和孤立状态反例

`init` 分开返回真实 `created` 与后续 `pending` 产物；`outline` 使用带连字符的公开阶段名并遵循统一工作区参数；`status/render` 调用 `taskctl` 的严格摘要而不再复制任务解析；两个工具都校验 task table 属于当前 workflow。

## SOL-003 用真实闭环验证并交付本轮改进

- 状态: confirmed
- 解决: GAP-001, GAP-002, GAP-003, GAP-004, GAP-005, GAP-006, GAP-007, GAP-008
- 满足: DES-001, DES-002, DES-003, DES-004, DES-005, AC-001, AC-003
- 依赖: SOL-001, SOL-002, SOL-004
- 风险: skill 正文或路由候选变化会使已有盲测证据失效；只在实际触发语义变化时更新候选并重做独立评估
- 验证: 本工作区任务结果、workctl/taskctl 回归、路由合同、部署合同、插件校验、最终 completion-context 与 Git 同步读回

使用本工作区的 `taskctl` 建立、领取、执行和完成任务；可修订阶段随新证据更新。最后重建索引，以同一快照遍历受保护目标、约束和延后项，逐项核对直接证据后再提交并普通推送。

## SOL-004 排除交付工作区的可重建缓存

- 状态: confirmed
- 解决: GAP-007
- 满足: DES-001, DES-005, AC-003
- 依赖: 无
- 风险: 忽略规则必须只覆盖 `.work-cache` 目录，不能隐藏受保护基线、阶段文档、任务、状态或结果
- 验证: `git check-ignore` 命中 `.work-cache/index.json`，而 `protected-baseline.json`、`tasks/*.json`、`state/*.json` 和 `results/*.json` 不命中

在项目根 `.gitignore` 增加任意交付工作区的 `**/.work-cache/`，保留全部语义与执行真源可跟踪。
