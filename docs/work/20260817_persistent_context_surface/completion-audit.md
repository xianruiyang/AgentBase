# 常驻模型上下文与恢复面收敛：完成审计

## 审计范围与身份

本审计只覆盖当前交付链确认的 1 个需求、4 个验收条件、2 个用户设计和 2 个约束。已发布 Codex 基线仍是 `86ee057306659da6e615a7d33580184f8c543cb8`；功能候选提交是 `fc1215b8d54939217fe82c7d830b8722713e6948`，状态提交是 `1295490c863ea49fd46c5b04e45b67bdf24c16ae`，两者已同步到 `origin/main`；routing bundle 是 `CDE243F4E0C58F73D335EA5E2CE978D645AB5F612170B4EA42D80F997082693C`。本版本没有再次执行真实 `Publish`。

## 目标证据

| 目标 | 当前结果与直接证据 | 判定 |
| --- | --- | --- |
| REQ-001 降低高频模型读取面的完整决策成本 | [读取面审计](context-surface-audit.md)逐项裁决 owner、读取时点与删除后果；[验证](verification.md)证明质量门后常驻面减少 294 tokens，最终 handoff 减少 1,725 tokens | 满足 |
| AC-001 保持跨项目行为合同 | 只合并同一全局 owner 内的连续重复规则，保留优先级、目标、证据、授权、交互面、查询升级、验证、完成和 Git 不变量；静态 Policy 和部署 Validate 通过 | 满足 |
| AC-002 保持 description 预加载路由边界 | 11 项逐一保留正向、相近非触发和协同边界；严格 Routing 76/76，References 19/19，静态 11/11 有正负覆盖 | 满足 |
| AC-003 handoff 只承担当前恢复 | `docs/handoff.md` 直接提供已发布基线、候选、真实状态、回滚、证据、边界和下一入口；所有相对链接存在，历史实现只保留正式 owner 链接 | 满足 |
| AC-004 同质量真实 Token 验收 | 同一 `tiktoken 0.13.0 / o200k_base` 比较；Token 仅在静态、独立评估、恢复清单和部署 Validate 后采纳 | 满足 |
| UDES-001 按常驻上下文方向继续开发 | 全局规则、11 descriptions 和 handoff 三个 owner 均已审计、实现和验证 | 满足 |
| UDES-002 保持独立候选边界 | 没有改变 `source_snapshot` 表示、引用池或时效语义，没有实施插件迁移 | 满足 |

## 约束与影响闭合

- CON-001：候选先通过 76-case 静态合同、严格 Routing、Policy/References 正式期望、恢复清单和部署 `Validate`，之后才比较 Token；没有按文件上限或目标比例删规则。
- CON-002：已发布基线和未发布候选分开记录；本次发布授权已消费，Git 同步不替代新一次发布授权。
- `global/AGENTS.md` 的所有项目消费者由候选规则与 Policy capsule 覆盖；删除的专项 skill 映射由始终预加载的 descriptions 和通用路由规则唯一承担，没有形成第二路由表。
- 11 个 description 的消费者由 76 个现有正向、相近非触发、混合与严格用例覆盖；`validate_contract.ps1` 已同步验证新表述，并显式补足 C++ 相近非触发边界。
- 新 `development/skill-routing/evidence/current.json` 绑定候选、三个不同 evaluator、capsule/input/routing 指纹和未访问仓库/隐藏期望声明；部署 owner 已消费并返回 `valid=true`。
- `docs/handoff.md` 仍是唯一接手状态入口；`docs/plan.md` 只登记项目级方向、完成结论和重开条件，详细事实留在本交付链，没有复制历史实现。

## 任务与验证闭合

| 任务 | 结果 | 直接验证 |
| --- | --- | --- |
| T001-HANDOFF | 当前恢复索引的功能阶段候选 | 状态、回滚、边界、下一入口、链接与 993-token 中间候选读回；T004 以最终发布/候选身份重验为 1,247 tokens |
| T002-RULE-AUDIT | 逐项审计与候选 | 静态 76 cases、34 strict routing、5 strict references；Routing 76/76 |
| T003-VERIFY | 三阶段证据与部署候选 | staged 76/76/19，`Validate valid=true`，同 tokenizer 对照 |
| T004-DELIVER | 项目计划、handoff、完成审计与 Git 交付 | `results/T004-DELIVER.r4.json`；最终状态、链接、Token、发布边界与 `origin/main` 0/0 读回 |

Policy 单次候选结果比已发布基线多 3 个未声明但未禁选的 `model_interaction_surface` 标签；正式期望与禁选全部满足，差异所对应的交互面条款本次未修改，不能形成候选导致退化的因果证据。该限制已在[验证记录](verification.md)保留，不反复运行筛选结果，也不改写 oracle。

## 完成判定

最终 `completion-context` 快照 `sha256:d9e6a126693be29b4981ad19c200e7f39f6fffaa6235cc802dd49510bd58c3fd` 单页覆盖全部 7 个目标和 2 个约束；每个目标都有当前结果和验证，4 个任务均为 `done`，没有 DCR、分页缺失、未决结果或已失效上游。结合上述 owner、消费者、路由、恢复、Token、部署和 Git 证据，当前范围已完成。真实 Codex 继续停留在已发布基线，直到用户另行批准一次新的 Publish。
