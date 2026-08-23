# 执行控制与 Skill 上下文生命周期：完成审计

## 重开原因

2026-08-21 的九题评测准备证明，原 AC-036 证据只覆盖“是否建立计划”和“条件相当时优先纵向闭环”，没有覆盖多个任务共享未证前提、首个真实消费者、失败遮蔽和昂贵批量验证。2026-08-23 用户又以两天大型 UE 工作流证明：相关规则虽然存在，任务状态仍滞后，验证维度启动过晚，手工 runner 与工具能力判断仍可产生可预防错误。第二次反例要求把可观察模型行为纳入项目质量，并让反例、前沿与覆盖边界进入正式执行状态；本文件以第二版候选重新审计，不沿用规则存在作为行为证明。

## 目标证据

| 目标 | 当前结果与直接证据 | 判定 |
| --- | --- | --- |
| AC-007 按端到端成本渐进加载上下文 | skill 选择、正文有效性和引用生命周期仍分离；新增 skill 只按两类控制问题加载引用 | 满足 |
| AC-024 纳入目标成立所需的职责调整 | 架构与长期 owner 仍由 `change-governance`；新执行 owner 明确排除单个领域故障和职责裁决，没有吸收治理职责 | 满足 |
| AC-036 共享前提先闭合真实消费者 | 全局不变量、执行控制循环、Delivery 投影、Task 真实依赖，以及 state 中的证据前沿/消费者/case/失效来源形成单向职责链；任务与路由回归通过 | 仓库合同满足；新版本真实执行未验证 |
| AC-050 目标档位、状态查询与切换收益分层 | 复杂执行的目标与状态价值归执行控制，稳定工作由模型直接判断，`reasoning-governor` 只承担线程读写与生命周期 | 仓库合同满足；真实自主切换未验证 |
| AC-066 支持场景以模型行为验收规则系统 | 全局责任边界、四个专项 skill、任务检查点、srcq 现态诊断、领域 runner 升级和五个严格行为场景已接入；旧 oracle 可零 Token 重验原结果 | 仓库合同满足；需发布后新任务验证行为 |
| AC-068 语义子代理有界委派 | `evidence` 稀疏可接纳证据与 `experiment` 可回滚连续遮蔽实验已进入代理、skill 和严格 Routing/References；补丁仍须主代理重写、修订接入或拒绝 | 仓库合同与安装满足；真实委派行为待新任务观察 |
| AC-069 同源当前前沿与结构写回漂移 | task/state/result 与关联 DCR 派生稀疏前沿，`state+1` 未引用结果只形成 advisory；102 项 taskctl 回归覆盖生成、预算、恢复、冲突与非触发边界 | 满足 |
| AC-070 昂贵动作 preflight | execution-governor 已定义按适用性选择的输入、fixture、权限、runner、oracle、变化依据和 ready/blocked，领域 runner 保留具体实现；严格路由与引用通过 | 仓库合同与安装满足；领域真实运行待消费者验证 |
| AC-071 四层规则执行失效定位 | 定义、路由/引用、动作、写回 trace 与修复 owner 的行为/引用合同通过，合理可选 lifecycle 引用不再被误作严格失败 | 仓库合同与安装满足；真实错误链待新任务验证 |
| AC-072 稳定候选后集中验证 | 用户仍补充内容时停止扩展完整回归；准备发布后集中完成 102 项 taskctl、零模型基础设施、detached evidence、部署 Validate 与 Publish 内回归 | 满足 |
| AC-073 当前动作局部快速路径 | owner/契约/验收/共享未知/职责变化形成统一直接闭环条件，机械文档与规格明确局部实现用例的 Routing/Policy 合同通过 | 仓库合同与安装满足；真实路由待新任务观察 |

## 职责与消费者闭合

- `docs/requirements.md` 持有纵向消费者与可观察行为目标；`global/AGENTS.md` 只保留维度化最小验证、反例熔断并写回、模型错误归责、领域 runner 升级和工具现态复现等跨项目不变量。
- `execution-governor` 是运行期下一动作 owner，但不持有计划、任务状态或完成结论；`delivery-workflow`、`task-table-manager`、`change-governance` 与 `reasoning-governor` 各自只消费其控制结论并维护原职责。
- `task-table-manager` 在原 task/state/result owner 内分别保存验证维度、执行检查点和直接覆盖；`context` 同源投影关联 DCR，没有新增恢复文件、日志、缓存、Hook 或 Goal 字段。
- `source-query` 只在现态能力/错误/降级待裁时加载诊断引用；领域 runner 的具体命令继续由领域 owner 维护。
- `development/skill-routing` 的 `oracle_revalidation` 只复用精确原结果并链接旧失败收据，不改变模型可见输入或绕过当前 oracle；总收据、历史和 merge 仍受原门禁。
- 114/114 Routing、114/114 Policy、45/45 References、102 项 taskctl 回归和零模型基础设施均通过；这些只证明仓库合同、粗粒度行为标签与引用选择，不提升为真实任务行为证明。

## 第二版完成判定

第二版仓库候选已闭合可观察行为责任、证据检查点、验证维度、工具诊断、领域 runner 升级和 oracle-only 恢复机制。从 Git 暂存索引构造的独立临时 worktree 已通过正式 Validate（46 项基线测试），当前组合工作树也通过 67 项测试；后者包含接手时已有的 Windows SWE dirty 候选，只证明组合兼容，不纳入本次提交或完成声明。该结论只证明未发布仓库候选，不证明真实 Codex 已加载或 UE 运行期行为已改变；安装状态保持上次已发布版本，真实行为验收必须在用户另行明确同意 Publish 后的新任务中进行。

## 第三版完成判定

第三版 SOL-014—SOL-020 已在稳定候选上完成 102 项 taskctl 回归、5 项受影响 skill 结构检查、114-case 静态合同、6-suite 零模型路由基础设施、114/114 Routing、114/114 Policy、45/45 References 和部署 Validate。路由恢复同时补齐跨 generation 的旧 oracle 失败收据复核：只有当前 oracle、stage 身份、文件哈希、evaluator 与不可变上一代账本链全部一致时才形成零 Token passed 收据，不能晋升身份、结构或执行失败。

用户针对本次 Publish 明确授权后，`DirectCompatibility + InstallPortableSettings` 写入 20 个受管资产并创建正式回滚备份；同范围 Status 返回 `published:true`。因此第三版仓库合同、正式 evidence、部署合同和真实安装已闭合，当前没有本版本开放源码实施项。该完成判定不外推为当前已启动任务已经加载新规则，也不证明真实 UE、子代理或昂贵 runner 行为已改变；这些行为边界由新任务中的实际消费者证据继续检验，出现反例时按 AC-066 重开。
