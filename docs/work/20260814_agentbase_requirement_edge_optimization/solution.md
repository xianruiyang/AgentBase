# AgentBase 根需求收益边缘持续优化：方案设计

## SOL-001 将协作洞察与优化优先级接入运行时规则

- 状态: confirmed
- 来源: GAP-001 的职责裁决
- 解决: GAP-001
- 依赖: DES-001, DES-002

在 `global/AGENTS.md` 以最低充分文字重写目标形成与方案选型规则：初始表达是洞察和共同校准的输入，用户保留最终裁决；质量是 Token 与速度优化的前置条件。在 `delivery-workflow` 的核心步骤和最终完成合同中承接复杂交付的需求洞察与持续防偏离。同步维护触发/行为评估与 README 摘要，但不复制完整需求或新增 CLI 状态。通过静态合同、skill 校验、独立路由行为评估和正式发布读回验证。

## SOL-002 无损精炼全局常驻内核

- 状态: confirmed
- 来源: GAP-002 的逐条职责审查
- 解决: GAP-002
- 依赖: DES-001, DES-002

只在 `global/AGENTS.md` 内合并同一规范事实、删除已被上位原则完整蕴含的重复条款并压缩不改变动作的措辞；保留所有独立的目标、证据、授权、skill 路由、机械门禁、修改、验证、记录和交付边界。同步更新静态合同所引用的最低充分语义片段，以既有 57 个行为/路由用例和新 detached 独立评估证明触发边界未退化，再发布并读回。目标不是追求最短，而是恢复常驻规则容量并降低每任务固定 Token。

## SOL-003 收敛 skill 路由权威到 description

- 状态: confirmed
- 来源: GAP-003 的权威入口裁决
- 解决: GAP-003
- 依赖: DES-001, DES-002

删除 `global/AGENTS.md` 中逐项复制的 skill 触发表，保留一条跨项目路由不变量：用户指定或任务满足可用 skill 的 `description` 时使用，description 同时定义触发与非触发边界，多个适用时选择覆盖动作的最小充分集合。各 skill 继续独立拥有具体边界；静态合同继续逐个检查 description，detached capsule 继续绑定全部 skill 正文，并用相同 57 个正向、非触发、组合和策略场景做独立盲评。跨 skill 的具体协调调用只有存在独立消费关系时保留，不视为通用触发表。

## SOL-004 让独立评估匹配真实渐进加载顺序

- 状态: confirmed
- 来源: GAP-004 的证据职责裁决
- 解决: GAP-004
- 依赖: DES-001, DES-002, SOL-003

首次路由 capsule 只提供全局规则、skill description、外部 skill 摘要、标签定义和请求，评估 skill、外部 skill 与粗粒度标签，禁止提前选择治理引用。通过首次隐藏 oracle 校验后，从该结果实际选中的 `change-governance` 用例生成第二个 capsule，只提供治理 skill 正文和可用引用名称，由新的隔离运行选择引用。合并入口在两阶段分别验证身份、输入声明、用例全集和隐藏期望后生成唯一 `evidence/current.json`；部署继续只消费该文件。候选哈希仍覆盖完整 skill 与 metadata，任何正文变化都会使两阶段证据失效。

## SOL-005 分离路由、规则行为与后置引用的证明职责

- 状态: confirmed
- 来源: GAP-005 的证据职责裁决
- 解决: GAP-005
- 依赖: DES-001, DES-002, SOL-004

首次路由 capsule 只提供全局规则、项目与外部 skill description、请求和可用外部 skill 集合，只输出 skill 选择；不包含行为标签名称、定义或引用字段。首次结果通过隐藏路由 oracle 后，单独生成策略 capsule，只提供始终可见的全局规则、请求和行为标签定义，并用首次 capsule 身份绑定评估顺序，输出粗粒度行为标签；不把任何案例的已选 skill 正文暴露给其他案例。治理引用继续在第三个 capsule 中只读取已选 `change-governance` 正文。合并入口分别验证三阶段身份、输入声明、用例全集和隐藏预期后生成唯一 `evidence/current.json`。三阶段共享同一完整候选哈希，使任何全局、skill 或 metadata 变化都会让整份证据失效，但各阶段的可见输入不跨越真实职责边界。

路由 oracle 只约束首次动作实际需要加载的 skill，不把 skill 正文中声明的后续条件性协同提前算作首次选择；`full-delivery-chain` 因此由 `delivery-workflow` 与 `task-table-manager` 启动，只有到最终跨契约复核时才由交付 skill 的正式规则触发 `change-governance`。

评估时间身份按可解析 ISO-8601、零 UTC offset 和非未来时间验证，同时接受等价的 `Z` 与 `+00:00` 表示；不把字面序列化偏好升级为发布硬门禁。

行为 oracle 按动作职责保持正交：`architecture_integrated` 只用于把行为接入正确长期 owner/正式入口，`impact_closure` 只用于既有共享或权威契约变化后的消费者与派生结果闭合；请求只命中后者时不强制前者。
