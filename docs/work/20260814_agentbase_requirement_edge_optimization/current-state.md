# AgentBase 根需求收益边缘持续优化：现状分析

## OBS-001 当前项目与安装状态一致

- 状态: confirmed
- 来源: Git 与正式部署 `Status` 直接读回
- 关联: DES-001, AC-002

2026-08-14 基线：工作区干净，`HEAD=9381bcf`；DirectCompatibility 受管 payload 的项目、安装、发布清单与路由证据哈希一致，`managed_payload_formally_published=true`，无发布差距。

## OBS-002 根需求尚未完整进入运行时内核

- 状态: confirmed
- 来源: `docs/requirements.md` 与 `global/AGENTS.md`、适用 skill 的直接文本对照
- 关联: DES-001, REQ-001

项目根需求已明确主动洞察、共同协作维护、质量优先于 Token、Token 优先于速度以及防止下游目标偏移；当前全局内核仍主要表述“用户明确表达用于确定目标”和按长期净收益选型，未直接建立上述协作起点与不可倒置优化顺序。`delivery-workflow` 也从“与用户商议确认”直接进入设计，未明确先形成需求洞察并持续复核下游是否偏离共同确认目标。

## GAP-001 运行时不能稳定推出新增根需求

- 状态: confirmed
- 来源: OBS-002 与 DES-001 的差距
- 关联: OBS-002, DES-001, AC-001

仅保存项目需求文档不能改变其他项目中的模型行为；若不在全局 owner 与复杂交付消费者中以最低充分规则承接，新根需求仍是未接入的规范资产。

## OBS-003 全局常驻规则逼近大小上限

- 状态: confirmed
- 来源: 第 1 轮发布后项目真源的文件字节数与逐条职责审查
- 关联: DES-001, DES-002, CON-001

第 1 轮完成后 `global/AGENTS.md` 为 20,231 字节，距 20 KiB 合同上限只剩 249 字节，并在所有适用项目常驻加载。授权、必要职责调整、预期外发现、测试职责和记录交付中的若干相邻条款重复表达同一动作边界；这既放大常驻 Token，也使后续新增一个真正必要的跨项目不变量缺少安全余量。

## GAP-002 全局内核存在可无损合并的重复成本

- 状态: confirmed
- 来源: OBS-003 与 `docs/requirements.md` AC-005、AC-006、AC-007 的差距
- 关联: OBS-003, DES-001, AC-001

在不改变目标、授权、职责、验证和完成边界的前提下，可通过合并同义证据条款、删除已被上位必要性规则完整蕴含的重复句、缩短不改变动作的修饰语，降低每个项目的固定上下文成本；只调整大小阈值或删除独立边界都不能解决该差距。

## OBS-004 skill 触发边界存在双处定义

- 状态: confirmed
- 来源: 第 2 轮发布后的全局路由段、13 个 `SKILL.md` frontmatter 与 detached capsule 构建合同直接对照
- 关联: DES-001, DES-002, CON-001

全局内核逐项复制了 12 类 skill 的触发条件，而 Codex 路由时可见的各 `SKILL.md` `description` 已由对应 skill 自身定义适用范围，关键边界包含明确非触发条件；静态合同和 detached capsule 也逐个绑定并验证这些 description。两处文本共同决定同一选择会增加所有任务的固定上下文，并可能在单边更新后漂移。

## GAP-003 skill 路由触发存在第二规范源

- 状态: confirmed
- 来源: OBS-004 与 `docs/requirements.md` AC-006、AC-007 的差距
- 关联: OBS-004, DES-001, AC-001

全局只需定义“按可用 skill description 的正负边界选择最小充分集合”的跨项目不变量；具体 skill 的触发与非触发条件应只由该 skill 的 description 维护。保留逐项清单没有独立消费者，删除后可由现有全量路由评估直接验证行为是否保持。

## OBS-005 独立路由 capsule 提前暴露 skill 正文

