# AgentBase 当前接手状态

更新时间：2026-08-17

## 已发布基线

- 仓库提交 `86ee057306659da6e615a7d33580184f8c543cb8` 已于 2026-08-17 17:48 按用户针对该次操作的明确授权发布到 `C:\Users\gzxt\.codex`，模式为 `DirectCompatibility + 可移植设置`。本次发布没有文件差异（`changed=0`），因为安装内容此前已与该来源一致；它补齐了 schema 7 正式发布清单和生命周期收据。
- 当前只读 `Status` 为 `published=true`、`managed_payload_formally_published=true`、`formal_publication_gap_count=0`。来源、安装、清单、路由证据和受管生命周期均匹配，退役路径、退役配置键、直接兼容冲突均为 0；独立 `srcq` 0.3.1 完整性与 doctor 均通过。
- 最新发布清单是 `C:\Users\gzxt\.codex\backups\AgentBase-20260817-174806-950ee535\manifest.json`。需要回滚时，从仓库根执行：

```powershell
& '.\development\codex-deployment\manage_agentbase.ps1' -Action Rollback -ProjectRoot (Get-Location).Path -CodexRoot (Join-Path $env:USERPROFILE '.codex') -BackupPath 'C:\Users\gzxt\.codex\backups\AgentBase-20260817-174806-950ee535'
```

发布只证明安装合同成立；当前 Codex 运行不会追溯加载新规则，行为验证应在新任务或重启后的运行中进行。

## 当前开发候选

- 正在执行[常驻模型上下文与恢复面收敛](work/20260817_persistent_context_surface/requirements.md)。它分别审计 `global/AGENTS.md`、11 个项目 skill description 和本 handoff，只采纳在保持规则、路由和恢复质量后确有完整输入收益的候选。
- 当前工作树相对已发布基线存在未发布开发改动；完成身份、验证和 Git 提交尚未形成。权威阶段文档、任务依赖和后续恢复入口由该交付链的 [`workflow.json`](work/20260817_persistent_context_surface/workflow.json) 索引。
- 本版本不改变跨任务 `source_snapshot` 的事实表示、引用池或时效语义，不实施插件迁移，也不再次向 Codex 发布。

## 直接证据与下一动作

- 已发布基线的模型交互面证据保留在[完成审计](work/20260817_model_interaction_surface_contract/completion-audit.md)，部署状态与生命周期合同由[部署说明](../development/codex-deployment/README.md)和 [`managed_asset_lifecycle.json`](../development/codex-deployment/managed_asset_lifecycle.json)持有；本文件不复制历史实现展开。
- 当前候选已确认的基线为：`global/AGENTS.md` 4,690 个 `o200k_base` tokens，11 个 description 合计 1,192 tokens，本文件旧版 2,972 tokens。数值只确定审计范围，不证明任何语义可删除。
- 后继顺序：完成全局规则与 description 的逐项必要性审计；形成候选后刷新 detached Routing、Policy、References 证据并运行适用回归与部署 `Validate`；最后完成跨目标审计、更新本文件和总计划、提交并同步 Git。没有新的当次授权时停在“仓库候选未发布”。

## 未决边界

- 当前没有阻断已发布基线的已知失败。常驻读取面候选尚未完成，不能把工作文档、任务状态或局部缩短视为整体完成。
- `source_snapshot` 压缩和插件迁移仍是独立候选，只有各自 owner 出现新的直接证据时单独重开，不混入当前版本。
- 任何再次执行真实 `Publish` 都需要用户针对那一次操作重新明确同意；本次发布授权已经消费。Git 提交和远端同步按项目现有授权维护，但不能替代发布授权。
- 项目不使用远程 CI；验证只走 Windows 主机上的正式本地入口，远端仅同步源码与历史。
