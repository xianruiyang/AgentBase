# AgentBase 当前接手状态

更新时间：2026-08-17

## 当前版本与发布状态

- 当前 Codex 已安装版本仍是 Git 实现 `6fe7838` 对应的 `DirectCompatibility` 发布；已发布 source bundle SHA-256 为 `DACC5897574921931B84A8EA6A11E0791D4F2407AC3B72A58DD513F41FE3220A`，回滚资产为 `C:\Users\gzxt\.codex\backups\AgentBase-20260817-013438-fe195f4a`。
- 仓库 Git 实现版本为 `695aadc`，对应“模型可见工具输出双视图”开发候选；正式部署候选 `Validate` 通过，source bundle SHA-256 为 `F246ED2FF687FC988F66DDAC30B01D04B5E41AADA30D411C4817D43501735DC9`，routing evidence SHA-256 为 `E7380AD4D2311A9C61F0DF4A25DE1D32DBCE82C75D58AF20CAF39F5526DD2ECE`。该候选没有发布到 Codex。
- 再次发布到 `C:\Users\gzxt\.codex` 必须由用户针对该次 `Publish` 明确同意；开发、验证、Git 提交、远端同步和此前发布授权都不能替代。

## 最近完成的开发候选

最近完成的是 [`taskctl` / `workctl` 模型可见工具输出双视图](work/20260817_model_visible_tool_output_contract/completion-audit.md)：

- 根需求新增 REQ-012 与 AC-040—AC-044；`global/AGENTS.md` 维护消费者选择、最小充分字段、同源双视图和格式实测原则，具体投影仍由各工具 owner 决定。
- `taskctl` 与 `workctl` 默认返回面向模型的分行紧凑 HJSON 风格视图；程序、测试和完整结构审计显式使用 `--view machine` 保持既有 JSON。两种视图来自同一次 handler 事实计算，stdout/stderr 固定为 UTF-8。
- task status、context、completion-context 与 work status、context 已按当前动作投影；预算不足时裁剪完整低优先级语义单元并给出精确恢复，不统一截短字符串。task 执行 context 仍保留结果合同需要的完整 `source_snapshot`；completion-context 不复制候选完整映射。
- 真实工作区质量与 `o200k_base` 审计通过；同一模型投影中，当前 HJSON 风格比 compact JSON 和块状 YAML 更省 Token。具体数字只由[输出审计](work/20260817_model_visible_tool_output_contract/output-audit.md)维护，不外推为固定阈值。
- `task-table-manager` 70 项、`delivery-workflow` 35 项回归通过；静态 74-case 合同、Routing 74、Policy 74、References 19 和部署候选 Validate 通过。Routing 保留 1 个非严格 case 的额外 task-table-manager 选择警告，没有漏选、禁选或严格路由失败。
- References 评估曾暴露“仅保持目标不变也加载目标合同”的过选，正式 owner 已明确只有目标创建/修改/漂移、DCR 或最终复核才加载；Routing 评估暴露的一行 PowerShell 管道歧义也已在 `powershell-usage` owner 修正。

## 未决问题与后继候选

当前没有阻断本开发候选的已知失败。根 REQ-012 是以后所有模型可见工具都适用的长期合同，但本版本的直接实现和消费者迁移只覆盖 taskctl/workctl；[消费者影响复核](work/20260817_model_visible_tool_output_contract/consumer-impact.md)没有把其他 owner 误标为已迁移。

优先后继候选是 `codex-event-logger/read_codex_turn_log.py`：它直接服务模型恢复，当前仍返回路径、限制、字节计数和完整记录对象；应先用真实压缩恢复与历史追溯样本证明必要字段、恢复方式和 Token/质量边界，再决定是否建立 model/machine 投影。推理深度 receipt、QQ、MCP 和开发脚本维持各自生命周期，只有出现直接高成本证据时才重开，不能机械复制 task/work renderer。

跨任务 `source_snapshot` 仍存在重复，但本轮没有改变其事实表示、引入引用池或压缩。既有测量只证明约 7%–16% 的结构空间，尚未证明整数引用能保持模型质量；只有形成可读、可局部恢复且不隐藏版本差异的表示后才进入独立版本。

## 当前边界

- 本轮交付链有 4 个任务、14 个最终目标、3 个约束和 0 个 DCR；4 个任务均有当前结构化结果，最终跨合同读回为 0 诊断。T004 的历史 `r3` 保留一次来源声明不完整诊断，当前 `r6` 已显式消费缺失约束并重新验证。
- 插件迁移仍是独立事项；当前安装继续使用 `DirectCompatibility`，本轮没有修改插件分发模式。
- 再次执行 Codex `Publish` 仍需用户针对该次发布明确同意；Git 提交与远端同步继续按项目现有授权维护。
