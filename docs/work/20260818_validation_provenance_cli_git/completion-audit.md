# 验证溯源、CLI 帮助与 Git 基线：完成审计

## 目标与证据

| 目标 | 直接结果 | 判定 |
| --- | --- | --- |
| REQ-001 正式验证不能原样刷成功 | 正式 merge 逐阶段登记；失败有有界分类，相同输入的新结果需显式理由且最多一次，当前成功结果必须匹配通过收据 | 满足 |
| REQ-002 二级帮助独立指导调用 | 所有子命令参数具有非空 help；context、completion-context、complete 解释预算、CAS、收据、快照并给出示例 | 满足 |
| REQ-003 形成私有 Git 基线 | 核心实现提交 `5814dca` 已非强制推送 `origin/main`；状态文档由后续独立提交维护 | 满足 |
| CON-001 不再次发布 | 只读 Status 报告当前源码未发布，本轮没有调用 Publish | 满足 |

## 职责与消费者闭合

- `merge_routing_evidence.ps1` 仍是唯一正式合并入口，`record_routing_attempt.ps1` 只承担它共享的阶段接收与收据职责；没有第二份当前成功 evidence。
- `evidence/attempts.json` 是机器审计真源，`current.json` 是当前成功证据真源。部署 Validate 只检查匹配关系和重试边界，不把尝试历史当成行为正确 oracle。
- 当前三阶段结果通过 baseline 迁移接入；更早失败没有被伪造。后续相同输入最多两次的门禁已由原失败、同类变体、幂等复用和跨阶段身份场景覆盖。
- taskctl 参数帮助与 parser 同源；测试读取真实 parser 和 CLI 输出，没有另建需要同步的参数说明表。
- 插件 payload、直接兼容部署 Validate、部署回归和当前路由证据均重新验证；真实 Codex 安装保持旧发布状态，未产生越权同步。

## 完成判定

REQ-001—REQ-003、AC-001—AC-004 与 CON-001 均有直接证据，失败尝试 owner、部署消费者、CLI parser、Git 源码身份和未发布边界已经闭合，没有适用失败或开放实施项。baseline 的历史起点和 custom agent 真实宿主质量仍是明确证据边界，不反转本次完成结论。
