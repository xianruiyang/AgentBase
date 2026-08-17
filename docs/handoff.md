# AgentBase 当前接手状态

更新时间：2026-08-17

## 当前版本与发布状态

- 当前 Codex 已安装“模型交互面与资产职责”版本，对应核心实现提交 `dfc47b8` 和 `DirectCompatibility` 发布；包含可移植设置的受管理 source bundle SHA-256 为 `220CCE676647CE00EEF64445DDEA9A94CF5A53CE0073D2BB20185C8AC0BDD451`，routing evidence SHA-256 为 `AD83859A201F198AC8DF7923EDA60ED0389CB85434DDD0CE879371897249A021`，回滚资产为 `C:\Users\gzxt\.codex\backups\AgentBase-20260817-142154-933bdcd3`。
- 发布后正式 `Status` 读回：安装 bundle、发布清单、当前仓库来源和路由证据全部匹配，`managed_payload_formally_published=true`，`formal_publication_gap_count=0`；`srcq` 0.3.1 完整性与 doctor 均通过。仓库交付收束提交为 `25d7e79`。
- 本次发布授权已经消费；任何后续再次发布到 `C:\Users\gzxt\.codex` 仍必须由用户针对新的 `Publish` 明确同意，开发、验证、Git 提交、远端同步和本次授权都不能替代。

## 最近完成并发布的版本

最近完成的是 [模型交互面与资产职责](work/20260817_model_interaction_surface_contract/completion-audit.md)：

- `docs/requirements.md` 的 REQ-012 已从工具输出上升为覆盖模型直接读取、生成或修改内容的长期合同；`global/AGENTS.md` 先按事实 owner、消费者、当前判断或修改责任和生命周期裁决读取面、修改面与机器面，不以扩展名、存储位置或传统格式代替职责判断。
- 模型读取面只进入缺失后会改变当前判断、定位、动作、验证或恢复的信息；模型修改面要求同责事实局部可见、稳定可定位、可直接验证且只有一个长期决定位置。模型或人维护的语义真源派生机器产物，程序维护的机器真源通过 owner 的有界投影、查询或受验证语义入口服务模型。
- Delivery Workflow 已明确阶段 Markdown 是模型/人维护的语义真源，索引、保护快照和状态视图按各自机器职责维护；Task Table Manager 已明确任务、状态和结果 JSON 通过正式 revision/CAS 命令维护，生成表格和 completion-context 是读取面，不是语义编辑入口。上一版 `taskctl` / `workctl` 默认 model、显式 machine 双视图保持不变。
- `codex-event-logger` 保持 `conversation.json` 与 `file-operations.jsonl` 的完整机器日志合同，读取器默认返回面向模型恢复的最小投影，显式 `--view machine` 保留原有完整 JSON。模型面只保留 prompt、assistant、goal、净文件操作、异常和精确恢复入口；重复修改被合并，创建后删除的临时文件退出模型面。
- 当前真实 turn 的同一次有界读取中，默认 model 为 489 个 `o200k_base` tokens，显式 machine 为 8736 个，减少 94.4%；模型面仍保留当前需求、上一结论和 20 个最终受影响文件。该比例只证明本轮样本，不是项目固定压缩阈值。
- `task-table-manager` 70 项、`delivery-workflow` 35 项、Event Logger 10 项回归通过；Event Logger 另有 1 项目录链接用例因当前主机能力按既有条件跳过。静态 76-case 合同、Routing 76、Policy 76、References 19 和部署候选 Validate 通过。Routing 保留 1 个非严格用例额外选择 `task-table-manager` 的警告，没有漏选、禁选、严格路由或严格引用失败。

## 直接证据与完成边界

- 本轮交付链有 4 个任务、15 个最终目标、3 个约束和 0 个 DCR；四项结构化结果覆盖根合同、文档/任务资产 owner、Event Logger 恢复面和最终验证交付，跨合同完成读回为 0 诊断。
- 真实 owner 与交互面、机器兼容、模型恢复充分性、Token 对照和生成物边界记录在[交互审计](work/20260817_model_interaction_surface_contract/interaction-audit.md)；跨目标、约束、任务结果和部署身份记录在[完成审计](work/20260817_model_interaction_surface_contract/completion-audit.md)。运行日志只是本轮直接证据，不是项目真源。
- 本次 `Publish` 只证明文件已安装、发布清单与合同匹配；当前 Codex 运行不会追溯加载新规则，行为变化需要在新任务或重启会话中验证。

## 未决问题与后继候选

当前没有阻断本开发候选的已知失败。新上位合同适用于未来模型交互面，但本轮只迁移了已有直接证据和正式消费者的根规则、Delivery Workflow、Task Table Manager 与 Event Logger；其他工具、文件或生成物不能因原则存在就被误标为已经审计或迁移，只有其 owner 出现可证实的必要信息遗漏、冗余成本、误改风险或第二真源时才重开。

跨任务 `source_snapshot` 仍存在重复，但本轮没有改变它的事实表示、引用池、时效语义或恢复合同。既有测量不足以证明替代表达保持模型质量，继续作为独立候选处理。

插件迁移仍是独立事项；当前安装继续使用 `DirectCompatibility`，本轮没有修改插件分发模式。

## 当前边界

- 本版本已在用户针对本次操作明确同意后发布；任何后续再次发布仍需新的当次明确同意。
- 本轮没有混入 `source_snapshot` 压缩或插件迁移。
- 用户已确认项目完全不需要远程 CI；仓库不再维护 GitHub Actions workflow，远端 Actions 权限应保持禁用，所有验证由 Windows 主机上的正式本地入口承担。
- Git 提交与远端同步继续按项目现有授权维护；不得用历史重写、强制推送或反向读取安装副本改变仓库真源。
