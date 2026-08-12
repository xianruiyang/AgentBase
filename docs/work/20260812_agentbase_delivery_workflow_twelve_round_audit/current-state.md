# AgentBase 交付链十二轮审查与改进：现状分析

> 使用 `OBS-*` 和 `GAP-*` 二级标题分开记录当前证据与目标差距；事实、推断和未知必须明确区分。

## OBS-001 第1轮：初始化允许空白工作流身份

- 状态: superseded
- 后继证据: OBS-002
- 轮次: 1
- 基础版本: e8444eede5307ed4e7bdd3d6f94f5b51340cd757
- 来源或证据: 隔离工作区运行 `workctl init --id ' '` 返回成功；随后 `workctl status` 与 `taskctl status` 都因 task table ID 为空而失败
- 事实/推断/未知: 直接事实
- 关联目标: DES-002
- 可证明上限: 覆盖当前 workctl 初始化与两个读取入口的组合行为

`workctl init` 直接保存 argparse 字符串，`load_manifest` 也不验证 ID；而 `taskctl.load_table` 会拒绝空白 ID。创建入口因此能成功生成一个立即不可用的工作区。

## GAP-001 第1轮：创建合同与读取合同对身份有效性不一致

- 状态: superseded
- 后继证据: OBS-002
- 轮次: 1
- 关联: OBS-001, DES-002, AC-002

当前正式初始化入口不能保证产物满足自身下游读取合同；空白标题也能进入长期 manifest 和阶段模板，形成不可定位的工作流真源。

## OBS-002 第1轮完成：身份合同已在创建和读取边界统一

- 状态: confirmed
- 轮次: 1
- 来源或证据: workctl 20/20、taskctl 38/38；原空白 ID 输入返回退出码 2 且 `workflow.json` 不存在
- 事实/推断/未知: 直接事实
- 关联目标: DES-002, AC-002
- 可证明上限: 覆盖两个初始化入口、workctl manifest 读取及 taskctl workflow/task-table 身份读取

初始化写入前会去除合法文本两侧空白并拒绝空值；长期 manifest 读回拒绝空白或带外围空白的 ID/标题。成功创建的工作区不再因身份合同不一致而立即失效。

## OBS-003 第2轮：文件系统失败泄漏完整 traceback

- 状态: superseded
- 后继证据: OBS-004
- 轮次: 2
- 基础版本: 第1轮已验证版本（T001 / results/T001.r4.json）
- 来源或证据: 把普通文件作为 `workctl init --work-dir` 和 `taskctl init --task-dir`，两个命令均退出 1 并输出完整 Python traceback
- 事实/推断/未知: 直接事实
- 关联目标: DES-003
- 可证明上限: 覆盖两个 CLI 顶层对 `FileExistsError` 的处理

两个 `main` 只捕获各自领域异常。底层 `OSError` 绕过机器可读错误合同，把内部调用栈和宿主绝对路径写入输出。

## GAP-002 第2轮：可预期环境失败不能被调用方稳定消费

- 状态: superseded
- 后继证据: OBS-004
- 轮次: 2
- 关联: OBS-003, DES-003, AC-002

CLI 的成功和领域错误是 JSON，但常见文件系统错误改变为 traceback 和退出码 1；自动化调用方需要第二套解析，且不必要地放大输出。

## OBS-004 第2轮完成：文件系统错误已收敛为有界 JSON

- 状态: confirmed
- 轮次: 2
- 来源或证据: workctl 21/21、taskctl 39/39；原文件路径工作区反例均退出 2、可解析为 JSON 且不含 `Traceback`
- 事实/推断/未知: 直接事实
- 关联目标: DES-003, AC-002
- 可证明上限: 覆盖两个 CLI 主入口中的 `OSError`；编程错误仍不在该捕获范围

可预期文件系统异常现在保持和领域错误相同的机器可读形态，模型不再接收内部堆栈；非 `OSError` 的实现缺陷仍按原方式暴露。

## OBS-005 第3轮：in_progress 状态可以持有非空阻塞原因

- 状态: superseded
- 后继证据: OBS-006
- 轮次: 3
- 基础版本: 第2轮已验证版本（T002 / results/T002.r4.json）
- 来源或证据: 隔离任务从 `in_progress` 调用 `note --blocked-reason '等待外部输入'` 成功，读回仍为 `in_progress` 且 blocked_reason 非空
- 事实/推断/未知: 直接事实
- 关联目标: DES-004
- 可证明上限: 覆盖 `command_note` 与 `validate_state` 当前组合合同

