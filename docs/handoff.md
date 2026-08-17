# AgentBase 当前接手状态

更新时间：2026-08-17

## 当前已发布版本

- 仓库闭合提交 `94d32d1671b376e87cac0f598609e814ddea5ca3` 已于 2026-08-17 20:12 按用户针对该次操作的明确授权发布到 `C:\Users\gzxt\.codex`，模式为 `DirectCompatibility + 可移植设置`，实际写入 12 项。功能主体提交是 `fc1215b8d54939217fe82c7d830b8722713e6948`；本文件所在的后续提交只维护发布后状态，不改变已发布 payload。
- 发布后只读 `Status` 返回 `managed_payload_formally_published=true`、`formal_publication_gap_count=0`。来源、安装与合同 bundle 均为 `8D66756E8D0E0E3028A52C6E2A2394E4FD5ECAE48C289C293670A5A36F5E127A`，发布清单同时匹配来源、安装、路由证据和生命周期；退役路径、退役配置键、直接兼容冲突均为 0，独立 `srcq` 0.3.1 完整性与 doctor 均通过。
- 最新发布清单是 `C:\Users\gzxt\.codex\backups\AgentBase-20260817-201245-41645e36\manifest.json`。需要回滚时，从仓库根执行：

```powershell
& '.\development\codex-deployment\manage_agentbase.ps1' -Action Rollback -ProjectRoot (Get-Location).Path -CodexRoot (Join-Path $env:USERPROFILE '.codex') -BackupPath 'C:\Users\gzxt\.codex\backups\AgentBase-20260817-201245-41645e36'
```

发布只证明安装合同成立；当前 Codex 运行不会追溯加载新规则，行为验证应在新任务或重启后的运行中进行。

## 本次交付

- 该[交付链](work/20260817_persistent_context_surface/completion-audit.md)分别审计 `global/AGENTS.md`、11 个项目 skill description 和 handoff，并只采纳通过质量门后的完整输入收益。routing bundle 为 `CDE243F4E0C58F73D335EA5E2CE978D645AB5F612170B4EA42D80F997082693C`。
- 相对上一已发布基线，常驻全局规则与 descriptions 减少 294 个 `o200k_base` tokens（5.0%），交付时 handoff 从 2,972 降为 1,247 tokens（58.0%）。
- 本版本不改变跨任务 `source_snapshot` 的事实表示、引用池或时效语义，也不实施插件迁移。

## 直接证据与后继入口

- 上一版本的模型交互面证据保留在[完成审计](work/20260817_model_interaction_surface_contract/completion-audit.md)，部署状态与生命周期合同由[部署说明](../development/codex-deployment/README.md)和 [`managed_asset_lifecycle.json`](../development/codex-deployment/managed_asset_lifecycle.json)持有；本文件不复制历史实现展开。
- 本次交付的逐项 owner 与删改裁决在[读取面审计](work/20260817_persistent_context_surface/context-surface-audit.md)，capsule 身份、Routing/Policy/References、恢复清单、Token 与部署 `Validate` 在[验证记录](work/20260817_persistent_context_surface/verification.md)，跨目标和消费者闭合在[完成审计](work/20260817_persistent_context_surface/completion-audit.md)。
- 当前没有开放的实现任务；出现审计中列出的重开条件时回到该交付链，而不是在 handoff 展开历史实现。

## 未决边界

- 当前没有阻断已发布版本的已知失败。Policy 单次结果的兼容附加标签限制已保留在验证记录；正式期望、禁选、严格 Routing 和 References 均通过，不能把该诊断外推为运行行为已经改变。
- `source_snapshot` 压缩和插件迁移仍是独立候选，只有各自 owner 出现新的直接证据时单独重开，不混入当前版本。
- 任何再次执行真实 `Publish` 都需要用户针对那一次操作重新明确同意；本次发布授权已经消费。Git 提交和远端同步按项目现有授权维护，但不能替代发布授权。
- 项目不使用远程 CI；验证只走 Windows 主机上的正式本地入口，远端仅同步源码与历史。
