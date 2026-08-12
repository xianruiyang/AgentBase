# AgentBase 交付链自审与改进：现状分析

## OBS-001 初始化返回值声明了未创建的文件

- 状态: superseded
- 后继证据: T002 结果与 OBS-008
- 来源或证据: 本轮真实运行 `workctl init` 的返回值与文件读回；`init_workspace`
- 事实/推断/未知: 直接事实
- 关联目标: DES-002
- 可证明上限: 只覆盖当前 `init` 返回合同

命令返回的 `created` 包含 `protected-baseline.json`、`.work-cache/index.json`、`WORK_STATUS.md` 和 `TASK_TABLE.md`，但初始化后这些文件均不存在。模型若依赖该字段决定下一步，会把待创建产物误认为已经存在。

## GAP-001 初始化结果不能准确指导下一步

- 状态: superseded
- 后继证据: T002 结果与 OBS-008
- 关联: OBS-001, DES-002, AC-002

当前返回合同没有区分已创建内容与后续命令才会生成的内容，不满足工具输出应准确描述确定性动作的设计。

## OBS-002 outline 的公开参数与文档不一致

- 状态: superseded
- 后继证据: T002 结果与 OBS-008
- 来源或证据: 本轮按 skill/tooling 调用 `outline --work-dir ... --stage current-state` 失败；`build_parser` 只接受内部下划线名称且拒绝 `--work-dir`
- 事实/推断/未知: 直接事实
- 关联目标: DES-002, UDES-001
- 可证明上限: 覆盖 `outline` 的当前公开 CLI

skill 要求每次显式传绝对工作区，tooling 给出统一命令形态，但 `outline` 是例外且阶段名使用 `current_state`、`user_design` 等内部键。公开合同没有列出这一差异。

## GAP-002 阶段合同查询不易可靠组合

- 状态: superseded
- 后继证据: T002 结果与 OBS-008
- 关联: OBS-002, DES-002, AC-001

模型必须读源码或先失败一次才能知道正确参数，增加 Token 和错误恢复成本。

## OBS-003 workctl 独立解析任务状态且没有验证任务集合

- 状态: superseded
- 后继证据: T001、T002 结果与 OBS-007、OBS-008
- 来源或证据: `task_status_summary` 只枚举 `state/*.json`，把状态文件数当任务数，重复读取状态，并未核对 `tasks/`、state identity、当前 result identity 或 task revision
- 事实/推断/未知: 直接事实
- 关联目标: DES-003, DES-005
- 可证明上限: 覆盖 `workctl status/render` 的任务摘要实现

同一任务存储合同已经由 `taskctl` 完整验证，`workctl` 又维护了较弱的第二套读取逻辑；孤立或损坏状态文件可能产生看似正常但错误的进度摘要。

## GAP-003 跨 skill 任务进度存在第二套弱实现

- 状态: superseded
- 后继证据: T001、T002 结果与 OBS-007、OBS-008
- 关联: OBS-003, DES-003, DES-005, AC-002

当前职责没有收敛到任务管理真源，无法保证组合视图与 `taskctl status` 对同一存储给出一致、可验证的计数。

## OBS-004 workflow 与 task table 的工作流身份没有绑定

- 状态: superseded
- 后继证据: T001、T002 结果与 OBS-007、OBS-008
- 来源或证据: `workctl.load_manifest` 与 `taskctl.load_table` 校验固定路径但不校验两个 manifest 的 `id` 相同
- 事实/推断/未知: 直接事实
- 关联目标: DES-001, DES-003, DES-004
- 可证明上限: 覆盖当前工作区 manifest 组合合同

把另一工作流的 `task-table.json` 和任务目录放入当前目录后，路径结构仍可能通过；最终候选证据存在跨工作流混用风险。

## GAP-004 工作区身份不足以约束任务证据归属

- 状态: superseded
- 后继证据: T001、T002 结果与 OBS-007、OBS-008
- 关联: OBS-004, DES-003, DES-004

当前结构校验不能证明任务表属于同一个交付闭环。

## OBS-005 新增和更新任务不会立即返回上游诊断

- 状态: superseded
- 后继证据: T001 结果与 OBS-007
- 来源或证据: `command_add` 与 `command_update` 成功返回只有 revision 等存储结果；`task_diagnostics` 只在后续查询、领取或完成路径中使用
- 事实/推断/未知: 直接事实
- 关联目标: DES-003
- 可证明上限: 覆盖 add/update 返回合同

未知 source ID、上游未决、缺失产出或验证等允许保存的合同问题不会在写入动作结束时直接显示，模型需要额外查询才能发现。

## GAP-005 任务写入没有实现最低成本的即时辅助

- 状态: superseded
- 后继证据: T001 结果与 OBS-007
- 关联: OBS-005, DES-003, AC-002

CLI 保持了非门禁属性，但没有在最接近错误输入的位置提供软诊断，不符合快速辅助编写规范任务的目标。

## OBS-006 状态和结果历史存在三个确定性边界缺口

