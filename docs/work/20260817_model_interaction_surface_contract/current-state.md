# 模型交互面合同：现状分析

## OBS-001 根 REQ-012 和运行规则当前只覆盖工具输出

- 状态: confirmed
- 来源: `docs/requirements.md` REQ-012、AC-040—AC-044，`global/AGENTS.md` 第 3 节与根 `AGENTS.md` 维护/验证条款
- 关联: DES-001, DES-002

直接观察：正式文字反复使用“工具输出”“模型视图”“机器视图”，没有把模型读取、生成或修改的文件定义为同一交互面。证据上限是规范覆盖范围，不证明所有运行行为都违反更广目标。

## OBS-002 上一专项的用户设计比实际目标和实现范围更广

- 状态: confirmed
- 来源: `docs/work/20260817_model_visible_tool_output_contract/user-design.md` UDES-001 与同专项 requirements/design/completion-audit
- 关联: DES-001

直接观察：UDES-001 已记录“模型直接阅读和修改的内容采用极简设计”，但专项 REQ、DES、SOL 和完成审计只迁移 taskctl/workctl。上一版如实声明其他 owner 未迁移，因此其完成证据仍有效，但不能证明更广用户设计已经闭合。

## OBS-003 Delivery Workflow 已有唯一真源与派生产物基础

- 状态: confirmed
- 来源: `delivery-workflow` 的 `artifact-contracts.md`、`SKILL.md` 与 `workctl` 合同
- 关联: DES-005

直接观察：阶段 Markdown 已被定义为语义真源，`workflow.json` 只登记位置，保护快照只保存确认元数据，索引和生成视图可重建；稳定 ID 支持局部引用。当前合同尚未把这些事实提升为通用的模型读取面/修改面职责，也没有直接说明为何模型不得编辑派生产物。

## OBS-004 Task Table Manager 已有双视图和结构化写入基础

- 状态: confirmed
- 来源: `task-table-manager` 的 `SKILL.md`、`task-contracts.md` 与 `tooling.md`
- 关联: DES-006

直接观察：任务合同、状态和结果分别保存在结构化 JSON，写命令使用路径与 CAS revision 门禁，生成表格和索引不是任务真源；SKILL 与 tooling 已记录默认 model、显式 machine 合同。当前缺口是这些事实尚未被明确组织为“模型通过正式读取/修改面维护结构化真源，生成表格与索引不得作为修改入口”的统一资产合同。Delivery Workflow 也已有 Markdown 真源和 model/machine 说明，但缺少相同修改面表述。

## OBS-005 Event Logger 把机器记录对象直接作为模型读取结果

- 状态: confirmed
- 来源: `skills/codex-event-logger/scripts/read_codex_turn_log.py`、`SKILL.md` 与测试
- 关联: DES-007

直接观察：读取器已经限制文件、行、记录、深度和字符串并再次脱敏，但默认把路径、大小、全部限制参数、正常状态、截断计数和完整有界记录对象以 pretty JSON 返回。它直接服务压缩恢复和历史追溯，没有 model/machine 消费者投影。现有测试只证明边界和 JSON 结构，不证明模型恢复充分性或 Token 成本。

## OBS-006 当前隔离策略只有工具输出行为样本

- 状态: confirmed
- 来源: `development/skill-routing/trigger-cases.json` 的 `consumer_aware_tool_output` 标签和用例
- 关联: DES-008

直接观察：Policy oracle 只要求在 model/machine 工具视图间选择，没有模型读取机器文件、维护模型友好真源或避免编辑生成物的场景。

## GAP-001 用户确认的模型交互范围没有进入上位合同

- 状态: confirmed
- 关联: REQ-001, REQ-002, DES-001, DES-002, OBS-001, OBS-002

当前规则从工具生产者输出开始判断，仍可能把文件和生成内容当作中性载体；模型在读取或修改前没有统一的 owner、消费者、责任与生命周期判断起点。

## GAP-002 模型读取面与模型修改面没有独立职责

- 状态: confirmed
- 关联: AC-002, AC-003, DES-003, DES-004, OBS-003, OBS-004

既有原则主要检查上下文字段是否必要，没有同时要求模型直接修改内容具备语义局部性、唯一修改位置、生成区隔离和直接验证，容易把“更短”误当成“更易可靠修改”。

## GAP-003 当前文档/任务消费者没有完整接入新语义

- 状态: confirmed
- 关联: AC-007, DES-005, DES-006, OBS-003, OBS-004

工作流和任务资产已有大部分正确结构与 model/machine 输出说明，但正式合同未把读取、修改和机器派生关系明确为同一交互面，也未直接禁止通过生成视图改变语义或绕过结构化写入责任。

## GAP-004 当前机器日志恢复入口仍把完整有界对象交给模型

- 状态: confirmed
- 关联: AC-002, AC-005, AC-006, DES-007, OBS-005

Event Logger 已控制资源上限但没有按恢复或历史选择动作投影，证明“有界”不等于“最小充分”；路径、限制和正常元数据仍与真正需要的 prompt、assistant、goal、文件操作和异常并列进入上下文。

## GAP-005 验证不能观察文件读取与修改思维是否改变

- 状态: confirmed
- 关联: AC-008, DES-008, OBS-006

静态字符串和现有工具用例只能证明工具输出规则存在，不能推翻模型仍把机器文件或生成视图当作默认读取/编辑对象的错误机制。
