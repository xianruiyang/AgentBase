# 推理深度生命周期：现状分析

## OBS-001 设置写入不发送 turn，Goal 只提供续轮

- 状态: confirmed
- 证据: 2026-08-18 当前 Codex 真实线程的 max→high→max 实验及真实 turn context；OpenAI 官方 Goal 与模型指南
- 关联: DES-002

两次设置回执均为 `updateAccepted=true`、`readbackVerified=true`、`matchesRequestedEffort=true`、`sentTurn=false`；当前轮保持原档位，随后被 Goal 拉起的真实下一轮分别采用 high 与 max。历史同一线程也存在无 Goal 的配置变化，证明 Goal 不是设置前提。官方资料把 reasoning effort 定义为应按工作负载有意选择的配置，把 Goal 定义为跨轮持续执行的 durable objective，与实验边界一致。

## OBS-002 现有规则把三个机制错误合并

- 状态: confirmed
- 证据: `global/AGENTS.md` 与 `skills/reasoning-governor/SKILL.md`
- 关联: DES-001, DES-002

全局规则和 skill 当前都只允许 active Goal 中自主切换，并把 Goal 称为唯一续跑承载；这把设置权限、next-turn 生效时点和自动续轮混成一个条件，使无 Goal 场景即使判断负担变化也不会调用已存在的设置入口。

## OBS-003 固定尾部读取在当前长线程产生可重复误判

- 状态: confirmed
- 证据: 2026-08-18 仓库脚本对当前线程的真实 `status` 运行
- 关联: DES-003

当前 snapshot 为 19,062,770 bytes，脚本返回 `readbackVerified=false`、`currentConfiguredEffort=null` 且没有传输错误。实现只在超过 8 MiB 后保留 4 KiB 前缀与 4 MiB 尾部；已由完整解析确认存在的 `latestThreadSettings.effort` 位于被丢弃中段，因此失败是读取算法误判，不是宿主缺字段。

## OBS-004 默认回执包含模型当前动作不需要的机器字段

- 状态: confirmed
- 证据: 同一次真实 `status` 输出与仓库脚本返回结构
- 关联: DES-004

默认输出包含 method、transport、threadId、pipePath、client id、snapshot bytes、多个固定 false/null 字段及重复验证语义。仓库没有发现这些默认字段的程序消费者；skill 直接把该输出交给模型，而机器诊断仍需要显式完整视图。

## GAP-001 无 Goal 的自主调节与用户固定优先级尚未进入正式 owner

- 状态: confirmed
- 关联: AC-001, AC-002, DES-001, DES-002, OBS-001, OBS-002

现有跨项目规则与 skill 同时缺少已验证的设置/续轮解耦，也只用一句“用户固定时保持”表达优先级，未覆盖范围、期限、额度动机无需审查和不得自主恢复等关键边界。

## GAP-002 长帧读回机制不能覆盖真实长对话

- 状态: confirmed
- 关联: AC-003, DES-003, OBS-003

固定尾部窗口不能保证字段位置，扩大窗口只会延后同一失败并继续把文本命中当成结构猜测；必须在 owner 内改为有界的结构扫描。

## GAP-003 模型默认输出尚未按当前消费者投影

- 状态: confirmed
- 关联: AC-004, DES-004, OBS-004

canonical receipt 同时被当作模型默认显示和机器诊断协议，违背项目已经确认的模型/机器双视图合同，并在每次状态检查和设置读回中重复消耗上下文。

## OBS-005 内容型 skill 路由漏掉了负担型档位控制

- 状态: confirmed
- 证据: 当前对话中较长的 skill 生命周期探索及随后用户追问；工具调用记录没有 `reasoning-governor -Status` 或设置操作
- 关联: DES-006

该工作同时包含真实会话取证、平台合同、压缩机制、跨 owner 设计、Token 对照和三阶段独立验证，事后按现有四项负担标准应先把目标档位判断为 `high`。执行时只选择了内容直接相关的治理、交付和 PowerShell skill，并未经读回便沿用当前档位。随后真实 `-Status` 证明线程当前为 `max`，所以无法反推当时一定需要设置；直接成立的失败是没有进行目标判断与状态检查裁决。

## GAP-004 “需要变化才使用”形成循环跳过

- 状态: confirmed
- 关联: AC-005, DES-006, OBS-005

全局规则要求“需要变化才使用” governor，但没有在 skill 选择前分离目标档位判断、当前状态证据和切换收益。模型可以因为尚未读回而声称不能确认需要变化，再以未确认变化为由跳过 governor；同时若改成每轮固定 `-Status`，又会让短小当前轮任务承担不能产生收益的查询成本。
