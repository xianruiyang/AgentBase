# AgentBase 交付链十二轮审查与改进：方案设计

> 使用 `SOL-*` 和必要的 `DEC-*` 二级标题记录解决差距的动作、结果、依赖、风险和验证方式。

## SOL-001 第1轮：统一初始化与读取的工作流身份合同

- 状态: confirmed
- 轮次: 1
- 解决: GAP-001
- 满足: DES-002, AC-002
- 依赖: 无
- 风险: 不应修改已经有效的 ID，只在创建和读取边界拒绝空白文本
- 验证: 两个 init 均拒绝空白 ID/标题；workctl 读取被改坏的空白 workflow ID 时拒绝；正常自举与既有回归继续通过

在 `workctl` 与独立 `taskctl init` 写入前规范化并验证 ID、标题；在 `workctl.load_manifest` 与 `taskctl.load_table/load_workflow` 读回时验证对应身份字段，使任何成功创建的工作区都可被两个工具继续消费。

## SOL-002 第2轮：把文件系统异常收敛到 CLI 错误边界

- 状态: confirmed
- 轮次: 2
- 解决: GAP-002
- 满足: DES-003, AC-002
- 依赖: SOL-001 已形成可用初始化版本
- 风险: 只捕获可预期 `OSError`，不得吞掉编程错误或伪装验证成功
- 验证: 普通文件作为工作区时两个 CLI 均退出 2、stderr 是单个 JSON 且不含 traceback；全量单元回归继续通过

在两个正式 CLI 的顶层错误边界单独捕获 `OSError`，转换为带操作失败说明的领域输出；保留非文件系统编程异常的 traceback，使真实实现缺陷仍可见。

## SOL-003 第3轮：建立阻塞状态不变量并提供直观写法

- 状态: confirmed
- 轮次: 3
- 解决: GAP-003
- 满足: DES-004, AC-002
- 依赖: SOL-002 后的有界错误合同
- 风险: 状态损坏必须作为硬错误，但提供阻塞原因时不应要求模型重复填写显而易见的 status
- 验证: 非空 `--blocked-reason` 自动进入 blocked；blocked 无原因和非 blocked 有原因的损坏 state 均拒绝；显式离开 blocked 清除原因；全量 taskctl 回归通过

在 `validate_state` 统一校验 status/reason 不变量；`note` 在只提供非空 blocked reason 时自动设置 blocked。清空原因但未指定离开状态时返回有界错误，要求调用方明确恢复到 in_progress、review 或其他非阻塞状态。

## SOL-004 第4轮：为 argparse 建立 JSON 错误入口

- 状态: confirmed
- 轮次: 4
- 解决: GAP-004
- 满足: DES-005, AC-002
- 依赖: SOL-002 的顶层错误格式
- 风险: 不改变 `--help` 正常输出，也不把参数错误伪装成领域执行失败
- 验证: 未知参数、缺必需参数和非法 choice 在两个 CLI 中均为 exit 2 + 单 JSON + 无 usage；help 仍 exit 0；回归通过

用两个工具共享语义的 `JsonArgumentParser` 覆盖 argparse `error`，直接复用紧凑 JSON 输出；只改变错误路径，保留标准 help 行为。

## SOL-005 第5轮：为常用任务查询增加 ID 游标分页

- 状态: confirmed
- 轮次: 5
- 解决: GAP-005
- 满足: DES-006, AC-002, AC-003
- 依赖: SOL-004 使错误游标也返回 JSON
- 风险: `next` 排序会随状态变化；它是建议查询，不建立一致性快照，游标缺失时要求重新从第一页读取
- 验证: list/next/deps/dependents 以 limit 1 或 2 逐页遍历全部 ID，无重复无缺失；未知游标失败；原命令不带游标结果不变；回归通过

新增统一 `--after-id` 与 `next_after_id`；在命令完成既有筛选和排序后切页。游标必须命中当前结果集，否则明确要求从第一页重读，不用 offset 或隐式状态。

## SOL-006 第6轮：把用户确认来源纳入基线完整性

- 状态: confirmed
- 轮次: 6
- 解决: GAP-006
- 满足: DES-007, AC-003, UDES-001
- 依赖: SOL-005 后的当前查询版本
- 风险: 只验证基线已有的正式用户确认合同，不尝试验证外部对话系统本身
- 验证: protect 拒绝空白 confirmation_ref；两个工具拒绝篡改 confirmed_by 或 confirmation_ref；正常基线摘要包含 confirmation_ref；回归通过

