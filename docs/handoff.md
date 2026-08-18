# AgentBase 当前接手状态

状态截点：2026-08-18 源码基线固化与 srcq 发布身份修复后（Asia/Shanghai）

## 一句话状态

当前 Codex 受管理 payload 候选已通过正式验证并发布到本机，原 dirty candidate 已形成 Git 基线；随后已在项目源码中修正 srcq 发布许可证的旧 SGY 产品标题并补回归，但按用户要求暂不构建、安装或迁移任何新版本。

## 仓库与发布状态

- 当前分支为 `main`；`9b29a5c`（`feat: refine model interaction and execution contracts`）固化此前已发布且验证通过的完整候选，后继提交只修正 srcq release helper、回归和直接受影响的状态说明。最终 HEAD 与上游应通过 Git 读回，不再把 `5b9523e` 当作当前源码。
- 2026-08-18 09:34 已在用户针对该次操作的明确同意下，通过唯一部署入口发布到 `C:\Users\gzxt\.codex`。模式为 `DirectCompatibility + InstallPortableSettings`，实际改变 3 项；没有混入插件迁移。
- 独立 `srcq` 安装仍为 `{ready:true version:0.3.1}`；该已安装版本的 `THIRD_PARTY_LICENSES.txt` 仍带旧 SGY 标题，项目源码已经修复但没有构建或安装替代版本。Codex 使用同一模式读回 `published : true`，此次源码修复不改变该 payload 状态。
- 本次回滚资产是 `C:\Users\gzxt\.codex\backups\AgentBase-20260818-093442-e6af20a4`。需要回滚时必须使用该路径和[部署说明](../development/codex-deployment/README.md)中的正式 `Rollback` 入口。
- 发布只证明受管理安装合同成立。发布当时的任务不会追溯加载新规则；新建任务或重启 Codex 后才使用本次安装内容。
- 本交接和总计划是在发布后维护的仓库文档，不属于 Codex payload，也不使上述安装状态失效。

## 当前候选已完成的能力

- 模型交互面已从“统一完整序列化”转为同一 canonical 结果的消费者视图：模型面按动作保留最小充分证据，machine 面保留完整稳定合同。Task/Work CLI 的 authoring、completion、查询、写入回执和生成式导航均已沿各自 owner 闭合；详细索引在[总计划](plan.md)第 4 节。
- `source_snapshot` 已完成收据化交互面：最终模型预算投影决定捕获成员，模型传递最小收据，机器面持有内容寻址映射；进一步压缩或语义迁移仍是独立候选，不能据此视为开放任务。
- 部署、Windows bootstrap 和 `srcq` 安装器的直接控制台输出已采用紧凑模型投影，完整程序合同保留在显式 machine 视图；旧版受管理资产由生命周期合同清理，不靠手工删除。
- 执行控制已明确：架构或职责证据使原方案失效时先重裁再实现；是否建立计划由任务的跨步骤控制需要决定。
- Skill 每个 new turn 重新路由；完整正文仍在有效上下文且来源未变时不重复读取，压缩后只恢复当前重新选中的 skill 及必要引用。
- 推理档位控制已从 Goal 解耦：先独立判断目标档位，只有状态证据会改变动作时查询，只有错配且剩余工作能摊销切换成本时设置；用户固定档位始终优先，Goal 只承载本来需要的续轮。

## 直接证据与正式入口

- 项目方向、所有闭环子计划、owner、消费者和重开条件以[总计划](plan.md)为唯一索引；当前没有未闭环的项目级实施项。
- 最新全局规则与 skill 候选通过静态合同：90 个场景，49 个严格路由场景、6 个严格引用场景，11/11 项目 skill 均有正向与非触发覆盖。
- 最新 detached 评估为 Routing `90/90`、Policy `90/90`、References `21/21`；候选 bundle 为 `24CC35AECD613FAAED13E45A2B2FE69D724FFA9E53009E049CA8942FC12EBA18`。身份、输入声明和 capsule 哈希由 [`evidence/current.json`](../development/skill-routing/evidence/current.json)持有，不在本文件复制完整结果。
- 当前基线复验覆盖 Task Table Manager `92/92`、Delivery Workflow `39/39`、推理生命周期 `8/8`、bootstrap、srcq 安装视图与安装生命周期、90-case 路由静态合同和正式部署 `Validate`；详细专项证据仍由各自验证文档持有。
- srcq release helper 的定向 Rust 回归为 `5/5`，新增用例直接断言第三方许可证前言使用 SRCQ 产品身份且不含旧 SGY 标题；正式新版本构建、归档验收和真实安装尚未执行。
- 真实安装状态不能由本文件推断；使用[部署说明](../development/codex-deployment/README.md)中的只读 `Status`，并保持 `DirectCompatibility + InstallPortableSettings` 范围一致。

## 未决边界

- 当前没有已知失败阻断已发布 Codex payload，也没有仅因计划存在而应继续实施的任务。srcq 源码缺陷已修复；生成新版本、归档验收和真实安装是用户明确延后的独立生命周期，不能误报为已经完成。
- 插件迁移尚未进行。直接 skill 安装与 `agentbase-core` 插件不得同时启用；迁移必须作为独立工作验证安装、启停、hook 信任、卸载和回滚。
- 原 dirty candidate 已形成职责清晰的 Git 基线；下个对话仍先用 `git status --short`、当前分支和上游读回确认最终工作区状态，不从本文件猜测。
- 任何下一次真实 `Publish` 都必须重新取得用户针对那一次发布的明确同意；本次授权已经消费。Git 授权也不能替代发布授权。
- 项目不使用远程 CI；正式验证在 Windows 本机执行，远端只承担源码与历史同步。

## 下个对话的最小恢复步骤

1. 先读取根 `README.md` 和本文件；只有需要选择、重开或替代子计划时再读取[总计划](plan.md)。
2. 运行 `git status --short` 并读回当前分支、HEAD 与上游；`9b29a5c` 是此前已发布候选的源码基线，后继 srcq 修复不代表已经构建或安装新版本。
3. 若任务依赖真实安装状态，按部署说明以 `DirectCompatibility + InstallPortableSettings` 运行只读 `Status`；不要从 handoff 或 Git 历史推断安装状态。
4. 根据用户的新请求定位总计划中的现有 owner。只有命中重开条件才继续开发；若目标是整理 Git，则先审查实际差异并取得当前操作所需授权。
5. 只读取所选专项的 `solution.md`、`verification.md` 或 `completion-audit.md` 中当前判断缺少的部分，不批量重读全部历史交付链。