`command_note` 只有显式 `--status` 才改变状态，但 `validate_state` 不约束 status 与 blocked_reason 的组合，因此进度统计说任务进行中，恢复上下文却说它被阻塞。

## GAP-003 第3轮：阻塞事实存在两个可以相互矛盾的字段

- 状态: superseded
- 后继证据: OBS-006
- 轮次: 3
- 关联: OBS-005, DES-004, AC-002

调用方无法仅凭状态或原因可靠判断任务能否继续，且 `status=blocked` 也可以没有原因；这是确定性状态模型不一致，不属于语义诊断。

## OBS-006 第3轮完成：阻塞状态与原因满足单一不变量

- 状态: confirmed
- 轮次: 3
- 来源或证据: taskctl 41/41、workctl 21/21；原 `--blocked-reason` 场景读回 `status=blocked`；损坏的 blocked 空原因状态被拒绝
- 事实/推断/未知: 直接事实
- 关联目标: DES-004, AC-002
- 可证明上限: 覆盖 task state 校验及 note 的进入、退出 blocked 路径

非空阻塞原因会自动进入 blocked，blocked 必须有原因，显式恢复到非阻塞状态会清除原因；持久化的矛盾组合无法再被任务查询接受。

## OBS-007 第4轮：参数解析错误绕过 JSON 错误合同

- 状态: superseded
- 后继证据: OBS-008
- 轮次: 4
- 基础版本: 第3轮已验证版本（T003 / results/T003.r4.json）
- 来源或证据: 对 `taskctl list` 传入当前不存在的 `--after-id`，命令退出 2 但输出多行 argparse usage 和纯文本错误
- 事实/推断/未知: 直接事实
- 关联目标: DES-005
- 可证明上限: 覆盖 parse_args 发生在 main 领域异常边界之前的行为

第2轮只收敛了 handler 内的 `OSError`；参数解析发生在 try 之前，两个 CLI 仍有另一套错误输出协议。

## GAP-004 第4轮：调用方仍需按错误发生阶段选择解析器

- 状态: superseded
- 后继证据: OBS-008
- 轮次: 4
- 关联: OBS-007, DES-005, AC-002

同一个 CLI 的参数错误不是 JSON，模型无法用统一、低 Token 的结构化路径识别失败原因；usage 输出还会重复大量命令列表。

## OBS-008 第4轮完成：参数错误已进入统一 JSON 协议

- 状态: confirmed
- 轮次: 4
- 来源或证据: workctl 22/22、taskctl 42/42；原未知参数场景 exit 2、JSON 可解析且无 usage；help 保持 exit 0 和标准文本
- 事实/推断/未知: 直接事实
- 关联目标: DES-005, AC-002
- 可证明上限: 覆盖两个 CLI 的 argparse error 与 help 路径

缺参数、未知参数和非法 choice 不再输出多行 usage；调用方可用与运行错误相同的 JSON 解析路径恢复，正常帮助没有被机器错误格式替代。

## OBS-009 第5轮：常用有界查询截断后无法继续

- 状态: superseded
- 后继证据: OBS-010
- 轮次: 5
- 基础版本: 第4轮已验证版本（T004 / results/T004.r4.json）
- 来源或证据: 当前 4 项任务运行 `list --limit 1` 返回 `truncated=true`、`matched_count=4`，但没有 cursor；`--after-id` 仍报告未知参数
- 事实/推断/未知: 直接事实
- 关联目标: DES-006
- 可证明上限: 覆盖 list；源码读回显示 next/deps/dependents 同样只切片且无续页参数

这些命令能够告诉模型还有结果，却没有办法继续取得第 2 页。提高 limit 只能增加单次 Token 成本，并在未知规模时反复猜测。

## GAP-005 第5轮：低 Token 查询与完整遍历不可同时成立

- 状态: superseded
- 后继证据: OBS-010
- 轮次: 5
- 关联: OBS-009, DES-006, AC-002, AC-003

模型要么接受漏项，要么扩大输出；依赖和后继查询尤其可能隐藏关键任务，违背 CLI 用少量 Token 快速查询依赖的职责。

## OBS-010 第5轮完成：四类查询可用固定小页完整遍历

- 状态: confirmed
- 轮次: 5
- 来源或证据: taskctl 43/43、workctl 22/22；当前 5 项任务以 limit 2 遍历得到 T001..T005，各一次且最终 truncated=false
- 事实/推断/未知: 直接事实
- 关联目标: DES-006, AC-002, AC-003
- 可证明上限: 覆盖 list/next/deps/dependents 的 unchanged-input ID cursor；不主张跨状态变化的快照一致性