创建前规范化确认引用；workctl 与 taskctl 每次读取 baseline 时都要求用户主体和非空引用。`protected_baseline` 摘要加入 confirmation_ref，使最终复核能看到当前基线的确认依据。

## SOL-007 第7轮：让 taskctl init 继承既有 workflow 身份

- 状态: confirmed
- 轮次: 7
- 解决: GAP-007
- 满足: DES-008, AC-002, AC-003, UDES-001
- 依赖: SOL-006 后的工作流身份与基线合同
- 风险: 独立无 workflow 的纯任务目录仍允许调用者定义身份；只在组合工作区收敛权威来源
- 验证: 既有 workflow 中 mismatched ID/title 均在写入前失败，同一 ID/title 能恢复缺失任务表并被 status 读取；纯任务 init 不变；回归通过

`taskctl command_init` 在写入前检测并验证已有 workflow；存在时要求传入身份与其完全一致。workflow 是组合工作区身份真源，task-table 不得反向改写或创建第二身份。

## SOL-008 第8轮：把引用提取限制到正式关系字段

- 状态: confirmed
- 轮次: 8
- 解决: GAP-008
- 满足: DES-009, AC-002, AC-003
- 依赖: SOL-007 后的组合工作区版本
- 风险: 必须覆盖合同允许的全部关系字段，不能因收窄误删真实链路
- 验证: 正式关系字段继续形成正反向引用；正文/标题/来源中的 ID 形文本不形成引用或诊断；当前工作区 fake token 消失且真实引用计数稳定；回归通过

新增显式关系字段解析器，只扫描字段值中的合法 ID；更新产物合同列出可索引字段。任务 source_ids 仍由 taskctl 自身显式字段管理，不受正文解析影响。

## SOL-009 第9轮：限制 complete 的合法来源状态

- 状态: confirmed
- 轮次: 9
- 解决: GAP-009
- 满足: DES-010, AC-002, AC-003
- 依赖: SOL-008 后的当前任务/语义版本
- 风险: 不把 review 设为强制阶段；in_progress 可直接完成，保持轻量执行
- 验证: todo/claimed/blocked complete 均在写结果前失败；in_progress 和 review 均成功；结果恢复路径不变；回归通过

在 command_complete 写结果前检查来源状态，仅允许 `in_progress/review`。错误保持有界 JSON，不新增产品语义门禁或依赖完成门禁。

## SOL-010 第10轮：分离 completion-context 的续页流

- 状态: confirmed
- 轮次: 10
- 解决: GAP-010
- 满足: DES-011, AC-002, AC-003
- 依赖: SOL-009 后的真实任务生命周期版本
- 风险: 首次精确 target 查询仍需保留共享首屏；续页请求必须通过 returned_streams 明确实际返回内容
- 验证: 首次页返回 targets/constraints/deferred；目标续页只返回 targets；candidate、constraint、deferred 续页分别只返回自身；混合流游标失败；snapshot 变化仍失败；回归通过

根据续页游标选择唯一流，新增 `returned_streams`。无游标首次请求保持完整首屏；`after-id/candidate-after-id/constraint-after-id/deferred-after-id` 各自选择目标、候选、约束或 DCR 流，禁止组合。

## SOL-011 第11轮：统一任务状态与导出视图的数据路径

- 状态: confirmed
- 轮次: 11
- 解决: GAP-011
- 满足: DES-012, AC-002, AC-003
- 依赖: SOL-010 后的完成上下文版本
- 风险: Markdown 仍只是可重建投影，不得把结果计数描述为产品完成
- 验证: 导出显式包含需复核与三项结果统计；损坏当前结果使 render 有界失败；既有状态、上游与任务表内容保持

让 `command_render` 复用 `summarize_loaded_task_storage`，并把与 `status` 同义的复核数和结果统计写入 Markdown 与 JSON 返回值；同时保留“视图不表示产品完成”的声明。

## SOL-012 第12轮：补齐交付总览的三类状态

- 状态: confirmed
- 轮次: 12
- 解决: GAP-012
- 满足: DES-013, AC-002, AC-003
- 依赖: SOL-011 后的可信任务存储摘要
- 风险: 数量不能被描述为最终完成率或 READY 门禁
- 验证: WORK_STATUS.md 显示确认者/引用、任务总数/需复核、可修订未决/DCR、当前结果/验证/未决结果；损坏结果仍使 render 失败；回归通过

`render_workspace` 只消费 taskctl 已验证的摘要，不创建第二状态源。视图按职责分块报告三类状态，并保留完成结论必须回到受保护目标逐项审计的边界。
