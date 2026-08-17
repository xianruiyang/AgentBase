# 模型交互面合同：完成审计

## 1. 审计对象与结论

本审计复核 `cycle-001` 的 15 个最终目标、3 个约束、4 个任务结果、实际消费者和部署候选身份。结论是本版本已经在正确的正式 owner 与合同层闭合：项目长期目标由 `docs/requirements.md` 拥有，跨项目判断顺序由 `global/AGENTS.md` 拥有，阶段资产和任务资产分别由 Delivery Workflow 与 Task Table Manager 拥有，机器日志到模型恢复面的投影由 Codex Event Logger 拥有。没有建立通用 hook、统一摘要器、第二真源或同责发布入口。

四项任务均为 `done`，最终 completion-context 对目标、约束、任务 revision、来源快照和结果诊断的当前读回为 0 诊断。核心实现提交为 `dfc47b8`；正式部署候选 `Validate` 通过，但没有向实际 Codex 根目录执行 `Publish`，因此当前已安装版本仍是 `6fe7838`。

## 2. 正式 owner 与合同层闭合

| 正式 owner | 本版本承担的合同 | 当前消费者与完成证据 |
| --- | --- | --- |
| `docs/requirements.md` REQ-012 | 所有模型直接读取、生成或修改内容的长期可验收结果；读取面、修改面、机器面和唯一真源边界 | 根规则、工作流、任务工具和 Event Logger 均能从 AC-040—AC-046 推导，没有新增重叠根需求 |
| `global/AGENTS.md` | 先判断事实 owner、消费者、当前判断或修改责任和生命周期，再选择交互面；格式只在投影后比较 | 静态合同和独立 Policy/Routing 评估覆盖新触发边界；不承担领域字段或文件清单 |
| Delivery Workflow | 阶段 Markdown、工作流清单、保护快照、索引和状态视图各自的真源与派生职责 | 稳定 ID 支持模型局部维护；35 项回归证明现有工作流入口未退化 |
| Task Table Manager | 结构化任务、状态、结果的正式 revision/CAS 写入，以及默认 model、显式 machine 读取责任 | 真实 T001—T004 通过正式状态命令维护；70 项回归证明任务合同与机器消费者未退化 |
| Codex Event Logger | 完整机器日志到最小充分模型恢复面的同源投影 | 10 项回归、异常/低预算 fixture 与真实 turn Token/恢复审计直接覆盖；显式 machine 保持原 JSON |

## 3. 最终目标覆盖

| 目标 | 当前结构化证据 | 完成结论 |
| --- | --- | --- |
| REQ-001 | T001、T004 | 根需求和全局内核不再只从工具输出出发，读取、生成与修改内容统一按交互面裁决 |
| REQ-002 | T001、T002、T004 | 唯一真源按维护主体与生命周期确定，模型面和机器面不形成双向同步 |
| REQ-003 | T002、T003、T004 | 当前正式消费者已接入；上一版 task/work 双视图保持为工具输出子集 |
| AC-001 | T001、T004 | owner、消费者、当前责任和生命周期成为设计起点 |
| AC-002 | T001、T003、T004 | Event Logger 真实恢复面只保留会改变恢复判断的信息 |
| AC-003 | T001、T002、T004 | 模型修改内容具有稳定 ID、局部职责和唯一决定位置 |
| AC-004 | T001、T002、T004 | 模型/人维护的阶段真源可重建索引与状态视图 |
| AC-005 | T001、T002、T003、T004 | 结构化任务与机器日志通过正式查询、投影或语义写入口服务模型 |
| AC-006 | T003、T004 | 预算在投影前参与规划，低预算保留 turn 身份、原因和精确恢复入口 |
| AC-007 | T002、T004 | Delivery Workflow 与 Task Table Manager 明确真源、生成物及修改入口 |
| AC-008 | T003、T004 | 读取充分性、修改局部性、machine 稳定、派生边界和真实 Token 分别验证 |
| UDES-001 | T001、T004 | 命令返回、生成给模型阅读的文件和模型修改文件处于同一上位合同 |
| UDES-002 | T001、T002、T003、T004 | 模型面最小充分，机器面稳定完整 |
| UDES-003 | T001、T002、T003、T004 | 领域必要性由内容 owner 决定，不依赖通用 hook 或格式器猜测 |
| UDES-004 | T001、T003、T004 | 不把格式变短当成质量；真实读取、恢复和 Token 证据共同裁决 |

全部结果的 `source_snapshot` 与当前阶段条目一致，任务 revision 当前，`unresolved` 和 `invalidated_source_ids` 均为空。没有 DCR；确认后的用户目标和三个约束没有漂移。

## 4. 约束与排除项

| 约束 | 证据 | 结论 |
| --- | --- | --- |
| CON-001 质量、Token、速度顺序 | 组件回归、真实恢复审计、独立评估先于 Token 结论 | 489/8736 tokens 的差异只在恢复充分性成立后采纳，没有设固定压缩率 |
| CON-002 不混入 `source_snapshot` 或插件迁移 | 变更范围、任务结果和部署模式读回 | 未改变 `source_snapshot` 表示、引用池或时效语义；仍为 `DirectCompatibility` |
| CON-003 Publish 当次授权 | handoff、部署命令边界与当前安装读回 | 只执行 `Validate`，没有执行 `Publish`；再次发布仍需用户当次明确同意 |

## 5. 验证与身份

- Task Table Manager：70 项通过。
- Delivery Workflow：35 项通过。
- Codex Event Logger：10 项通过；1 项目录链接用例因当前 Windows 主机能力按既有条件跳过。
- 静态合同：76 个场景通过，11/11 skills 均有正向与非触发覆盖。
- 独立评估：Routing 76/76、Policy 76/76、References 19/19；Routing 仅保留一个非严格场景额外选择 `task-table-manager` 的警告，没有漏选、禁选、严格路由或严格引用失败。
- 真实 Event Logger：同一次有界读取的默认 model 为 489 个 `o200k_base` tokens，显式 machine 为 8736 个；模型面仍覆盖需求、上一结论、20 个最终文件与恢复入口。完整方法和限制见[交互审计](interaction-audit.md)。
- 部署候选：`DirectCompatibility` `Validate` 通过，source bundle SHA-256 `E855645C83C820E3063425B55DCD410ACD3F52B3751C41E00D15BB964913C772`，routing evidence SHA-256 `AD83859A201F198AC8DF7923EDA60ED0389CB85434DDD0CE879371897249A021`，candidate bundle SHA-256 `9E8378165B8FD746AB58E35545BA539034C5B784B3ECC546AEB7A61980AB990B`。

## 6. 完成边界与重开条件

本版本证明的是上位合同和当前四个正式 owner/消费者已经闭合，不证明仓库内所有未来文件或工具都已优化。其他模型交互面只有出现直接的必要信息遗漏、冗余上下文、误改风险、生成物反向决定真源或同责多入口证据时，才回到其正式 owner 重开。Event Logger 的恢复充分性、machine 兼容、语义预算或异常保护退化时也应重开。

`source_snapshot` 压缩和插件迁移保持独立候选；当前没有授权向 Codex 发布。本完成结论只覆盖仓库开发候选、结构化证据和 `Validate`，不把未安装的新规则误称为当前 Codex 运行行为。
