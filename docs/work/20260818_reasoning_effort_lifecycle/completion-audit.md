# 推理深度生命周期：完成审计

## 目标证据

| 目标 | 当前结果与直接证据 | 判定 |
| --- | --- | --- |
| REQ-001 可靠调节 next-turn 深度 | 设置、下一轮生效和 Goal 续轮已按真实实验拆分；规则、skill 与脚本分别接入正式 owner | 满足 |
| AC-001 无 Goal 自主临时切换 | 全局规则与 skill 明确不要求 active Goal 或另行授权；严格 `no-goal-reasoning-shift` 独立路由通过 | 满足 |
| AC-002 用户固定深度优先 | 根需求、全局规则、skill 和 `user_reasoning_override` Policy 标签共同覆盖范围、期限、解除、额度动机无需验证和失败边界；正向及固定后禁切场景通过 | 满足 |
| AC-003 长对话结构读回 | 固定 tail 已退出；结构扫描器覆盖真实 JSON 路径、转义、嵌套和分块，10 MiB fake IPC 与约 19.2 MB 真实线程均读回正确 | 满足 |
| AC-004 模型/机器双视图 | 默认 30-character 回执只含当前动作证据，machine 599-character 完整 JSON 保留诊断；两者共享 canonical receipt，8 项测试通过 | 满足 |
| AC-005 负担判断不被内容路由或转换成本掩盖 | 全局入口先判断目标；skill 分别门控状态与设置；长探索、短任务、已有充分读回、无 Goal 错配和显式短查询均有严格独立场景 | 满足 |
| UDES-001 设置与 Goal 解耦 | Goal 只承担本来需要的跨轮续跑；skill 明确不为切换创建临时 Goal | 满足 |
| UDES-002 用户固定档位优先 | 用户覆盖在全局预加载规则和 skill 执行协议中均先于自主判断 | 满足 |
| UDES-003 先开发验证 | 仓库候选与 `Validate` 已完成，没有真实 Publish | 满足 |

## 约束与影响闭合

- CON-001：临时基线和用户覆盖只存在于当前对话指令与经验证回执；任务表、Goal、Hook、项目文件和脚本均未新增状态源。基线证据丢失时规则要求不猜测或虚假声称恢复。
- CON-002：部署 `Validate` 只读验证候选；每次真实 Codex 发布仍需新的用户明确同意，本审计不把此前发布授权继承到本版本。
- 项目需求 owner 已新增 AC-048/AC-049；`global/AGENTS.md` 持有跨项目优先级和动态选择不变量，`reasoning-governor` 持有 next-turn 生命周期、命令和成功合同，Node/PowerShell 脚本持有 IPC 与视图实现，没有同责入口。
- `global/README.md`、`reasoning-governor/agents/openai.yaml`、Delivery Workflow 和 Task Table Manager 的实际引用已同步；任务文件继续不能固定线程设置，用户明确覆盖则保持优先。
- 内容型领域 skill、计划和 Goal 不再承担目标档位判断；全局规则拥有前置不变量，governor description 拥有触发边界，正文拥有查询与设置收益协议，conversation state 仍是唯一配置证据，没有新增缓存或状态源。
- Delivery Workflow 与 Task Table Manager 仍只把推理深度委托给 governor、不保存线程设置；其现有引用未复制查询或收益算法，语义继续有效，无需随本次 owner 扩展重复修改。
- 路由静态 oracle、三个 detached evaluator、合并 evidence 和部署 validator 均消费新候选；严格 Routing 没有用 Policy 的宽松兼容诊断替代。
- 没有改变 `source_snapshot` 表示、插件迁移、远程 CI、其他工具输出或真实 Codex 安装内容。

## 完成判定

组件行为、当前真实线程、默认/机器消费者视图、目标—查询—设置成本分层、全局与 skill 规则、直接引用、静态路由、三阶段独立证据和部署候选均已形成闭环，没有适用验证失败，也没有仍依赖旧“Goal 是设置前提”或“内容路由会自然触发档位判断”语义的当前消费者。当前范围作为未发布仓库候选已完成；真实 Codex 继续使用上一次已发布内容，直到用户针对新一次 `Publish` 明确同意。
