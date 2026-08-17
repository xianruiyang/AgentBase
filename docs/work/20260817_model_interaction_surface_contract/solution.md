# 模型交互面合同：方案设计

## SOL-001 把 REQ-012 与全局内核提升为模型交互面合同

- 状态: confirmed
- 解决: GAP-001, GAP-002
- 满足: REQ-001, REQ-002, DES-001, DES-002, DES-003, DES-004

修订项目根 REQ-012 及既有 AC，而不创建重叠根需求；增加模型修改面和唯一真源生命周期验收。`global/AGENTS.md` 定义模型交互面术语及判断顺序，替换工具专属规则；根 `AGENTS.md` 把开发与验证责任扩展到模型读取、修改、机器派生和恢复。规则不指定统一文件格式或建立通用压缩器。

验证：检查同一规范事实只在最低充分作用域定义，原工具双视图仍可由新上位合同推导，静态合同不靠保留旧字符串制造重复规则。

## SOL-002 让交付与任务资产显式接入读取面和修改面

- 状态: confirmed
- 解决: GAP-002, GAP-003
- 满足: AC-003, AC-004, AC-005, AC-007, DES-005, DES-006
- 依赖: SOL-001

在 delivery-workflow 公共产物合同中明确阶段 Markdown、manifest/快照、索引/生成视图的权威和派生关系，以及按稳定 ID 局部修改的责任；在 task-table-manager 中明确结构化任务真源通过 taskctl 的 model 查询和 CAS 写入口维护，生成表格不直接编辑。沿用两项工具已经成立的默认 model、显式 machine 合同，不重写 renderer 或制造不存在的兼容迁移。

验证：工作流和任务组件回归通过；静态检查确认 SKILL 与 tooling 对 model/machine、真源和生成物说明一致，且没有要求普通简单文件为形式完整建立额外投影。

## SOL-003 为 Event Logger 建立机器真源到模型恢复面的同源投影

- 状态: confirmed
- 解决: GAP-004
- 满足: AC-002, AC-005, AC-006, AC-008, DES-007, UDES-002, UDES-003
- 依赖: SOL-001

保留现有有界读取函数及 JSON 对象作为 canonical machine 结果，增加默认 `model` 与显式 `machine` 输出面。list 模型视图只提供可选择的 turn；read 模型视图按恢复责任保留 prompt、assistant、goal、文件操作和适用异常，正常路径省略目录、限制、字节和零值。模型预算在选择对话和操作单元时生效并返回精确恢复；machine 继续保持现有完整 JSON。

验证：原测试显式请求 machine 后结构不变；新增默认 model、异常、低预算、list、最新 turn 和机器同源测试，并使用代表性恢复 fixture 比较判断覆盖和实际 Token。

## SOL-004 扩展策略 oracle 并闭合消费者与交付状态

- 状态: confirmed
- 解决: GAP-005
- 满足: REQ-003, AC-008, DES-008, CON-001, CON-002, CON-003
- 依赖: SOL-002, SOL-003

把静态合同和隔离 Policy 从 `consumer_aware_tool_output` 提升为 `model_interaction_surface`，保留工具双视图场景并增加模型读取机器资产、修改权威文件与避开生成物的相近场景。运行受影响组件、静态合同、独立 Routing/Policy/References 评估和部署候选 Validate；更新总计划、当前接手状态与本子计划完成审计。

验证：独立 capsule 身份和隐藏 oracle 声明完整，行为样本同时覆盖读取、修改与机器消费者；source_snapshot 和插件模式未改变，真实 Codex Publish 未执行。
