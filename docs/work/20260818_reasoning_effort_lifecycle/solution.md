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
