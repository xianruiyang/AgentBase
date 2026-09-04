# 实验环境清理与保留节点

2026-09-04，按用户授权删除过期独立实验环境，重要基线保留；失败项原计划同盘集中等待手动删除。本记录供后续实验恢复与定位环境使用，不进入部署。它记录本次清理后的状态，不保证未来环境仍未被修改。

## 保留

基线根目录为 `C:/Users/gzxt/AppData/Local/AgentBase/benchmark-homes`：

| 节点 | 根目录下的保留路径 | 依据 |
| --- | --- | --- |
| 旧最佳批量版 | `full-suite-agentbase-only-v2/external/control` | [既定新旧基线](report-code-reading-qualified-v25.md) |
| v25 已采纳新版，71/74 | `scope-evidence-clean-v1/candidate` | 同上，保留原身份，不用后继安装态替换 |
| 本轮当前安装态，74/74 | `reading-current-v26/control` 与 `reading-current-v26/candidate` | [完整复测](report-code-reading-current-v26.md)；两份环境只差工作区信任登记，各自被原始 manifest 引用 |

四份 home 的 AGENTS、config、bin 和 skills 在清理前后逐文件比对一致；没有改名、搬迁或重新复制基线。保留节点没有外部 environment-dependencies 目录依赖。

`D:/AgentBaseBench` 中的原始答案、usage、summary、capsule、准备资料及 `source-workspaces/agentbase-v24` 源码快照保留。历史实验记录引用的其他 home 已可能不存在；旧结果可继续审计，不代表旧运行环境仍可直接启动，也不得用当前内容偷偷补回历史环境。

## 已删除

- C 盘 benchmark-homes 根内，除上述保留树外的87个目录分支全部删除，清理期间可用空间增加约25.91 GiB。
- `D:/AgentBaseBench/full-suite-oldbatch-v1/homes/old-batch` 与 `D:/AgentBaseBench/full-suite-oldbatch-v1/dependencies/old-batch` 两处旧整树副本删除，清理期间可用空间增加约3.07 GiB。
- Temp 下另删除 `AgentBase-codex-ab-benchmark/candidate-home`、`AgentBase-code-search-opt-benchmark-v2/ablation-home` 与 `AgentBase-code-search-opt-benchmark-v2/bare-home` 三份早期 home；同目录原始结果与工作区保留。这部分可用空间增加约0.87 MiB。
- 合计约28.98 GiB；磁盘空闲量会受其他进程影响，不将其视为精确文件占用统计。没有改动真实 Codex 安装或项目源码，没有运行模型测试或部署。
- 本次92处目标全部删除成功，没有待手动删除目录。删除没有经过回收站，不能直接撤销；重要基线和原始实验记录已独立保留。项目 `.codex` 中的本地配置、调试状态不属于本次实验 home 清理范围。

精确操作清单、保留文件校验和执行结果在 `D:/AgentBaseBench/environment-cleanup-20260904`；这是本次清理的审计材料，不是新的实验环境、长期清理入口或门禁。
