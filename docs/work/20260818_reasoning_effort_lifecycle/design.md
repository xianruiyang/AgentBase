# 推理深度生命周期：目标设计

## DES-001 用户约束与模型临时选择形成单一优先级

- 状态: confirmed
- 满足: REQ-001, AC-001, AC-002, UDES-001, UDES-002

当前对话中用户明确指定的档位和期限是唯一用户覆盖层；在其有效期内禁用自主升降。没有用户覆盖时，模型按下一段工作的不确定性、后果、可逆性和验证负担选择最低充分等级。当前 IPC 配置只是可读写运行状态，不自行证明用户固定意图。

## DES-002 设置、下一轮生效与续轮分别承担独立职责

- 状态: confirmed
- 满足: AC-001, UDES-001, CON-001

`reasoning-governor` 先读回当前 next-turn 配置，仅在目标不同后写入并再次读回；写入不能改变已开始的当前轮，因此成功后结束当前轮。active Goal 可以自然拉起下一轮；没有 Goal 时等待下一次自然用户消息。自主配置在当前工作闭合或判断负担再次变化时恢复经验证基线或选择紧邻已知工作的最低充分等级，不把短期档位升级为长期偏好。

## DES-003 conversation state 由增量结构扫描器读取

- 状态: confirmed
- 满足: AC-003

小帧继续完整 `JSON.parse`；超过正常帧上限时，脚本逐字节维护 JSON 容器、对象键、字符串转义和标量状态，只捕获 snapshot 判定、线程身份及 `params.change.conversationState.latestThreadSettings.effort` 所需的短路径和值。对话正文即使包含同名文本仍处于 JSON 字符串内，不参与结构路径匹配；扫描内存只随嵌套深度和少量目标字段增长。

## DES-004 同一 canonical receipt 投影两种消费者视图

- 状态: confirmed
- 满足: AC-004

IPC 读写函数继续返回完整 canonical 对象。CLI 默认输出单行紧凑模型视图，只保留 `ok`、操作、有效档位以及失败时的原因和必要恢复信息；`--view machine` 输出完整 JSON。PowerShell 入口传递同一显式视图，不复制成功判断。

## DES-005 规则、skill、交付引用和路由证据共同消费新合同

- 状态: confirmed
- 满足: REQ-001, AC-001, AC-002, AC-003, AC-004

项目根需求定义长期结果；`global/AGENTS.md` 只保留跨项目优先级与自主选择不变量；`reasoning-governor` 正文拥有具体生命周期和命令；脚本拥有 IPC 与输出投影；`global/README.md`、Delivery Workflow 引用、静态合同和路由用例作为实际消费者同步更新并重验。

## DES-006 推理档位是独立于内容路由的前置控制

- 状态: confirmed
- 满足: REQ-001, AC-005

`global/AGENTS.md` 在 skill 正文尚未加载前要求模型先按下一段实质工作的判断负担形成目标档位；领域 skill、计划和 Goal 只提供工作事实或续轮能力，不替代该判断。`reasoning-governor` 再分别裁决状态查询和实际设置：查询只补足会改变动作的当前配置证据，设置还必须比较剩余工作收益与当前轮中断、无 Goal 续轮等待及恢复成本。当前上下文中同一线程、此后无设置或已知变化的最近验证读回可以复用，不建立持久缓存。