四类查询现在都返回 `next_after_id` 并接受 `--after-id`。游标不属于当前筛选结果时明确要求重新从第一页读取，保持建议查询轻量而不冒充最终审计快照。

## OBS-011 第6轮：基线确认来源可以被改成模型且仍通过

- 状态: superseded
- 后继证据: OBS-012
- 轮次: 6
- 基础版本: 第5轮已验证版本（T005 / results/T005.r4.json）
- 来源或证据: 隔离复制受保护工作区，把 baseline 的 `confirmed_by` 改为 `model`、`confirmation_ref` 改为空白；`workctl status` 仍 exit 0 并报告 protected/confirmed_by=model
- 事实/推断/未知: 直接事实
- 关联目标: DES-007
- 可证明上限: 覆盖当前 baseline 读取校验；被保护文档内容与哈希未改变

创建命令限制 confirmed_by choice，但 baseline 读回只验证 schema、workflow、文档路径、哈希和 IDs。确认主体与确认引用不属于完整性检查。

## GAP-006 第6轮：文档完整性可被误当成用户确认完整性

- 状态: superseded
- 后继证据: OBS-012
- 轮次: 6
- 关联: OBS-011, DES-007, AC-003, UDES-001

一个失去用户确认来源的 baseline 仍能驱动最终目标集合，破坏受保护目标的规范来源边界；摘要也没有 confirmation_ref 供复核。

## OBS-012 第6轮完成：基线完整性包含用户确认来源

- 状态: confirmed
- 轮次: 6
- 来源或证据: workctl 23/23、taskctl 44/44；原 confirmed_by=model 反例 exit 2；当前 status 读回 user 与精确 confirmation_ref
- 事实/推断/未知: 直接事实
- 关联目标: DES-007, AC-003, UDES-001
- 可证明上限: 覆盖项目 baseline 结构与两个工具的创建/读取合同；不验证外部对话系统内容

空确认引用不能建立 baseline，篡改确认主体或引用会在两个工具读取时失败；状态与索引摘要现在暴露确认引用，最终审计可核对其来源。

## OBS-013 第7轮：taskctl 恢复任务表时可写入冲突身份

- 状态: superseded
- 后继证据: OBS-014
- 轮次: 7
- 基础版本: 第6轮已验证版本（T006 / results/T006.r4.json）
- 来源或证据: 隔离 workctl 工作区删除 task-table 后，`taskctl init --id other-id` exit 0 并写入；随后 taskctl status 因 different workflow 失败
- 事实/推断/未知: 直接事实
- 关联目标: DES-008
- 可证明上限: 覆盖 taskctl init 对既有 workflow 的组合恢复路径

第1轮约束了单个 manifest 的身份文本，第7轮的新版本仍未约束独立初始化入口与已经存在的交付身份一致。

## GAP-007 第7轮：恢复入口能制造新的跨 manifest 冲突

- 状态: superseded
- 后继证据: OBS-014
- 轮次: 7
- 关联: OBS-013, DES-008, AC-002, AC-003, UDES-001

任务表缺失本来是可恢复状态，但错误参数会写入新的长期真源，命令声称成功后所有组合命令失败，需要人工删除再重试。

## OBS-014 第7轮完成：任务表恢复继承既有 workflow 身份

- 状态: confirmed
- 轮次: 7
- 来源或证据: taskctl 45/45、workctl 23/23；原隔离工作区 mismatched init exit 2 且未写表，matching init exit 0，随后 status exit 0
- 事实/推断/未知: 直接事实
- 关联目标: DES-008, AC-002, AC-003, UDES-001
- 可证明上限: 覆盖既有 workflow + 缺失 task-table 的恢复路径；纯任务目录保持独立身份

组合工作区中 workflow 成为身份权威，taskctl 不能用不同 ID 或标题建立第二身份；正确参数仍能恢复缺失任务表并继续查询。

## OBS-015 第8轮：正文中的 ID 形文本被当成关系

- 状态: superseded
- 后继证据: OBS-016
- 轮次: 8
- 基础版本: 第7轮已验证版本（T007 / results/T007.r4.json）
- 来源或证据: 当前 parser 对标题与完整 body 运行 ID_RE；因此本证据句中的示例 `REQ-NOT-A-REFERENCE` 会被索引为未知引用
- 事实/推断/未知: 直接事实与可重复输入
- 关联目标: DES-009
- 可证明上限: 覆盖 workctl parse_document 的引用提取范围及由它派生的 taskctl index

