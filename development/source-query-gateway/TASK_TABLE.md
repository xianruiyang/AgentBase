# 统一源码查询网关分支

> 本文件由 taskctl 生成，只是任务合同与状态的可重建视图，不表示允许执行或产品完成。

## 状态统计

| 状态 | 数量 |
| --- | ---: |
| todo | 1 |
| claimed | 0 |
| in_progress | 0 |
| review | 0 |
| blocked | 0 |
| done | 50 |
| retired | 1 |

## 复核与结果

- 需复核任务：0
- 当前可读取结果：50
- 含验证结果：50
- 含未决结果：8
- 合同修订后陈旧结果：0

## 上游状态

- 用户确认快照：protected
- 可修订上游未决：2
- 延后讨论项：1

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
| TSQG-031 | done | codex-root | 实现 rg 自适应结果表示 | TSQG-005:hard, TSQG-030:hard | results/TSQG-031.r12.json | 1 |
| TSQG-032 | done | codex-root | 覆盖 rg 公开模式 | TSQG-002:hard, TSQG-030:hard | results/TSQG-032.r4.json | 1 |
| TSQG-033 | done | codex-root | 消除候选对 Python rg 回执的依赖 | TSQG-030:hard, TSQG-032:hard | results/TSQG-033.r4.json | 1 |
| TSQG-040 | done | codex-root | 复核 AST 公开入口 | TSQG-011:hard, TSQG-023:hard, TSQG-032:hard | results/TSQG-040.r4.json | 1 |
| TSQG-041 | done | codex-root | 裁决 AST 公共原语复用 | TSQG-040:hard | results/TSQG-041.r4.json | 1 |
| TSQG-042 | done | codex-root | 完成三后端诊断、来源与 Windows CLI 生命周期 | TSQG-022:hard, TSQG-032:hard, TSQG-041:hard | results/TSQG-042.r12.json | 2 |
| TSQG-043 | done | codex-root | 原子迁移 Source Query Gateway 正式身份 | TSQG-042:hard | results/TSQG-043.r4.json | 1 |
| TSQG-050 | done | codex-root | 建立只消费 PATH srcq 的统一查询候选 skill | TSQG-023:hard, TSQG-033:hard, TSQG-043:hard | results/TSQG-050.r8.json | 3 |
| TSQG-051 | done | codex-root | 迁入 AST skill 语义 | TSQG-050:hard | results/TSQG-051.r8.json | 2 |
| TSQG-052 | done | codex-root | 迁移正式消费者并退出旧入口 | TSQG-043:hard, TSQG-050:hard, TSQG-051:hard | results/TSQG-052.r7.json | 2 |
| TSQG-053 | done | codex-root | 闭环独立 srcq 发布与精简 Skill payload | TSQG-052:hard | results/TSQG-053.r19.json | 3 |
| TSQG-054 | done | codex-root | 冻结 LSP 渐进暴露基线 | TSQG-050:hard | results/TSQG-054.r3.json | 1 |
| TSQG-055 | done | codex-root | 验证 Codex 原生延迟 MCP 工具发现 | TSQG-054:hard | results/TSQG-055.r3.json | 1 |
| TSQG-056 | done | codex-root | 闭环 LSP 渐进模型入口 | TSQG-055:hard, TSQG-043:hard | results/TSQG-056.r3.json | 1 |
| TSQG-060 | done | codex-root | 运行候选影响验证 | TSQG-053:hard | results/TSQG-060.r12.json | 1 |
| TSQG-061 | done | codex-root | 运行 detached 路由行为评估 | TSQG-050:hard, TSQG-052:hard | results/TSQG-061.r10.json | 1 |
| TSQG-062 | done | codex-root | 运行受监控 Codex 对照 | TSQG-006:hard, TSQG-060:hard, TSQG-061:hard | results/TSQG-062.r8.json | 2 |
| TSQG-063 | done | codex-root | 裁决候选收益边缘 | TSQG-062:hard | results/TSQG-063.r6.json | 2 |
| TSQG-064 | retired | codex-root | 请求当次 Codex 发布裁决 | TSQG-065:hard | — | 3 |
| TSQG-065 | done | codex-root | 逐项完成审计 | TSQG-062:hard, TSQG-063:hard | results/TSQG-065.r3.json | 1 |
| TSQG-066 | done | codex-root | 强化 srcq 安装状态与 Codex 发布前置门禁 | TSQG-053:hard | results/TSQG-066.r6.json | 1 |
| TSQG-067 | done | codex-root | 冻结全部模型可见输出族的字段准入合同 | — | results/TSQG-067.r3.json | 1 |
| TSQG-068 | done | codex-root | 建立 model、machine 与 native 输出边界 | TSQG-067:hard | results/TSQG-068.r4.json | 1 |
| TSQG-069 | done | codex-root | 收敛 fd 与 rg 的模型证据格式 | TSQG-068:hard | results/TSQG-069.r4.json | 1 |
| TSQG-070 | done | codex-root | 收敛 AST 与辅助命令的模型证据格式 | TSQG-068:hard | results/TSQG-070.r4.json | 1 |
| TSQG-071 | done | codex-root | 迁移模型输出消费者与按需协议 | TSQG-069:hard, TSQG-070:hard | results/TSQG-071.r4.json | 1 |
| TSQG-072 | done | codex-root | 验证根因修正后的查询身份并运行受影响隔离对照 | TSQG-081:hard | results/TSQG-072.r14.json | 3 |
| TSQG-073 | done | codex-root | 审计模型输出收敛并裁决采纳 | TSQG-072:hard | results/TSQG-073.r4.json | 1 |
| TSQG-074 | done | codex-root | 建立 srcq 统一接管的 rg/fd 原生直觉入口 | TSQG-071:hard | results/TSQG-074.r3.json | 4 |
| TSQG-075 | done | codex-root | 实现真实结果后的自适应模型投影 | TSQG-074:hard | results/TSQG-075.r3.json | 2 |
| TSQG-076 | done | codex-root | 内化默认上下文预算与精确续页 | TSQG-075:hard | results/TSQG-076.r3.json | 1 |
| TSQG-077 | done | codex-root | 迁移消费者并冻结 srcq 接管后的输出身份 | TSQG-075:hard, TSQG-076:hard | results/TSQG-077.r7.json | 2 |
| TSQG-078 | done | codex-root | 以实际输出能力取代后端版本许可 | TSQG-077:hard | results/TSQG-078.r4.json | 1 |
| TSQG-079 | done | codex-root | 固化普通查询最小语法与定向错误恢复 | TSQG-078:hard | results/TSQG-079.r4.json | 1 |
| TSQG-080 | done | codex-root | 把 AST 与 LSP 升级改为证据缺口驱动 | TSQG-077:hard | results/TSQG-080.r4.json | 1 |
| TSQG-081 | done | codex-root | 接入三项根因修正并冻结新测试 identity | TSQG-078:hard, TSQG-079:hard, TSQG-080:hard | results/TSQG-081.r4.json | 1 |
| TSQG-082 | todo | — | 审计高成本证据轮次并裁决最小修正层 | TSQG-073:hard | — | 1 |
