# 模型可见工具输出合同完成审计

更新时间：2026-08-17

## 当前结论

本专项在其确认范围内已完成：taskctl/workctl 的同源 model/machine 输出面、仓库消费者迁移、语义预算恢复、UTF-8、真实工作区质量与 Token 审计、独立 Routing/Policy/References 证据和部署候选 `Validate` 均已闭合。最终 `completion-context` 返回 14/14 目标、3/3 约束、0 个 DCR、0 个查询或候选结果诊断，所有目标均有带验证的当前候选结果。该结论不等于已经发布到 Codex，也不把其他工具 owner 标记为已迁移。

## 已覆盖证据

- `docs/requirements.md` 已增加 REQ-012 与 AC-040—AC-044，明确按实际消费者和当前动作选择输出面、模型最小充分投影、同源 machine 合同、语义预算恢复以及质量与真实 tokenizer 双重验收。
- `global/AGENTS.md`、根 `AGENTS.md` 与两个 skill 的正式合同已经建立“先投影、后序列化”和同一 canonical 计算派生双视图的职责边界。
- `taskctl.py` 与 `workctl.py` 默认提供模型视图，显式 `--view machine` 保留稳定 JSON；预算不足时裁剪完整低优先级单元并返回可定位恢复信息，未改变 `source_snapshot` 的事实表示。
- `task-table-manager` 70 项与 `delivery-workflow` 35 项回归通过，包括非 UTF-8 默认宿主、模型视图、显式 machine 视图、低预算恢复和错误输出场景。
- [输出审计](output-audit.md)记录了真实工作区上的字段充分性、实际 `o200k_base` Token 对照和同投影 JSON、HJSON 风格、YAML 表示比较；具体比例仅证明该样本，不作为全项目固定阈值。
- [消费者影响复核](consumer-impact.md)沿根 README 的正式 owner 检查了 srcq、MCP、事件日志、推理深度、QQ 与开发入口；只有 taskctl/workctl 在本版本形成迁移闭环，其他 owner 不被误标为已采用同一实现。
- 静态合同通过 74 个 case、34 个严格路由 case、5 个严格引用 case及 11/11 skill 正向与非触发覆盖；最终独立证据为 Routing 74、Policy 74、References 19，三阶段来自不同 detached capsule 运行并绑定同一候选哈希。
- Routing 最终结果在一个非严格 case 中额外选择 `task-table-manager`，正式校验器将其记录为警告；没有漏选、禁选、严格路由或严格引用失败。早期独立运行的漏选没有被用于证据合并。
- References 早期运行曾在执行反馈 case 过选 `target-contracts.md`；根因是“目标保护”边界容易把单纯遵守不变误读为目标合同动作。`delivery-workflow` 正式 owner 已明确只有目标创建、修改、重新裁决、漂移、DCR 或最终复核才加载目标合同，新的 References 19/19 验证通过。
- Routing 早期运行反复把“读取、解析、字段投影组成的一行 PowerShell 管道”误当作单个只读 cmdlet；`powershell-usage` 已在描述与正文中按语义构成而非物理行数明确边界，静态合同和后续 Routing 通过。
- 正式部署候选 `Validate` 通过，source bundle 为 `F246ED2FF687FC988F66DDAC30B01D04B5E41AADA30D411C4817D43501735DC9`，routing evidence 为 `E7380AD4D2311A9C61F0DF4A25DE1D32DBCE82C75D58AF20CAF39F5526DD2ECE`；该验证没有写入真实 Codex 根目录。

## 最终跨合同读回

- 任务状态：4/4 `done`，4/4 当前引用结果包含 verification，当前状态摘要没有结果诊断。
- 最终快照：`sha256:e82c1eff7ab27aba3122a06b003802e32b7d1423fe1f4c67815968b34c17b638`；14 个目标和 3 个约束均完整返回，没有分页续游标，0 个 DCR。
- 证据覆盖：14 个目标的 `candidate_result_with_verification_count` 均大于 0；候选任务为 T001—T004，当前 T004 结果是 `r6`。
- 诊断：`query_diagnostic_count=0`，候选结果诊断、任务 revision 陈旧、来源快照问题和总诊断均为 0。
- T004 的首次 `r3` 曾把 `CON-002` 列入 `evidence_for`，但执行来源快照没有消费它，CLI 正确产生 `result_source_snapshot_incomplete`。该历史结果没有被改写或删除；任务重开后把 `CON-002` 加入正式来源，后继执行 context 读回 34 个完整来源和 0 诊断，`r6` 重新验证并成为当前结果。

## 明确边界

- 本专项没有改变 `source_snapshot` 的表示、去重池或压缩合同；只在模型投影中省略当前动作不需要的重复完整副本。
- 本专项没有进行插件迁移，也没有改变当前 `DirectCompatibility` 安装模式。
- 根 REQ-012 是适用于后续工具变更的长期合同；本专项完成只覆盖 taskctl/workctl 的直接实现与消费者迁移，不声称事件日志、推理深度、QQ、MCP 或开发脚本已经统一改造。事件日志是有直接模型消费者但尚缺真实质量对照的后继审计候选。
- 本专项没有向 `C:\Users\gzxt\.codex` 发布；任何再次 `Publish` 仍需用户针对当次操作明确同意。
