# 增量独立路由验证完成审计

## 目标复核

- `REQ-001 / AC-001..003`：三阶段身份只绑定 evaluator 可见语义；隐藏 oracle 单独复验，协议未知时扩大失效。指纹、capsule 与 planner 回归直接覆盖。
- `REQ-002 / AC-004..005`：model/machine planner、Routing/Policy 并行和 References 延后判断已经进入正式 refresh；真实最终 generation 只运行一个阶段，未变化再次调用为零运行。
- `REQ-003 / AC-006..008`：用户 npm 原生 CLI、临时 home/work/runtime、只读认证硬链接、单模型目录、禁用能力、Begin/Finish、分类限额、收据绑定、同代与跨代中断恢复均有确定性或真实运行证据。
- `REQ-004 / AC-009..010`：统一入口覆盖 22 个脚本和 6 组套件，测试边界机械禁止 evaluator；该入口只服务路由研究基础设施。部署以快速确定性 payload 合同和受管资产生命周期闭环，不读取、要求或记录模型 evidence。
- `UDES-001`：独立质量边界保留，planner、复用和恢复减少无关运行；同口径 Token 测量与真实 receipt 分开报告。
- `UDES-002`：subagent 与独立子进程并不等价，package-identity 权限问题已通过官方用户 npm CLI 和绝对原生路径解决，正式评估继续使用隔离子进程。
- `UDES-003`：交付不是一次性成功 evidence；统一确定性入口、模型禁用测试边界、增量 refresh、崩溃续传及其与部署职责的明确分离共同构成长期基础设施。

## 约束与影响闭包

- `CON-001` 在原实施周期满足并已被后续授权替代：当时只安装独立验证所需的 Codex CLI，完成仓库实现、独立评估和 Validate，没有向真实 Codex 根部署。
- 正式消费者已闭合：项目 AGENTS、根与组件 README、Windows bootstrap、路由研究入口、部署 Validate/Deploy/Status 和私有仓库真源按职责分层；bootstrap 与 evaluator 共同消费唯一 npm 原生路径 owner，WindowsApps 不再是 runner 候选，subagent 未成为第二评估入口。
- staging、lock、临时 home、原始 JSONL 和测试输出均为忽略或清理的可重建状态；`current.json` 保存上一份完成快照，`attempts.json` 保存当前 generation 的 2/6 份失败收据，二者在 merge 前按合同允许不同代且不进入 payload、部署清单或安装状态。

## 完成结论

当前基础设施与部署职责范围已完成并验证：评估基础设施有统一零模型回归入口，模型评估按可见语义增量、可审计且可恢复；模型采样不再拥有其无法可靠证明的部署裁判权。schema 9 部署只消费确定性 payload 与受管资产生命周期，schema 8 及更早历史仍可读回和回滚。当前模型研究仍有两份明确的 oracle 失败、没有成功合并到 `current.json`；它们是待后续研究处理的结果证据，不是基础设施、部署合同或本次安装失败，也不再阻断本范围完成。
