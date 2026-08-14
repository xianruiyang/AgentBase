# 统一源码查询网关分支

> 本文件由 taskctl 生成，只是任务合同与状态的可重建视图，不表示允许执行或产品完成。

## 状态统计

| 状态 | 数量 |
| --- | ---: |
| todo | 4 |
| claimed | 0 |
| in_progress | 0 |
| review | 0 |
| blocked | 0 |
| done | 26 |
| retired | 0 |

## 复核与结果

- 需复核任务：0
- 当前可读取结果：26
- 含验证结果：26
- 含未决结果：1
- 合同修订后陈旧结果：0

## 上游状态

- 用户确认快照：protected
- 可修订上游未决：2
- 延后讨论项：0

## 任务

| ID | 状态 | Owner | 标题 | 依赖 | 结果 | 合同修订 |
| --- | --- | --- | --- | --- | --- | ---: |
| TSQG-001 | done | codex-root | 审核分支根本需求与设计约束 | — | results/TSQG-001.r3.json | 1 |
| TSQG-002 | done | codex-root | 冻结三个查询后端的精确版本与公开模式 | TSQG-001:hard | results/TSQG-002.r8.json | 1 |
| TSQG-003 | done | codex-root | 冻结当前 sgy AST 可观察合同 | TSQG-002:hard | results/TSQG-003.r3.json | 1 |
| TSQG-004 | done | codex-root | 登记历史总 Token 基线及证据边界 | TSQG-001:hard | results/TSQG-004.r4.json | 1 |
| TSQG-005 | done | codex-root | 建立绑定源码快照的正式 benchmark corpus | TSQG-004:hard | results/TSQG-005.r3.json | 1 |
| TSQG-006 | done | codex-root | 扩展唯一隔离 benchmark runner 与 monitor | TSQG-005:hard | results/TSQG-006.r4.json | 1 |
| TSQG-010 | done | codex-root | 裁决可跨 backend 复用的公共职责 | TSQG-003:hard | results/TSQG-010.r4.json | 1 |
| TSQG-011 | done | codex-root | 提取公共执行原语且保持 AST 行为 | TSQG-010:hard | results/TSQG-011.r4.json | 1 |
| TSQG-012 | done | codex-root | 建立 rg/fd EvidenceSignature 与 renderer | TSQG-011:hard, TSQG-005:hard | results/TSQG-012.r4.json | 1 |
| TSQG-013 | done | codex-root | 建立有界 spool、snapshot 与精确 cursor | TSQG-011:hard, TSQG-012:hard | results/TSQG-013.r4.json | 1 |
| TSQG-020 | done | codex-root | 实现 fd 命令闭环 | TSQG-002:hard, TSQG-011:hard | results/TSQG-020.r4.json | 1 |
| TSQG-021 | done | codex-root | 实现 fd 可逆目录树 | TSQG-012:hard, TSQG-020:hard | results/TSQG-021.r4.json | 1 |
| TSQG-022 | done | codex-root | 覆盖 fd 公开模式 | TSQG-002:hard, TSQG-020:hard | results/TSQG-022.r4.json | 1 |
| TSQG-023 | done | codex-root | 验证 fd 自适应表示 | TSQG-005:hard, TSQG-021:hard | results/TSQG-023.r4.json | 1 |
| TSQG-030 | done | codex-root | 实现 rg 命令闭环 | TSQG-002:hard, TSQG-011:hard, TSQG-012:hard | results/TSQG-030.r4.json | 1 |
| TSQG-031 | done | codex-root | 实现 rg 自适应结果表示 | TSQG-005:hard, TSQG-030:hard | results/TSQG-031.r4.json | 1 |
| TSQG-032 | done | codex-root | 覆盖 rg 公开模式 | TSQG-002:hard, TSQG-030:hard | results/TSQG-032.r4.json | 1 |
| TSQG-033 | done | codex-root | 消除候选对 Python rg 回执的依赖 | TSQG-030:hard, TSQG-032:hard | results/TSQG-033.r4.json | 1 |
| TSQG-040 | done | codex-root | 复核 AST 公开入口 | TSQG-011:hard, TSQG-023:hard, TSQG-032:hard | results/TSQG-040.r4.json | 1 |
| TSQG-041 | done | codex-root | 裁决 AST 公共原语复用 | TSQG-040:hard | results/TSQG-041.r4.json | 1 |
| TSQG-042 | done | codex-root | 完成三后端诊断与来源 | TSQG-022:hard, TSQG-032:hard, TSQG-041:hard | results/TSQG-042.r4.json | 1 |
| TSQG-050 | done | codex-root | 建立统一查询候选 skill | TSQG-023:hard, TSQG-033:hard, TSQG-042:hard | results/TSQG-050.r4.json | 1 |
| TSQG-051 | done | codex-root | 迁入 AST skill 语义 | TSQG-050:hard | results/TSQG-051.r4.json | 1 |
| TSQG-052 | done | codex-root | 准备消费者原子迁移 | TSQG-050:hard, TSQG-051:hard | results/TSQG-052.r4.json | 1 |
| TSQG-053 | done | codex-root | 形成候选供应链 payload | TSQG-052:hard | results/TSQG-053.r4.json | 1 |
| TSQG-060 | done | codex-root | 运行候选影响验证 | TSQG-053:hard | results/TSQG-060.r4.json | 1 |
| TSQG-061 | todo | — | 运行 detached 路由行为评估 | TSQG-050:hard, TSQG-052:hard | — | 1 |
| TSQG-062 | todo | — | 运行受监控 Codex 对照 | TSQG-006:hard, TSQG-060:hard, TSQG-061:hard | — | 1 |
| TSQG-063 | todo | — | 裁决候选收益边缘 | TSQG-062:hard | — | 1 |
| TSQG-064 | todo | — | 请求主线采纳与发布裁决 | TSQG-063:hard | — | 1 |
