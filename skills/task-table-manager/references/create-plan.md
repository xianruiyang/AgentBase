# 创建或修改 v1 计划

只在创建 `plan.json` 或修改计划合同时读取。复制 `assets/templates/plan.json`，保留 `strict_v2`；`state.json` 只能由 `activate` 生成。

## 先审语义，后用 CLI

1. 直接读取并冻结用户要求、正式设计、完整实现差距和实施方案。每个稳定 ID、正文、依赖和状态必须存在于它真正所属的上游文件；缺 ID 就先修改上游。不得先写任务，再让同一生成器制造“追踪真源”。
2. 正向逐条检查要求是否进入设计、差距、方案和验收；反向检查每个方案动作是否有要求与未满足差距来源。主动检查至少一个会推翻当前映射的反例。未知项保持未知，不能用表格完整或测试绿色补足。
3. `scope_sources` 直接登记这些真实文件、完整 ID inventory 和 `file_sha256`。生成目录、任务投影、旧任务表和同一任务模型生成的 ledger 只能是背景资料，不能拥有上游语义。
4. `audit-plan` 只能检查 schema、ID 集合、依赖、指纹和跨层引用；它不能判断正文含义是否一致。语义审计未通过时不得因为 CLI 返回 `ok` 而激活。

## 大规模迁移的项目级语义预检

批量替换、历史身份重映射、跨 owner 迁移或机器生成大量任务分配时，在 `plan.json` 根登记项目级预检：

```json
{
  "semantic_preflight": {
    "receipt_ref": "semantic-preflight.<revision>.json",
    "producer_source_id": "semantic-preflight-verifier",
    "scope_source_ids": [
      "migration-inventory",
      "semantic-preflight-verifier"
    ],
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

1. 把逐项 inventory 与项目验证器都登记为 `file_sha256` scope source；按设计修订使用独立 `receipt_ref`，不要覆盖活动修订的回执。
2. 让项目验证器逐项冻结正确 owner、精确现有 successor 或明确的新合同/gap、保留/迁移/不支持/删除处置、生命周期、输入输出责任以及所需测试或产品证据绑定。未知项直接计入未决；禁止 `and/or`、`equivalent`、namespace 推断或“owner 以后解决”。
3. 从 `<SkillDir>/assets/templates/semantic-preflight.json` 生成项目回执。`total_count` 取预期唯一 identity 总数，`resolved_count + unresolved_count` 必须与其相等；placeholder、duplicate 和每个 required dimension 都单独计数。用错误 owner、未知 successor、缺行、重复行、无关证据和占位文本做项目级反例测试。
4. 运行 `audit-plan`。未声明预检的兼容计划只得到 `execution_readiness=structural_only`；已声明但回执缺失、无效或非零未决时返回 `blocked` 和非零退出码；只有当前来源指纹匹配且全部计数闭合时才返回 `ready`。

旧计划的 plan/state schema 保持兼容，但控制器身份会随 skill/tool 版本变化；已有活动包必须先用原控制器完成或 `checkpoint --release`，不得在包执行中热切换已安装 skill。更新后，在下一次涉及大规模迁移合同的 `amend` 中加入预检。进度分别报告任务状态、`semantic_preflight.unresolved_count` 和真实产品证据闭合度；任何一项不得代替另两项。

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