- 状态: confirmed
- 来源: 第 3 轮最终证据审计与 `routing_evaluation_common.ps1` 直接检查
- 关联: DES-001, DES-002, CON-001

第 3 轮已把首次路由权威收敛到 skill description，但当前 detached capsule 同时嵌入了每个完整 `SKILL.md` 与 metadata，并要求评估器一次性选择 skill 和治理引用。真实加载顺序应先依 description 选择 skill，再读取已选 skill 正文决定引用；现有 57/57 结果因此只能证明“看到完整正文时可以给出正确选择”，不能直接证明首次路由只依赖 description。

## GAP-004 路由证据证明对象与真实加载顺序不一致

- 状态: confirmed
- 来源: OBS-005 与 `docs/requirements.md` AC-007、AC-026、AC-028 的差距
- 关联: OBS-005, DES-001, AC-001

若发布门禁继续接受单阶段结果，后置正文可能掩盖 description 缺失或歧义，削弱第 3 轮单一权威入口的证据。应把首次 skill/策略选择与后置治理引用选择分阶段隔离，并让正式证据同时绑定两个阶段，而不是通过新增用例或提高评估模型能力弥补证明对象错误。

## OBS-006 评估专用策略标签仍进入首次路由输入

- 状态: confirmed
- 来源: 第 4 轮发布后的首次 capsule 与 `trigger-cases.json` 直接对照
- 关联: DES-001, DES-002, CON-001

首次 capsule 已不再暴露 skill 正文，但仍同时提供 `authority_lifecycle`、`document_authority`、`protected_user_baseline` 等行为标签定义并要求同一次运行选择标签。这些定义是开发评估 oracle 的解释材料，不是 Codex 首次 skill 路由时独立可见的运行时输入；其中若干定义与 `change-governance`、`delivery-workflow`、`task-table-manager` 的职责高度同构，可能向评估器补充 description 之外的路由线索。

## GAP-005 首次路由证据仍被后置策略判断污染

- 状态: confirmed
- 来源: OBS-006 与 `docs/requirements.md` AC-006、AC-007、AC-026、AC-028 的差距
- 关联: OBS-006, DES-001, AC-001

第 4 轮已经证明“没有 skill 正文时可以完成路由与策略联合判断”，但尚未单独证明“只依全局规则、skill description、可用外部 skill description 和请求即可完成首次 skill 路由”。应让路由选择、规则行为判断和选中后的引用判断各自只看到真实需要的输入；增加隔离阶段的成本低于继续保留证明混淆的发布门禁。

首次无策略提示的独立反例进一步显示，`full-delivery-chain` 的旧 oracle 要求在开始交付链时同时加载 `change-governance` 和完成审计引用；但 `delivery-workflow` 已明确只在最终复核实际跨越受保护目标与证据时再调用该专项能力。旧期望把后续阶段依赖前移到首次动作，违反渐进加载边界，因此本差距同时包含输入污染和 oracle 时点错误。

三阶段合并还直接复现了另一处同类边界偏差：评估器给出合法的 `+00:00` UTC ISO-8601 时间，旧验证器却只接受字面 `Z`。两者表达同一零偏移时间，限制字面形式不能提高证据身份质量，只会让机械门禁超出其风险证明范围。

独立规则行为评估还区分了两个被旧 oracle 重叠的判断：`authority-change-impact-closure` 已有公共契约与 owner，本次必需动作是让契约变化穿透消费者并形成 `impact_closure`；它不涉及把尚未归位的行为接入新 owner 或入口，因此 `architecture_integrated` 不是该请求的必然标签。把两者同时设为硬预期会模糊职责形成与后续传播的生命周期边界。

## OBS-007 根需求审计已达到当前收益边缘

- 状态: confirmed
- 来源: 第 5 轮发布后对根需求、运行时 owner、验证证据和剩余候选的逐项复核
- 关联: DES-001, DES-002, AC-003, CON-001

