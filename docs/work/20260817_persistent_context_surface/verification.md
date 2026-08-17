# 常驻模型上下文与恢复面验证

## 候选身份

- 已发布基线：`86ee057306659da6e615a7d33580184f8c543cb8`
- 候选 routing bundle：`CDE243F4E0C58F73D335EA5E2CE978D645AB5F612170B4EA42D80F997082693C`
- Routing capsule：`77052D80D2AB879F05FBF8B70CD9B123AE96F948A3993DF1F04A8D0CBC0A53F8`
- Policy capsule：`3F3A5C1750D885EC5334A8CAEB5E8693DF8E0ADE59656E6CF9B0EE8F81E16283`
- References capsule：`7CD8F4B6F0B9F74A491043E04B75C6BB9EC8393DD94FAED1E82EB20E97BC1789`
- 当前合并证据：`development/skill-routing/evidence/current.json`

三个阶段由三个不同的 evaluator run 完成；每项结果都记录实际模型、运行环境、UTC 时间、`detached-capsule` 模式、未访问仓库与隐藏期望声明，并与各自 capsule、candidate、input 和上游 Routing 结果指纹匹配。

## 规则与路由

| 检查 | 结果 | 直接证明范围 |
| --- | --- | --- |
| `validate_contract.ps1` | 通过：76 cases、34 strict routing、5 strict references；11/11 skill 具有正向和非触发覆盖 | 结构、必需语义片段、引用、静态 oracle 与触发集合自洽 |
| detached Routing + `-FailOnUnexpectedSelections -RoutingOnly` | 76/76 通过 | descriptions 缩短及全局重复路由退出后，没有漏选、禁选或严格额外 skill |
| detached Policy | 76/76 满足期望与禁选 | 全局候选继续提供声明的粗粒度行为；不证明具体任务执行 |
| detached References | 19/19 满足合同，5 个严格引用用例通过 | Routing 选择后，`change-governance` 与 `delivery-workflow` 的条件引用没有退化 |
| 合并 evidence + `validate_routing_results.ps1` | staged 76/76/19 通过 | 三阶段身份、输入声明、hash、完整性和正式期望成立 |

Policy oracle 有意把“未声明但未禁选”的兼容标签保留为诊断，而严格额外选择只用于 Routing 和指定 References。若额外启用非正式的全 Policy 精确相等开关，本候选有 109 个兼容标签、已发布基线有 106 个；差异只有 `literal-text-search`、`bounded-file-discovery` 和 `event-log-explicit-history-request` 各多一个 `model_interaction_surface`。本次没有修改模型交互面条款，单次独立评估差异不能形成候选导致退化的因果证据；正式 Policy 期望和禁选全部满足。本限制保留在证据中，不通过改写隐藏 oracle 或反复运行取得更好样本。

## 恢复充分性与 Token

`docs/handoff.md` 已直接定位：已发布提交、真实 Codex `Status`、精确发布清单与回滚路径、当前未发布交付链、未决候选、发布授权限制和后继顺序。全部相对 Markdown 链接均读回为现有文件；只读部署 `Status` 为 `published=true`、`managed_payload_formally_published=true`、正式缺口 0。

同一 `tiktoken 0.13.0 / o200k_base` 结果：

| 读取面 | 基线 | 候选 | 变化 |
| --- | ---: | ---: | ---: |
| `global/AGENTS.md` | 4,690 | 4,531 | -159（-3.4%） |
| 11 个 skill descriptions | 1,192 | 1,057 | -135（-11.3%） |
| 每个适用任务常驻合计 | 5,882 | 5,588 | -294（-5.0%） |
| `docs/handoff.md` 恢复面 | 2,972 | 993 | -1,979（-66.6%） |
| 三个指定读取面 | 8,854 | 6,581 | -2,273（-25.7%） |

handoff 只在接手时读取，最后一行不是每个任务的固定节省。Token 比较只在上述语义、路由和恢复检查成立后用于采纳。

## 部署候选与范围

`manage_agentbase.ps1 -Action Validate` 返回 `valid=true`，证明当前仓库候选的全局规则、skills、三阶段 evidence、受管生命周期、可移植配置、agents、hooks 与独立组件身份满足部署合同。此动作没有写入真实 Codex；当前安装仍是已发布基线。

本验证没有改变 `source_snapshot` 表示、引用池或时效语义，没有实施插件迁移，也没有执行第二次 `Publish`。任何后续真实发布仍需用户针对该次操作重新明确同意。
