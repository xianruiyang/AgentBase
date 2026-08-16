# AgentBase 交付工作流渐进上下文下一版：现状分析

## OBS-001 单阶段修改被要求完整读取统一产物合同

- 状态: confirmed
- 来源: 直接读取 `skills/delivery-workflow/SKILL.md` 与 `references/artifact-contracts.md`
- 关联: AC-001, DES-001, DES-002

主入口明确要求建立或修改任一阶段产物前完整读取 `artifact-contracts.md`。该文件当前为 9,201 字节，同时包含工作区、ID、全部阶段细则、DCR 与最终完成合同；修改单一阶段也承担全部固定输入。

## OBS-002 统一产物合同没有仓库外形态消费者

- 状态: confirmed
- 来源: 对仓库当前非历史内容的精确路径引用搜索
- 关联: DES-001, AC-005

除 `delivery-workflow/SKILL.md` 外，没有脚本、测试或其他当前 owner 按文件路径解析 `artifact-contracts.md`。`workctl` 解析阶段 Markdown，不读取该规范文件，因此合同可以按职责拆分而不需要兼容复制或 CLI 迁移。

## OBS-003 任务上下文已有局部压缩但工作流缺少通用执行边界

- 状态: confirmed
- 来源: 直接读取 `task-table-manager/SKILL.md`、`references/execution.md` 与 `delivery-workflow/SKILL.md`
- 关联: AC-002, AC-003, DES-003

`taskctl context` 已返回任务合同、直接依赖结果、必要上游条目、直接下游和来源快照；任务执行规则也明确不读完整对话。但 `delivery-workflow` 没有对不使用任务表的方案动作定义同一层级的最小语义闭包与扩展条件。

## OBS-004 当前完成审计与辅助工具边界已经充分

- 状态: confirmed
- 来源: 直接读取 `delivery-workflow`、`task-table-manager` 和根需求 REQ-004、REQ-005、REQ-008、REQ-009
- 关联: AC-004, AC-005, DES-004

当前规则已要求最终逐项复核全部确认目标、约束、DCR、直接证据及权威变化影响；CLI 仅提供有界上下文、诊断和快照保护。旧自审与十二轮计划已验证的门禁、分页、DCR、快照和任务存储机制不需要重做。

## OBS-005 Source Query 实践确认固定预读和错误 owner 会放大完整路径成本

- 状态: confirmed
- 来源: `development/source-query-gateway/evidence/round-trip-audit-p10.md` 与 `completion-audit-p10.md`
- 关联: REQ-001, AC-003, CON-001, CON-002

2026-08-16 的真实代理实践直接观察到固定 README 预读、失败回合和错误 owner 会增加端到端上下文；在实际 owner 修正规则边界比继续增加命令配方有效。该证据支持渐进加载原则，但不直接证明本轮交付合同拆分后的具体 Token 降幅。

## OBS-006 独立引用评估只支持单个硬编码 skill

- 状态: confirmed
- 来源: 直接读取 `development/skill-routing/routing_evaluation_common.ps1`、`trigger-cases.json` 与 `test_routing_capsule.ps1`
- 关联: AC-006, DES-005

现有 References 阶段只选择 `change-governance` 用例，候选和结果字段也固定为该 skill。它能验证治理引用，但不能消费新增的 `delivery-workflow` 条件引用路由；另建一次性评估会复制隔离、身份和验证职责。

## GAP-001 阶段合同读取粒度高于当前动作需要

- 状态: confirmed
- 关联: OBS-001, OBS-002, DES-001, DES-002, AC-001

当前唯一引用把互不同时需要的目标、规划、执行和完成细则绑定为固定输入，违反按动作加载最低充分专项上下文的目标。

## GAP-002 非任务表执行缺少明确的最小语义闭包

- 状态: confirmed
- 关联: OBS-003, DES-003, AC-002, AC-003

模型能够从一般原则自行推导局部读取，但正式交付 owner 没有明确哪些上游和结果构成可靠执行的默认闭包，也没有说明何时必须扩展，容易在全量预读与证据不足之间摇摆。

## GAP-003 下一版本的行为变化尚无直接证据

- 状态: confirmed
- 关联: OBS-004, OBS-005, DES-005, AC-006

现有静态合同与独立评估只覆盖当前 skill 身份，且引用阶段硬编码为单个 skill。合同拆分会改变候选 bundle；实施后必须把引用评估泛化为条件引用型 skill 的公共能力，刷新 detached 证据并单独检查阶段引用选择和扩展边界，不能以文件变短直接声称模型行为或 Token 已改善。
