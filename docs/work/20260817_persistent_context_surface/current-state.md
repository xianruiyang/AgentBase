# 常驻模型上下文与恢复面收敛：现状分析

## OBS-001 当前高频读取面具有可观测成本

- 状态: confirmed
- 证据: 2026-08-17 当前仓库文件与本机 `tiktoken 0.13.0` 的 `o200k_base`
- 关联: DES-001, DES-003

`global/AGENTS.md` 为 18,386 UTF-8 bytes、195 行、4,690 tokens；11 个项目 skill description 合计 1,881 字符、1,192 tokens。静态合同的 `global_max_bytes` 为 20,480，当前文件已使用约九成字节额度。数值证明审计范围和维护余量，不证明具体语义可以删除。

## OBS-002 skill descriptions 已明确承担正向与负向路由

- 状态: confirmed
- 证据: 11 个 `skills/*/SKILL.md` frontmatter 与 `development/skill-routing/trigger-cases.json`
- 关联: DES-001, DES-002

当前 descriptions 普遍同时表达触发、非触发或协同条件；其中 `change-governance`、QQ Hook、Reasoning Governor 等较长条目覆盖容易误选的边界。只按长度统一改写会改变预加载路由信息，必须逐项对照正文职责和 76 个路由用例。

## OBS-003 handoff 已混合当前恢复与已归档历史展开

- 状态: confirmed
- 证据: `docs/handoff.md` 与其链接的两个完成审计
- 关联: DES-001, DES-003

当前 handoff 为 11,241 UTF-8 bytes、59 行、2,972 tokens。它完整保留当前版本、真实安装、回滚与未决边界，同时再次展开统一生命周期根因、上一模型交互面实现和多组历史测试；这些细节已有正式完成审计或组件说明持有。后继只需要当前结论、直接证据和精确链接即可恢复动作。

## OBS-004 当前没有需要借本版本修复的 LSP、source_snapshot 或插件故障

- 状态: confirmed
- 证据: `docs/plan.md`、`docs/handoff.md`、Source Query Gateway 当前状态与本轮发布读回
- 关联: CON-002, UDES-002

Source Query Gateway 已验证宿主延迟发现路径，`source_snapshot` 的默认模型视图已省略完整快照且替代表示仍缺质量证据，当前 DirectCompatibility 发布状态为正式 published 且无缺口。这些对象不构成本版本差距。

## GAP-001 常驻规则与路由面缺少当前语义必要性审计

- 状态: confirmed
- 关联: REQ-001, AC-001, AC-002, DES-001, DES-002, OBS-001, OBS-002

当前有规模与路由覆盖证据，但尚未逐项区分全局预加载必需语义、skill 预加载必需语义和正文加载后细则；因此既不能证明现状已经最小，也不能安全从字节接近门限直接推出删改方案。

## GAP-002 handoff 的当前恢复职责被历史展开放大

- 状态: confirmed
- 关联: REQ-001, AC-003, DES-001, OBS-003

同一历史结论同时存在于完成审计和 handoff 展开正文，增加恢复输入并扩大旧事实失效时的同步面；handoff 尚未严格收敛为当前索引。

## GAP-003 候选尚无同质量 Token 与路由证据

- 状态: confirmed
- 关联: AC-004, DES-003, OBS-001

当前只有基线测量。任何文本候选仍需证明恢复充分、规则语义和独立路由不退化，再比较 Token；没有这些证据时不得采纳压缩。
