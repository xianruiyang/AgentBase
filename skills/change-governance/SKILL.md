---
name: change-governance
description: 裁决故障根因、争议 oracle、职责与正式入口、跨消费者影响、迁移退出、共享门禁和跨契约完成审计。不用于仅校准意图、按已知事实纠正前提、稳定 owner 下的普通实现/复核、局部验证或一般问答。只读评审确需上述裁决时仍适用；批量顺序、失败遮蔽与执行成本归 execution-governor。
---

# Change Governance

只处理当前动作确需的原因、职责、入口或验收判断。普通修改、单个文件存在、任务结束都不自动触发治理；不要求先走 execution-governor。

## 选择参考

- 原因、机制、反复失效或差距会改变动作：读 [causal-analysis.md](references/causal-analysis.md)。同时要求修复或证明原机制不再失败时，再读 [verification-and-gates.md](references/verification-and-gates.md)；仅使用已有反例分析原因时不加载后者。
- 多入口、第二状态源、职责/权威变化、共享能力、消费者接入、迁移兼容、原型转正或临时路径退出：读 [lifecycle-and-entry.md](references/lifecycle-and-entry.md)。只定位规则、路由或动作的失效层仍归 causal。
- 争议 oracle、机制修复证明、模型行为的验证/反馈缺口、共享阻断门禁或跨契约完成审计：读 [verification-and-gates.md](references/verification-and-gates.md)。
- 多个缺口同时成立才组合引用；失败分类已由 execution-governor 覆盖、这里只裁决长期入口时，不再加载 causal。

## 裁决与交付

找出能改变当前方案的判断及反证。职责按稳定约束、状态、生命周期、失败边界和变化原因裁决，不能仅按文件位置或实现相似性合并。修正从权威 owner 传播到实际消费者；保留已确认目标，不在下游吸收上游冲突。

只报告关键结论、来源、影响与未证范围，不固定填写认识状态或完整审计清单。需要跨轮或消费者恢复的决定写回现有设计、方案、任务或结果；普通单轮分析以最终回复记录。

出现共享未知、扩量、昂贵验证或反复失败时才另用 execution-governor 控制顺序；实际修改阶段文档或任务状态才选择其对应 skill，不为引用名称预加载整套流程。
