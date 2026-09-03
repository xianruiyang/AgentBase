# 推理深度生命周期：方案设计

## SOL-001 在规则 owner 中建立用户覆盖与自主临时调节合同

- 状态: confirmed
- 解决: GAP-001
- 满足: DES-001, DES-002, AC-001, AC-002

修订项目根需求、全局内核和 `reasoning-governor`：用户明确档位在其范围内优先，未给结束点则直到明确变更或释放；没有用户覆盖时模型可在有无 Goal 的任意场景按真实判断负担设置 next-turn 深度。成功设置后结束当前轮，Goal 仅在已经承担长期执行时续轮；不为切换建立任务表、Hook、文件状态或第二配置源。

## SOL-002 用增量结构扫描替代大帧尾部猜测

- 状态: confirmed
- 解决: GAP-002
- 满足: DES-003, AC-003

在现有 Node IPC owner 内删除固定 tail 读取分支，加入只匹配真实 JSON 路径的有界扫描器。回归覆盖字段位于大帧中段、正文中的伪同名文本、关键键跨 chunk、null 设置、小帧原路径和真实当前线程读回。

## SOL-003 为回执增加默认模型视图与显式机器视图

- 状态: confirmed
- 解决: GAP-003
- 满足: DES-004, AC-004

CLI 默认输出紧凑单行模型回执；`--view machine` 保留完整 JSON。失败模型视图返回可区分的 update rejection、readback unavailable 或 mismatch 及必要实际值；PowerShell wrapper 与 skill 命令同步视图合同，canonical 结果与成功判定保持一个实现。

## SOL-004 同步消费者并完成独立候选验证

- 状态: confirmed
- 解决: GAP-001, GAP-002, GAP-003
- 满足: DES-005, CON-002

更新 `global/README.md`、Delivery Workflow 引用、静态断言及正向/相近非触发路由用例；运行 Reasoning Governor 组件测试、当前真实线程只读状态、全局 skill 静态合同、detached Routing/Policy/References 和部署 `Validate`。本轮不执行真实 Publish。

## SOL-005 分离目标判断、状态查询和实际切换

- 状态: confirmed
- 解决: GAP-004
- 满足: DES-006, AC-005

在 `global/AGENTS.md` 把目标档位判断设为下一段实质工作前、独立于内容型 skill、计划和 Goal 的控制；在 `reasoning-governor` description 用“档位错配可能实质影响质量或总体成本”触发正文，并明确短小当前轮任务不触发。正文先判断目标，再只为可能改变动作的未知状态运行 `-Status`，最后仅在剩余工作收益超过设置、结束当前轮、续轮等待与恢复成本时设置。路由同时覆盖长探索与治理 skill 共存、无 Goal 的真实错配、已有充分读回和短任务不查询，避免用固定状态检查替代漏判修复。

## SOL-006 为自主配置转换加入阶段迟滞

- 状态: implemented
- 解决: GAP-005
- 满足: DES-007, AC-006, UDES-004

保持下一段实质工作前的目标判断，但在全局内核与 `reasoning-governor` 的触发、输入和收益合同中加入“后继阶段可预期长期保持不同判断负担”。严格路由分别覆盖长期阶段可切换、孤立高难项不切换、短机械尾段不切换和已有匹配读回不查询；不增加计数器、阶段文件或固定时长阈值。

## SOL-007 只为已知后继轮查询 next-turn 配置

- 状态: completed
- 解决: GAP-006
- 满足: AC-001, AC-005, AC-006

目标档位仍在每段实质工作前独立判断，但自主 `Status` 与设置共同要求同一工作的已知后继轮会消费配置。active Goal 可承担自动续轮；无 Goal 仍可自主设置，但必须已明确下一次自然用户消息会继续同一长期阶段，设置后结束当前轮等待。当前请求能在已开始的一轮闭合或没有明确后继轮时不加载 governor、不查询、不预设未知未来。

同步改写无 Goal 正例以明确等待边界，并增加一个中等多文件替换仍在当前轮闭合的非触发场景；不引入 Goal、Hook、缓存、计时器、固定文件数或新的配置状态。
