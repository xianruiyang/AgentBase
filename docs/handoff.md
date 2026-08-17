# AgentBase 当前接手状态

更新时间：2026-08-17

## 当前版本与发布状态

- 仓库当前候选为提交 `6fb3062`：部署 owner 已从仅记录退役路径的合同升级为路径与配置键共用的完整受管资产生命周期。该候选尚未 Publish 到真实 Codex；本轮没有取得或消费新的发布授权。
- 当前真实 Codex 仍是 2026-08-17 15:47 的 schema 6 `DirectCompatibility + 可移植设置` 安装，payload 内容仍对应核心实现提交 `dfc47b8` 和旧部署生命周期提交 `b7352b8`。三个旧查询 skill 已从安装目录退出，回滚资产仍为 `C:\Users\gzxt\.codex\backups\AgentBase-20260817-154709-8e23bcc2`；`source-query` 与独立 `srcq` 0.3.1 运行时未被本轮改变。
- 新合同的规范化 SHA-256 为 `C6A154180B84965299C1A5B85613E625928F9F3D1B921FD1C1767027FF9F66D2`，共 43 个稳定资产身份：38 个 `present`、3 个 `retired`、2 个 `transferred`。修正配置合同逐行指纹后，真实安装与当前来源都读为 `3561488DB15F06DD6DF9D6D8BB9F689F292A01C4063D88575757E7D217BCEBB0`，`installed_matches_source=true`；旧 schema 6 清单没有新算法和生命周期收据，因此 `managed_payload_formally_published=false`，三个正式缺口是清单来源指纹过期、安装指纹相对旧清单过期和生命周期收据过期。退役路径、退役配置键和配置冲突计数均为 0，故这表示候选尚未发布，不表示当前 payload 内容损坏。
- routing evidence 仍为 `AD83859A201F198AC8DF7923EDA60ED0389CB85434DDD0CE879371897249A021`。任何后续向 `C:\Users\gzxt\.codex` 执行真实 `Publish` 都必须由用户针对该次操作重新明确同意；开发、验证、Git 提交、远端同步和以前的发布授权都不能替代。

## 当前未发布的统一生命周期修正

- 更深根因不是单次清理漏项，而是部署器把“当前来源清单”误当成“完整受管历史”：某个路径或配置键一旦从当前来源消失，系统既不能区分退役与移交，也没有稳定身份和上一受管值来证明可安全删除。仅继续追加 tombstone 会让每种资产形成不同的手工补丁，仍可能在模式切换或配置迁移时复发。
- 正式 owner 保持为 `development/codex-deployment`。`managed_asset_lifecycle.json` 现在以稳定身份统一维护路径和配置键的 `present`、`retired`、`transferred` 状态；当前来源派生的全部路径与键必须和 `present` 集合精确相等，已发布身份不得删除，只能从现役显式转为退役或移交。稳定身份只包含定位与类型，发布/清理适用范围是可显式演化的策略，因此直接模式安装的旧资产可以在插件迁移时声明跨模式清理。
- schema 7 清单记录全部资产身份并跨发布模式和设置范围携带最后受管配置值的逐行指纹。退役路径继续验证类型与 reparse 边界后完整备份清理；退役配置键只有在安装值仍等于最后受管值时才随完整 `config.toml` 备份移除，用户修改或来源不可证的键会阻断并要求改为移交或恢复来源值。`transferred`、个人 skill/agent、MCP、项目 trust 和其他未受管宿主状态保持不变。
- 基线审计读取 19 个历史 `trigger-cases.json` 版本和真实 Codex 中 36 份 AgentBase 备份清单：14 个历史 required skill 等于当前 11 个加 3 个已退役查询 skill，65 个历史事务路径均落在当前或退役资产范围，没有未登记路径；历史 agent 没有超出当前 `luna`、`sol`、`terra`。配置中 `model` 与 `model_reasoning_effort` 的历史退出已明确登记为宿主接管，而不是误作退役删除。
- 新生命周期测试覆盖来源与合同全集相等、现役资产静默消失拒绝、未登记现役资产拒绝、已发布身份删除拒绝、跨模式显式退役、无效替代身份、跨范围来源证据传递，以及配置键可移除/已修改/不可证三种分支。完整部署沙箱继续覆盖两种分发模式、增量发布、回滚、旧路径清理和无关宿主资产保留；`test_managed_asset_lifecycle.ps1`、`test_manage_agentbase.ps1`、`test_portable_config.ps1`、PowerShell 语法检查和正式 Validate 均通过。既有路由验证仍只有原有 1 个非严格额外选择警告。
- 本修正没有向 `srcq` 增加参数兼容或过滤分支，也没有改变正式 payload 文件内容；source bundle 数值变化来自原便携配置合同把单元素数组错误下标为首字符的指纹缺陷被修正，真实来源和安装内容在新算法下仍一致。