当前全局内核已承接协作洞察、质量—Token—速度优先级、渐进加载、证据与授权、公共职责生命周期及辅助工具边界；`delivery-workflow` 承接需求、用户设计、模型设计和持续防偏离，`task-table-manager` 承接跨轮任务与同快照恢复，`change-governance` 承接公共职责和权威变化的影响闭包，部署链承接三阶段独立证据、唯一发布入口与发布后身份读回。静态合同、三个隔离评估阶段、受影响 skill 回归、部署 `Validate`、`Publish` 和 `Status` 均无适用失败。

剩余可设想的改动没有形成新的直接需求差距：把引用盲评扩展到所有 skill 会新增大量没有已知故障驱动的 oracle；操作系统级评估沙箱会引入宿主依赖，而当前合同只要求可审计的脱离仓库输入隔离；插件分发迁移仍取决于目标环境先独立验证插件安装，当前 DirectCompatibility 已保持单一入口且无冲突；继续压缩 15,981 字节的全局内核尚未发现可无损合并的独立规范事实。它们的预期收益不足以覆盖复杂度、Token、迁移和回归成本，继续实施反而可能降低质量，因此按当前证据停止新增轮次。

## OBS-008 真实代理优化实践揭示完整决策链成本

- 状态: confirmed
- 日期: 2026-08-16
- 来源: Source Query Gateway P10 的受监控真实 Codex 运行、命令链审计与 detached completion audit
- 关联: DES-002, REQ-001, AC-001, CON-001

P10 以 P9 的同质量结果 `1,150,528` Token、48 次命令、`363.163 s` 为最近可比参照，连续审查 v1—v21。v3 曾降至 `542,658` Token，但缺少逐项定位、快照限定并发生 benchmark 污染；v4 将原则展开成同次调用、全部锚点等操作配方后回升至 `720,707` Token；v5 加入 8192 默认预算并扩大 skill 触发后回升至 `823,177` Token。它们直接证明局部输出更短、预算更大或命令更具体，均不能替代质量和实验身份。

命令链还证明了 owner 归属对总成本的决定性影响：v19 的纯只读定位误用了 AgentBase“修改前读取 README”条款，完整运行达到 `1,340,388` Token、51 次命令；修正最近项目规则的适用边界后，相同受影响六次由 `778,895` 降至 `528,450` Token、20 次命令，且不再读取根 README。若在全局路由或工具中增加补偿特例，既不能修正错误 owner，也会增加所有消费者的长期成本。

最终 v21 达到 required、行限和 evidence complete 12/12，45 次命令无失败，总 Token `1,066,470`，相对 P9 降低 `7.31%`；耗时 `480.739 s`，相对 P9 上升 `32.38%`。因此只证明质量保持且 Token 改善，不证明速度改善。详细逐调用证据、各轮事实与完成审计见 [P10 往返审计](../../../development/source-query-gateway/evidence/round-trip-audit-p10.md)、[P10 分支计划的日期化汇总](../../../development/source-query-gateway/plan.md#38-2026-08-16-p10-实践证据与总体计划复核)和 [P10 完成审计](../../../development/source-query-gateway/evidence/completion-audit-p10.md)。

## GAP-006 总体优化计划缺少可复用的因果采纳合同

- 状态: confirmed
- 来源: OBS-008 与 DES-002 的对照
- 关联: OBS-008, DES-002, REQ-001, AC-001, CON-001

DES-002 已规定每轮选择最高净收益差距及“质量—Token—速度”的顺序，但尚未明确：优化对象必须是模型获得充分证据并形成结论的完整决策链；候选必须与最近的同质量、同环境、可比 identity 比较；低成本但质量或隔离无效的运行不得成为目标；原因须由可观察命令、工具结果、推理摘要和最终回答归入真实 owner；一次只改变一个可解释机制且机制未变时不得为期待不同结果重跑。2026-08-16 复核时，这些边界只存在于专项分支和本日期化交付链，README 与项目权威划分均没有项目总计划入口；后续全局规则、skill、工具或验证优化仍可能无法发现它们，并重复局部 stdout 优化、微观命令配方、错误 owner 补偿和无效低成本追逐。
