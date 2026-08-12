# 从旧资产重建 v1 计划

只在用户明确授权迁移时使用。迁移是以当前设计为真源的新建模，不是把旧任务表、状态、测试或 Gate 转换成新格式。

1. 从用户要求和当前正式设计重新建立 requirements、observable claims 与依赖方向。
2. 对旧实现、测试、门禁和文档分别标记 `reuse`、`adapt`、`retire`、`audit_only` 或 `unknown`；记录职责、实际行为、适配成本和证据。名称相同、曾通过或覆盖面大都不构成复用依据。
3. 只把 `reuse/adapt` 的内容组装到新任务中。会强化旧架构、产生第二套业务、错误阻断局部迭代或掩盖真实失败的资产应移除出活动路径；是否删除或归档仍遵循用户授权。
4. 旧测试全部先按 `untrusted_legacy` 处理。重新确认 requirement、oracle、baseline、negative path、作用范围和公开用户流程后，才能成为 `qualified`。
5. 不导入旧 `done`、百分比、handoff、memo、Gate 结论或任务 ID 作为新状态。旧材料只可作为候选场景和审计证据；v1 从 `activate` 生成全新状态。
6. 比较新计划的 requirement/claim 覆盖与正式设计，确认没有静默漏项后再激活。当前仍在执行的旧计划默认继续 legacy 模式，不因 skill 更新而迁移。
7. 迁移包含大量历史身份、入口或资产逐项处置时，按 [create-plan.md](create-plan.md) 的项目级 `semantic_preflight` 冻结 owner、精确 successor/gap、处置、生命周期、输入输出和证据绑定；结构追踪通过不能替代该回执。
