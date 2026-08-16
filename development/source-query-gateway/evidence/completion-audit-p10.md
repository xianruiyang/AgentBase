# Source Query Gateway 完成矩阵

## 边界

本表逐项审计 [requirements.md](../requirements.md) 与 [user-design.md](../user-design.md) 的项目真源实现。`verified` 表示直接证据覆盖该条当前声明；它不表示 P10 已发布到 Codex。模型收益只由真实隔离运行证明，组件、文档或静态规则不代替端到端证据。

## 根本需求与验收

| 条目 | 状态 | 直接实现或证据 | 边界 |
| --- | --- | --- | --- |
| REQ-SQG-001 | verified | [iteration-audit-p10-v21.md](iteration-audit-p10-v21.md)、[audit-result-p10-v21.json](audit-result-p10-v21.json) | 12/12 质量；相对 P9 总 Token `-7.31%`；耗时 `+32.38%`，按既定优先级采纳但不声称更快 |
| AC-SQG-001 | verified | `tools/srcq/crates/srcq-cli/tests/query_gateway_real.rs`、v21 逐案审计 | 文件、文本、实现范围、关系与全集六类任务均取得 required 证据；组件测试覆盖分页和有界闭环 |
| AC-SQG-002 | verified | `tools/srcq/docs/model-output.md`、v21 usage | 普通/缓存输入、输出、推理输出与总量分列；1,066,470 Token 低于 P9 1,150,528 |
| AC-SQG-003 | verified | v21 usage 与 [verification.md](../verification.md) | 同 tier 计时完整；候选更慢，结论明确保留，不用速度抵消 Token 收益 |
| AC-SQG-004 | verified | `development/code-search-benchmark/experiment.py`、`corpus/v10.json`、v21 capsule 与 detached audit | 新鲜隔离 subject、身份冻结、外部 monitor、确定性验真和独立审计全部执行 |
| AC-SQG-005 | verified | `evidence/lsp-progressive-v1.json`、`skills/source-query/references/lsp.md` | no-LSP、单项和多阶段路径按 0/2/3 个能力渐进展开；未新增 `srcq lsp` |
| AC-SQG-006 | verified | `global/AGENTS.md`、`skills/source-query/SKILL.md`、v21 命令记录 | 已知正文直读，fd/rg 经 srcq，AST/LSP 只按实际证据缺口升级；项目/Provider 事实仍由最近来源裁决 |
| AC-SQG-007 | verified | `tools/srcq/docs/query-gateway.md`、`skills/source-query/references/rg-fd.md`、真实网关测试 | 退出、无匹配、分页、`@more`、`@cut`、snapshot/cursor 与错误恢复边界可区分 |
| AC-SQG-008 | verified | `srcq rg <argv...>` / `srcq fd <argv...>`、直接入口回归 | 模型无需预选 heading/tree/view/limit；显式 machine/native/artifact 保留独立控制面 |

## 约束

| 条目 | 状态 | 直接实现或证据 | 边界 |
| --- | --- | --- | --- |
| CON-SQG-001 | verified | 本目录的 requirements、user-design、design、current-state、solution、plan 与 tasks | 分支文档独立；已验证职责才迁入项目正式规则和 skill；Codex 发布仍逐次授权 |
| CON-SQG-002 | verified | `tools/srcq/docs/installation.md`、release/install 测试、项目 `AGENTS.md` | 正式运行时、安装、构建和验证只维护 Windows x86_64 MSVC |
| CON-SQG-003 | verified | `development/codex-deployment` payload 校验、`skills/source-query` 五文件边界 | benchmark、fixture、runner、原始结果和 audit 只在 development，不进入发布 payload |

## 用户设计

| 条目 | 状态 | 直接实现或证据 | 边界 |
| --- | --- | --- | --- |
| UDES-SQG-001 | verified | `tools/srcq` 单一 workspace 与 `skills/source-query` | rg、fd、AST 统一由 Source Query Gateway 承载，旧独立包装已退出正式消费者 |
| UDES-SQG-002 | verified | argv 透明测试、backend candidate matrix、native/artifact 路径 | 不以版本字符串准入；不能安全结构化时无损透传或显式失败，不伪装空结果 |
| UDES-SQG-003 | verified | `query_gateway.rs` renderer、model-output 文档与真实默认输出回归 | 工具观察实际结果后选择最短等价表示；正常完整输出没有固定 envelope |
| UDES-SQG-004 | verified | fd tree 与 rg tree-heading 测试 | 公共前缀只在可逆、顺序保持且实际更短时压缩；否则自动回退 flat/heading |
| UDES-SQG-005 | verified | workspace 测试、真实后端、release/install、doctor | 新增 rg/fd 具备与 AST 基线相同层级的接口、错误、测试、安装和来源边界 |
| UDES-SQG-006 | verified | AST baseline、`skills/source-query/references/ast.md` | 迁移前命令、profile、cache、fingerprint、process、rewrite、TTY/LSP 与 machine 协议未退化 |
| UDES-SQG-007 | verified | benchmark monitor、v21 raw-file capsule、detached auditor isolation declaration | 每个 case 使用新鲜隔离 agent；协调方只监控，不在运行中修正答案 |
| UDES-SQG-008 | verified | `development/code-search-benchmark/**` 与 deployment payload allowlist | 全部实验资产只保留在项目开发目录 |
| UDES-SQG-009 | verified | `install-srcq.ps1` 与隔离安装生命周期 | 用户级 PATH、Install/Status/Upgrade/Uninstall、回滚与受管卸载已覆盖 |
| UDES-SQG-010 | verified | `srcq.exe`、release manifest、消费者和迁移记录 | 唯一产品/命令身份为 Source Query Gateway / srcq；无 `sgy.exe` 别名或第二运行时 |
| UDES-SQG-011 | verified | LSP 渐进三案与 source-query 的按需 lsp 引用 | 宿主原生延迟发现已达标；编辑器写操作仍由独立 owner 承担 |
| UDES-SQG-012 | verified | 全局路由、source-query 与 v21 命令链 | 直接读取、srcq 文本/文件、AST、LSP 按证据与 Provider 逐层选择，不永久禁用 LSP |
| UDES-SQG-013 | verified | 精炼的 `global/AGENTS.md` 与 `skills/source-query/SKILL.md`、路由 corpus | 常驻内容只表达根本边界；规则审查非触发，没有 benchmark 答案、正反例或固定命令配方 |
| UDES-SQG-014 | verified | `design.md` DES-SQG-013、外部后端实现 | 当前反例均可在外部适配层解决，未拉取或分叉上游源码；升级仍要求先与用户讨论并单独授权 |

## 完成结论

26 个条目均有范围匹配的项目实现或直接证据。P10 最终候选在质量不退化时降低总 Token，速度反向已如实保留；当前没有共享明显改进支持继续增加规则、接口或默认预算。项目真源完成，Codex 安装态仍是此前发布的 P9；只有获得本次明确发布同意后才能更新安装态。
