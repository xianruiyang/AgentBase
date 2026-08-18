# Agent 与 Skill 指令面收敛：方案

## SOL-001 让 custom agent 真源只维护中文角色差异

- 状态: confirmed
- 解决: GAP-001
- 满足: AC-006, CON-002

由 `global/agents/*.toml` 唯一维护角色自然语言语义：Luna 只承接边界明确的窄任务并在关键歧义或跨模块职责出现时返回升级理由；Terra 承接需要有限探索的常规分析与实现，并在深度根因或跨契约裁决出现时升级；Sol 承接高歧义、多步骤、跨模块根因、架构和验证任务。三者不重复全局证据、授权和交付规则。

部署 validator 只验证固定文件集合、文件名与 name/model 身份、必要字段、单一结构、中文自然语言、非空且彼此可区分的角色说明，以及机器路径、外部依赖和敏感信息边界；不再复制 description 或 developer instructions 正文。

## SOL-002 按 taskctl 动作族选择条件引用

- 状态: confirmed
- 解决: GAP-002
- 满足: AC-007, AC-041

保留最小共享 `tooling.md`，只维护所有 taskctl 调用都需要的入口、model/machine 消费者边界和共享机械门禁；其余协议拆为：

- `authoring-tooling.md`：`init/draft/add/update`；
- `query-tooling.md`：`show/list/deps/dependents/impact/next/status/render`；
- `execution-tooling.md`：`context --capture`、状态命令、结果提交与来源快照；
- `completion-tooling.md`：`completion-context` 的证据目录、诊断和快照分页。

`SKILL.md` 在实际使用 CLI 时读取共享入口，并只增加当前命令族对应引用；一个请求跨命令族时才组合。既有机器合同、模型投影、永久存储和门禁语义不变。

## SOL-003 让条件引用评估消费 Task Table Manager

- 状态: confirmed
- 解决: GAP-002
- 满足: AC-007

把 `task-table-manager` 加入既有 References 阶段候选，新增或收紧 authoring、查询、执行和最终复核用例，使独立 evaluator 能证明当前动作选中必要引用且不加载其他命令族。静态合同验证所有新引用存在，并把原来只检查统一 tooling 的断言迁移到各自正式 owner。

## SOL-004 补齐 taskctl 顶层帮助但不改变命令身份

- 状态: confirmed
- 解决: GAP-003
- 满足: AC-041

为每个 argparse 子命令增加一句中文用途，明确 `next` 只是候选建议、`completion-context` 用于最终证据复核、写命令记录模型判断且 CAS 保护并发。保留现有命令名、参数、stdout 视图和退出行为，避免为说明改进制造 CLI 迁移。

## SOL-005 保留默认子代理设置并限定未知项

- 状态: confirmed
- 解决: GAP-004
- 满足: CON-001

本轮不改变 `global/config.toml` 的 Luna/max 默认值。源码与静态合同完善只能证明角色语义和唯一 owner；真实路由质量、结果质量与成本需要在候选发布后由新任务或独立运行比较，未取得前不把偏好写成配置结论。

## 验证设计

- Agent：部署 validator 和回归测试覆盖结构、身份、中文语义、角色差异、正文可独立修改及敏感边界。
- Skill：`validate_contract.ps1` 覆盖引用存在、owner 分配和条件路由合同；Task Table Manager CLI 完整回归保持行为不变。
- CLI：新增帮助测试，确认所有子命令可发现且关键用途文本存在。
- 独立证据：修改 skill 正文和 References oracle 后，当前 routing evidence 必然过期；刷新前只报告静态与组件验证，不能报告正式部署 Validate 已通过。
- 发布：本轮禁止 Publish，不写真实 Codex 根目录。