## 上一功能版本

最近完成的是 [模型交互面与资产职责](work/20260817_model_interaction_surface_contract/completion-audit.md)：

- `docs/requirements.md` 的 REQ-012 已从工具输出上升为覆盖模型直接读取、生成或修改内容的长期合同；`global/AGENTS.md` 先按事实 owner、消费者、当前判断或修改责任和生命周期裁决读取面、修改面与机器面，不以扩展名、存储位置或传统格式代替职责判断。
- 模型读取面只进入缺失后会改变当前判断、定位、动作、验证或恢复的信息；模型修改面要求同责事实局部可见、稳定可定位、可直接验证且只有一个长期决定位置。模型或人维护的语义真源派生机器产物，程序维护的机器真源通过 owner 的有界投影、查询或受验证语义入口服务模型。
- Delivery Workflow 已明确阶段 Markdown 是模型/人维护的语义真源，索引、保护快照和状态视图按各自机器职责维护；Task Table Manager 已明确任务、状态和结果 JSON 通过正式 revision/CAS 命令维护，生成表格和 completion-context 是读取面，不是语义编辑入口。上一版 `taskctl` / `workctl` 默认 model、显式 machine 双视图保持不变。
- `codex-event-logger` 保持 `conversation.json` 与 `file-operations.jsonl` 的完整机器日志合同，读取器默认返回面向模型恢复的最小投影，显式 `--view machine` 保留原有完整 JSON。模型面只保留 prompt、assistant、goal、净文件操作、异常和精确恢复入口；重复修改被合并，创建后删除的临时文件退出模型面。
- 当前真实 turn 的同一次有界读取中，默认 model 为 489 个 `o200k_base` tokens，显式 machine 为 8736 个，减少 94.4%；模型面仍保留当前需求、上一结论和 20 个最终受影响文件。该比例只证明本轮样本，不是项目固定压缩阈值。
- `task-table-manager` 70 项、`delivery-workflow` 35 项、Event Logger 10 项回归通过；Event Logger 另有 1 项目录链接用例因当前主机能力按既有条件跳过。静态 76-case 合同、Routing 76、Policy 76、References 19 和部署候选 Validate 通过。Routing 保留 1 个非严格用例额外选择 `task-table-manager` 的警告，没有漏选、禁选、严格路由或严格引用失败。

## 直接证据与完成边界

- 本轮交付链有 4 个任务、15 个最终目标、3 个约束和 0 个 DCR；四项结构化结果覆盖根合同、文档/任务资产 owner、Event Logger 恢复面和最终验证交付，跨合同完成读回为 0 诊断。
- 真实 owner 与交互面、机器兼容、模型恢复充分性、Token 对照和生成物边界记录在[交互审计](work/20260817_model_interaction_surface_contract/interaction-audit.md)；跨目标、约束、任务结果和部署身份记录在[完成审计](work/20260817_model_interaction_surface_contract/completion-audit.md)。运行日志只是本轮直接证据，不是项目真源。
- 上一次正式 `Publish` 只证明当时文件已安装且 schema 6 清单与合同匹配；当前未发布候选不会被当前 Codex 追溯加载，未来即使获批发布，行为变化仍需在新任务或重启会话中验证。

## 未决问题与后继候选

当前没有阻断本开发候选的已知失败。新上位合同适用于未来模型交互面，但本轮只迁移了已有直接证据和正式消费者的根规则、Delivery Workflow、Task Table Manager 与 Event Logger；其他工具、文件或生成物不能因原则存在就被误标为已经审计或迁移，只有其 owner 出现可证实的必要信息遗漏、冗余成本、误改风险或第二真源时才重开。

跨任务 `source_snapshot` 仍存在重复，但本轮没有改变它的事实表示、引用池、时效语义或恢复合同。既有测量不足以证明替代表达保持模型质量，继续作为独立候选处理。

插件迁移仍是独立事项；当前安装继续使用 `DirectCompatibility`，本轮没有修改插件分发模式。

## 当前边界

- 当前仓库候选尚未发布；上一版本的发布授权已经消费，任何后续再次发布仍需新的当次明确同意。
- 本轮没有混入 `source_snapshot` 压缩或插件迁移。
- 用户已确认项目完全不需要远程 CI；仓库不再维护 GitHub Actions workflow，远端 Actions 权限应保持禁用，所有验证由 Windows 主机上的正式本地入口承担。
- Git 提交与远端同步继续按项目现有授权维护；不得用历史重写、强制推送或反向读取安装副本改变仓库真源。
