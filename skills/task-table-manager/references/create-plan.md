# 创建或修改 v1 计划

只在创建 `plan.json` 或修改计划合同时读取。复制 `assets/templates/plan.json`，保留 `strict_v2`；`state.json` 只能由 `activate` 生成。每个新计划和 candidate 修订都必须把 `semantic_preflight.mode` 明确改成适用的合同并填写原因。

## 先审语义，后用 CLI

1. 直接读取并冻结用户要求、正式设计、完整实现差距和实施方案。每个稳定 ID、正文、依赖和状态必须存在于它真正所属的上游文件；缺 ID 就先修改上游。不得先写任务，再让同一生成器制造“追踪真源”。
2. 正向逐条检查要求是否进入设计、差距、方案和验收；反向检查每个方案动作是否有要求与未满足差距来源。主动检查至少一个会推翻当前映射的反例。未知项保持未知，不能用表格完整或测试绿色补足。
3. `scope_sources` 直接登记这些真实文件、完整 ID inventory 和 `file_sha256`。生成目录、任务投影、旧任务表和同一任务模型生成的 ledger 只能是背景资料，不能拥有上游语义。
4. `audit-plan` 只能检查 schema、ID 集合、依赖、指纹和跨层引用；它不能判断正文含义是否一致。普通非迁移计划使用 `{"mode":"not_applicable","reason":"..."}`；不得用该模式规避实际迁移预检。

## 大规模迁移的项目级语义预检

批量替换、历史身份重映射、跨 owner 迁移或机器生成大量任务分配时，在 `plan.json` 根登记项目级预检：

```json
{
  "semantic_preflight": {
    "mode": "required",
    "reason": "bulk historical identities require an implementation-entry semantic freeze",
    "receipt_ref": "semantic-preflight.<revision>.json",
    "identity_source_id": "migration-inventory",
    "producer_source_id": "semantic-preflight-verifier",
    "scope_source_ids": [
      "migration-inventory",
      "semantic-preflight-verifier"
    ],
    "expected_total_count": 1000,
    "identity_set_fingerprint": "sha256:<canonical-sorted-identity-array-hash>",
    "required_dimensions": [
      "owner",
      "successor_contract",
      "disposition",
      "lifecycle",
      "input_output",
      "evidence_binding"
    ]
  }
}
```

1. 把逐项 inventory 与项目验证器作为两个引用不同文件的 `file_sha256` scope source；无 requirements 时使用 `inventory_mode: advisory` 和空 `requirement_ids`。`identity_source_id` 指向 inventory，`producer_source_id` 指向验证器，两者都进入 `scope_source_ids`。按设计修订使用独立 `receipt_ref`，不要覆盖活动修订的回执。
2. 让项目验证器逐项冻结正确 owner、精确现有 successor 或明确的新合同/gap、保留/迁移/不支持/删除处置、生命周期、输入输出责任以及所需测试或产品证据绑定。未知项直接计入未决；禁止 `and/or`、`equivalent`、namespace 推断或“owner 以后解决”。
3. 令 identity ID 去重后按 Unicode 字符序排序；对该数组按 UTF-8、`ensure_ascii=false`、无空白 JSON（`,`/`:` 分隔）计算 SHA-256，写入计划和回执的 `identity_set_fingerprint`。回执必须携带同一 `identities` 数组；CLI 会核对排序、唯一性、数组 hash、`expected_total_count` 与 `counts.total_count`。
4. 从 `<SkillDir>/assets/templates/semantic-preflight.json` 生成通用 adapter 回执；项目逐项决策和领域验证器继续留在任务目录。`resolved_count + unresolved_count` 必须等于总数，placeholder、duplicate 和六个核心维度都单独计数。用错误 owner、未知 successor、缺行、重复行、无关证据、占位文本、错误总数和身份 hash 漂移做项目级反例测试。
5. 运行 `audit-plan`。新计划或 candidate 缺少显式模式时返回 `blocked`；`required` 回执缺失、无效或非零未决时返回 `blocked`；只有 `not_applicable` 已说明原因，或当前来源指纹、identity 集合和全部计数闭合时才返回 `ready`。

已有 `state.json` 且没有策略的旧计划只以 `legacy_structural_only` 继续；使用旧 `task.semantic-preflight.v1` 且原回执仍通过的活动计划只以 `legacy_semantic_v1` 继续，原回执存在债务时仍阻断。两者都不能被解释成新版语义 READY，所有下一次 `amend` 必须显式选择模式并升级 v2。控制器身份会随 skill/tool 版本变化；已有活动包必须先用原控制器完成或 `checkpoint --release`，不得在包执行中热切换已安装 skill。进度分别报告任务状态、`semantic_preflight.unresolved_count` 和真实产品证据闭合度；任何一项不得代替另两项。

## 任务建模

- Requirement 保存用户可观察结果；acceptance clause 是不可再删减而仍保持原意的完成条件，使用真实验证主体和 claims。派生的新验收语义必须有用户裁决。
- design clause 说明满足验收的职责、接口和依赖；solution step 写实际动作、结果、依赖与禁止依赖；gap 只写目标相对当前实现的事实、直接证据和可证明上限，不写根因或方案。
- 只为未满足 gap 建任务。任务依赖必须实现 solution 依赖；不同 owner、identity、lifecycle、persistence、build 或 rollback 尚未证明相同时不得合包。大量同类项使用任务目录内的机器清单逐项分配，但通用 `taskctl` 不判断领域语义。
- outcome、completion level、claim scope、测试与 readback 必须和实际证据层级一致。没有正式入口证据不得称 public/production-ready；代表样例不得称 domain complete。
- 测试先裁决 requirement、oracle、baseline、negative path、claims、真实 subject 与入口层级。旧测试默认不可信；无法证明 oracle 的测试保持 invalid 或退出活动 Gate。
- producer 只登记真实工具。Agent 文本、手写 `pass`、mock 或 recording 不能完成业务 claim。freshness 只覆盖真实影响范围，避免宽 glob 让无关任务反复失效。
- tests-first 是同一工作包内的顺序约束，不拆成独立管理任务。acceptance flow 只用于确实需要纵向证明的用户流程，不为每个模块制造流程对象。

## 激活与修订

```text
python <taskctl> validate --task-dir <AbsoluteTaskDir>
python <taskctl> audit-plan --task-dir <AbsoluteTaskDir>
python <taskctl> activate --task-dir <AbsoluteTaskDir>
```

激活后禁止直接改 `plan.json/state.json`。上游变化时先释放活动包，修改最早真源并提升 `design_revision`，重做语义审计，再对候选运行 `audit-plan --candidate` 和 `amend`。缩小要求、outcome、claim、测试、readback 或 freshness 必须记录用户裁决。

最终 `audit --all` 只有在当前 planning receipt、全部任务和必要 acceptance flow 均成立时才生成 completion receipt；结构回执不得被描述为语义审计通过。