语义关系没有区分结构字段和说明文字。日志、迁移记录、反例或“不要引用某 ID”的说明都可能反向污染追溯图。

## GAP-008 第8轮：追溯图会产生假未知和假下游

- 状态: superseded
- 后继证据: OBS-016
- 轮次: 8
- 关联: OBS-015, DES-009, AC-002, AC-003

错误边会增加诊断、让 impact 返回无关对象，并可能让 completion-context 把无关任务结果列为受保护目标候选证据，降低最终审计可信度。

## OBS-016 第8轮完成：语义边只来自正式关系字段

- 状态: confirmed
- 轮次: 8
- 来源或证据: workctl 24/24、taskctl 45/45；当前索引 unknown_reference=0，`REQ-NOT-A-REFERENCE` 不再产生诊断；显式缺失关系单测仍产生唯一 unknown
- 事实/推断/未知: 直接事实
- 关联目标: DES-009, AC-002, AC-003
- 可证明上限: 覆盖 artifact contract 声明的中英文关系字段与当前索引/impact 派生图

标题、来源、证据、说明和代码示例中的 ID 形文本不再进入关系图；明确关系字段仍形成正反向边和未知引用诊断。

## OBS-017 第9轮：todo 任务可以直接 complete 为 done

- 状态: superseded
- 后继证据: OBS-018
- 轮次: 9
- 基础版本: 第8轮已验证版本（T008 / results/T008.r4.json）
- 来源或证据: 隔离任务保持 state revision 1/todo，直接 complete 成功并读回 done/owner=audit
- 事实/推断/未知: 直接事实
- 关联目标: DES-010
- 可证明上限: 覆盖 command_complete 当前状态前置条件

`complete` 只拒绝已经 done 和 owner 冲突；todo、claimed、blocked 均可跳过执行或忽略阻塞直接完成，和 skill 声明的状态机及非法状态变换硬错误不一致。

## GAP-009 第9轮：完成状态不能证明任务曾进入执行阶段

- 状态: superseded
- 后继证据: OBS-018
- 轮次: 9
- 关联: OBS-017, DES-010, AC-002, AC-003

任务表虽不证明产品完成，但应准确记录自身执行生命周期；当前 done 甚至不能证明 start 发生过，降低恢复和完成候选的可信度。

## OBS-018 第9轮完成：complete 只接受执行或评审状态

- 状态: confirmed
- 轮次: 9
- 来源或证据: taskctl 46/46、workctl 24/24；原 todo complete 反例 exit 2、result_count=0、state 仍 todo；review 完成回归通过
- 事实/推断/未知: 直接事实
- 关联目标: DES-010, AC-002, AC-003
- 可证明上限: 覆盖 taskctl 完成状态变换；不把进入执行阶段外推为产品结果正确

todo、claimed 和 blocked 无法直接完成，失败发生在结果写入前；in_progress 与可选 review 均保留轻量完成路径。

## OBS-019 第10轮：目标续页重复返回相同约束

- 状态: superseded
- 后继证据: OBS-020
- 轮次: 10
- 基础版本: 第9轮已验证版本（T009 / results/T009.r4.json）
- 来源或证据: 当前真实工作区 completion-context limit=1 的首两页分别返回 AC-001/AC-002，但两页都返回 CON-001；紧凑 JSON 约 2343/2350 字节
- 事实/推断/未知: 直接事实
- 关联目标: DES-011
- 可证明上限: 覆盖目标续页；源码显示 DCR 与约束同样在未传其专属 cursor 时每次从头返回

completion-context 有独立游标字段，却没有独立流选择语义。分页目标时会重复约束与 DCR，分页约束时又会重复目标，范围越大浪费越明显。

## GAP-010 第10轮：最终审计分页会重复证据并增加漏审风险

- 状态: superseded
- 后继证据: OBS-020
- 轮次: 10
- 关联: OBS-019, DES-011, AC-002, AC-003

重复块占用预算，可能迫使目标候选被进一步截断；调用方也难以判断 null cursor 表示“该流已完成”还是“本页未请求该流”。

## OBS-020 第10轮完成：完成上下文续页只返回所选结果流

