# AgentBase Evo

AgentBase 演进框架，简称 **Evo**。本目录是 [AgentBase 总计划](../../plan.md)下的独立子计划入口，承接指定 AGENTS、skill、hook、MCP、工具、子 agent 设置和 Codex 设置组合的独立评分与内容自动迭代。评测内容单独分组，支持增删和选择激活。

本目录沿用命名前建立的路径，保留已有引用和源码研究，不另建同责目录。

## 文档职责

| 文档 | 内容与使用方 |
| --- | --- |
| [requirements.md](requirements.md) | 用户已确认的目标与范围；用户和实施模型据此判断结果与授权边界 |
| [user-design.md](user-design.md) | 用户确认的名称和计划层级；不把模型提出的技术路线当作用户指定设计 |
| [current-state.md](current-state.md) | 现有框架与第三方源码的直接事实、证据边界和差距 |
| [design.md](design.md) | 模型形成的基本设计；定义职责、对象、运行、评分与追溯合同 |
| [solution.md](solution.md) | 实施动作、阶段依赖、兼容处理和十三项需求的验证安排 |
| [estimates.md](estimates.md) | 完成 Evo 的工期和额度估算；保存假设与重估方法，不保存账户私有状态 |

各事实在所属文档维护；本文只导航。外部仓库来源和恢复由[参考目录](../../../development/references/README.md)维护，Evo 不复制来源清单。

## 当前阶段与后续切入点

初版使用入口见 [Evo 说明](../../../development/agent-evaluation/evo/README.md)。完成证据与适用边界由 [任务表](TASK_TABLE.md) 导航至结果真源；基本设计与实施方案继续按证据修订，不能以任务状态代替验收。新增用户结果统一进入 `requirements.md`，名称和计划层级由 `user-design.md` 维护。授权边界见 [CON-001](requirements.md#con-001-当前授权与阶段边界)。

初版范围按 SOL-011 覆盖 M1—M5；小场景证明框架可运行，不代表已取得真实内容优化收益。`workflow.json` 登记阶段文档，`taskctl` 维护任务合同、状态和结果；表格与索引可重建，不反向修改语义。

下一次接手按需读取：

1. 需求、用户设计与实际新任务，确认当前评测或修改范围；已有实施授权不自动授权新的大规模模型研究。
2. 对应 DES、SOL 及其引用的 OBS；源码或宿主合同变化时补查受影响证据，不重新展开全部研究。
3. 涉及外部参考源码时按来源清单核对版本；涉及模型运行时先明确场景、额度、评分与副作用范围。

本文和阶段 Markdown 由维护模型局部编辑；`workctl`/`taskctl` 的索引、来源快照和状态视图按各自合同维护，不替代用户目标或建立第二份技术方案。