- 状态: superseded
- 后继证据: T001 结果与 OBS-007
- 来源或证据: `command_note` 用 truthiness 判断参数，无法显式清空备注；`command_release` 允许释放未领取任务且保留旧 `next_action`；`validate_result_history` 解析文件 revision 后未与当前 state revision 比较
- 事实/推断/未知: 直接事实
- 关联目标: DES-003, DES-005
- 可证明上限: 覆盖对应状态变换与结果文件命名合同

这些行为不涉及产品语义，却会制造不可表达的状态操作、无效 revision 变化、旧 owner 残留意图或明显超前的历史文件。

## GAP-006 任务存储安全合同仍有可构造的不一致状态

- 状态: superseded
- 后继证据: T001 结果与 OBS-007
- 关联: OBS-006, DES-003, DES-005, AC-003

当前 CLI 没有完整覆盖自身声明的非法状态变换与结果身份边界。

## OBS-007 taskctl 改进后的任务存储行为

- 状态: confirmed
- 来源或证据: T001 结果；taskctl 36/36 回归；本工作区 next、context、claim、start、complete 与 deps 真实读回
- 事实/推断/未知: 直接事实
- 关联目标: DES-003, DES-004, DES-005
- 可证明上限: 覆盖当前 taskctl 存储、诊断、状态和结果历史合同

任务表与 workflow 身份一致；严格摘要核对 tasks/state/current results；`add/update` 返回软诊断而不阻断写入；备注可以显式清空，未领取任务不能释放，释放会清除旧下一动作，明显超前的结果历史会被拒绝。

## OBS-008 workctl 改进后的组合行为

- 状态: confirmed
- 来源或证据: T002 结果；workctl 18/18 回归；本工作区 `outline current-state`、`status` 和 `render` 真实读回
- 事实/推断/未知: 直接事实
- 关联目标: DES-002, DES-003, DES-005
- 可证明上限: 覆盖当前 workctl 初始化、阶段合同和组合任务摘要

初始化明确区分真实创建与待生成路径；阶段查询使用公开连字符名称和统一绝对工作区；组合任务摘要来自 taskctl 严格存储接口，最终准确读回 3 个任务、3 个当前结果且全部为 `done`。

## OBS-009 交付工作区缓存未被项目忽略

- 状态: superseded
- 后继证据: OBS-010
- 来源或证据: 本工作区真实运行后 `git status` 与根 `.gitignore` 读回
- 事实/推断/未知: 直接事实
- 关联目标: DES-001, DES-005
- 可证明上限: 覆盖 AgentBase 当前 Git 忽略合同

`.work-cache/index.json` 是明确可重建的索引，却会随 `docs/work/...` 一起进入未跟踪范围；临时候选和结果输入也按工具使用习惯放入该目录。

## GAP-007 自举工作区会把运行缓存带入项目差异

- 状态: superseded
- 后继证据: OBS-010
- 关联: OBS-009, DES-001, DES-005, AC-003

当前项目不能在保留需求、设计、任务、状态与结果真源的同时自动排除交付链运行缓存，增加提交污染和误用缓存为真源的风险。

## OBS-010 项目已区分交付缓存与工作流真源

- 状态: confirmed
- 来源或证据: 根 `.gitignore` 与 `git check-ignore` 逐路径读回
- 事实/推断/未知: 直接事实
- 关联目标: DES-001, DES-005
- 可证明上限: 覆盖 AgentBase 当前 Git 忽略合同

`**/.work-cache/` 已被忽略；同一工作区的 `protected-baseline.json`、`tasks/*.json`、`state/*.json` 与 `results/*.json` 均未被该规则隐藏。

## OBS-011 add/update 的即时诊断发生在任务写入之后

- 状态: superseded
- 后继证据: OBS-012
- 来源或证据: 改进后 `command_add` 与 `command_update` 控制流复核
- 事实/推断/未知: 直接事实
- 关联目标: DES-003, DES-005
- 可证明上限: 覆盖即时诊断新增路径的写入顺序

两个命令在原子写入合同后才调用 `load_states` 生成诊断；若已有其他任务的 task/state 集合损坏，命令会失败，但本次候选已经持久化，返回语义与实际状态不一致。

## GAP-008 即时诊断路径可能产生失败但已写入的操作

- 状态: superseded
- 后继证据: OBS-012
- 关联: OBS-011, DES-003, DES-005, AC-003

当前实现没有在写入前完成生成诊断所需的确定性存储验证，破坏了任务 CLI 的事务恢复合同。

## OBS-012 add/update 已在写入前验证完整存储集合

- 状态: confirmed
- 来源或证据: taskctl 36/36 回归；新增 task/state mismatch 反例读回候选文件均不存在或保持原值
- 事实/推断/未知: 直接事实
- 关联目标: DES-003, DES-005
- 可证明上限: 覆盖 add/update 即时诊断路径的本次候选写入顺序

`add` 对允许恢复的本任务半写入单独建模，同时在写入前核对其他 task/state 集合；`update` 在改写合同前加载完整状态集合。存储损坏会失败且不落盘本次候选，语义诊断仍保持非阻断。