- 状态: confirmed
- 轮次: 10
- 来源或证据: taskctl 46/46、workctl 24/24；当前真实工作区首屏返回 targets/constraints/deferred_changes，目标第二页只返回 targets 且 constraints/DCR 均为空；混合目标与 DCR 游标 exit 2
- 事实/推断/未知: 直接事实
- 关联目标: DES-011, AC-002, AC-003
- 可证明上限: 覆盖首次页、目标页、单目标候选页、DCR 页和混合游标反例；约束流由同一选择分支和回归覆盖

首次页继续提供完整审计入口，续页通过 `returned_streams` 声明唯一职责。真实目标第二页紧凑 JSON 从修复前约 2350 字节降至 2269 字节，且不再重复约束；快照一致性合同保持不变。

## OBS-021 第11轮：任务表导出弱于状态查询

- 状态: superseded
- 后继证据: OBS-022
- 轮次: 11
- 基础版本: 第10轮已验证版本（T010 / results/T010.r4.json）
- 来源或证据: 当前真实工作区 `taskctl status` 返回 needs_review_count 与三项结果统计；同版本生成的 TASK_TABLE.md 只显示状态行、结果路径和上游摘要
- 事实/推断/未知: 直接事实
- 关联目标: DES-012
- 可证明上限: 覆盖 taskctl 的 status/render 数据路径与当前导出内容

`render` 仅加载任务和状态，并忽略索引诊断；它没有调用 `summarize_loaded_task_storage`，因此不会校验当前结果内容，也不显示 status 已有的复核与结果闭合信息。

## GAP-011 第11轮：导出视图可能形成比 CLI 状态更弱的任务收据

- 状态: superseded
- 后继证据: OBS-022
- 轮次: 11
- 关联: OBS-021, DES-012, AC-002, AC-003

人或模型若通过低成本 Markdown 视图接手，只能看到 `done` 和结果路径，无法直接区分当前结果是否有效、是否含验证或是否仍有未决；损坏结果还可能继续显示为正常路径。

## OBS-022 第11轮完成：任务表导出复用已校验的当前结果汇总

- 状态: confirmed
- 轮次: 11
- 来源或证据: taskctl 46/46、workctl 24/24；真实工作区 render 返回 needs_review=0、current_results=10、verified_results=10、unresolved_results=0，TASK_TABLE.md 同步显示四项；损坏结果反例使 render exit 2
- 事实/推断/未知: 直接事实
- 关联目标: DES-012, AC-002, AC-003
- 可证明上限: 覆盖 taskctl status/render 的任务存储事实一致性，不把结果计数外推为产品完成

导出视图现在会先读回并验证当前结果，再生成状态、复核、结果和上游摘要；JSON 返回值同时暴露同义字段与索引诊断。

## OBS-023 第12轮：总状态视图缺少证据闭合与基线确认来源

- 状态: superseded
- 后继证据: OBS-024
- 轮次: 12
- 基础版本: 第11轮已验证版本（T011 / results/T011.r4.json）
- 来源或证据: 当前真实工作区 WORK_STATUS.md 显示 protected/10、语义数量与任务状态，但不显示 confirmed_by、confirmation_ref、当前有效结果、验证结果或未决结果
- 事实/推断/未知: 直接事实
- 关联目标: DES-013
- 可证明上限: 覆盖 workctl render 的输出合同；不评价具体任务结果能否证明最终需求

workctl 已从 taskctl 取得完整 `task_status_summary`，但 `render_workspace` 只消费其中的 `counts`；数据已经存在，视图职责仍未覆盖。

## GAP-012 第12轮：交付总览不能低成本区分任务完成与证据闭合

- 状态: superseded
- 后继证据: OBS-024
- 轮次: 12
- 关联: OBS-023, DES-013, AC-002, AC-003

只看 `done` 与语义未决为零可能产生“接近完成”错觉；接手者还无法从总览确认受保护基线依据哪次用户确认建立。

## OBS-024 第12轮完成：交付总览分层呈现执行、语义与证据状态

- 状态: confirmed
- 轮次: 12
- 来源或证据: workctl 26/26、taskctl 46/46；真实 WORK_STATUS.md 显示 user 与确认引用、可修订语义/DCR、12项任务执行状态、需复核0、当前结果11、含验证11、含未决0；损坏当前结果反例使 workctl render exit 2
- 事实/推断/未知: 直接事实
- 关联目标: DES-013, AC-002, AC-003
- 可证明上限: 覆盖可重建交付总览的数据来源和显示，不把数量外推为最终需求完成

总览复用 taskctl 已验证的存储摘要，没有新增状态源或 READY 门禁；文首明确计数不定义语义或最终完成状态。
