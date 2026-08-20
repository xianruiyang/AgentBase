# 增量独立路由验证完成审计

## 目标复核

- `REQ-001 / AC-001..003`：三阶段身份只绑定 evaluator 可见语义；隐藏 oracle 单独复验，协议未知时扩大失效。指纹、capsule 与 planner 回归直接覆盖。
- `REQ-002 / AC-004..005`：model/machine planner、Routing/Policy 并行和 References 延后判断已经进入正式 refresh；真实最终 generation 只运行一个阶段，未变化再次调用为零运行。
- `REQ-003 / AC-006..008`：用户 npm 原生 CLI、临时 home/work/runtime、只读认证硬链接、单模型目录、禁用能力、Begin/Finish、分类限额、收据绑定、同代与跨代中断恢复均有确定性或真实运行证据。
- `REQ-004 / AC-009..010`：统一入口覆盖 22 个脚本和 6 组套件，测试边界机械禁止 evaluator；部署 Validate 与真实 Publish 已接入，Status 与沙箱重复 Publish 不触发模型或重复整套回归。
- `UDES-001`：独立质量边界保留，planner、复用和恢复减少无关运行；同口径 Token 测量与真实 receipt 分开报告。
- `UDES-002`：subagent 与独立子进程并不等价，package-identity 权限问题已通过官方用户 npm CLI 和绝对原生路径解决，正式评估继续使用隔离子进程。
- `UDES-003`：交付不是一次性成功 evidence；统一确定性入口、模型禁用测试边界、增量 refresh、崩溃续传和部署消费者共同构成长期基础设施。

## 约束与影响闭包

- `CON-001` 满足：只安装了用户授权范围内为独立验证所需的 Codex CLI；完成仓库实现、独立评估和 Validate，未 Publish。
- 正式消费者已闭合：项目 AGENTS、根与组件 README、Windows bootstrap、部署 Validate/真实 Publish、当前 evidence/attempt ledger 和私有仓库真源使用同一职责；bootstrap 与 evaluator 共同消费唯一 npm 原生路径 owner，WindowsApps 不再是 runner 候选，subagent 未成为第二评估入口。
- staging、lock、临时 home、原始 JSONL 和测试输出均为忽略或清理的可重建状态；`current.json` 与 `attempts.json` 是正式证据 owner，没有新增双向同步真源。

## 完成结论

当前确认范围已完成并验证：评估基础设施有统一零模型回归入口，模型评估按可见语义增量、可审计且可恢复，权限、失败分类和部署消费者已经闭合。没有开放 DCR 或适用验证失败；真实 srcq 升级与 Codex Publish 属于用户暂停或需逐次授权的后续状态转换，不是本子计划未完成项。
