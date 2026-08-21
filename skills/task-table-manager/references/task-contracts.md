# 任务合同

## 目录

- [任务文件](#任务文件)
- [字段职责](#字段职责)
- [依赖类型](#依赖类型)
- [任务准入](#任务准入)
- [结果输入与永久文件](#结果输入与永久文件)

## 任务文件

模型交给 `add/update --file` 的 authoring 输入保留稳定任务 ID 与语义正文，不包含 `schema` 或 `revision`：

```json
{
  "id": "T001",
  "title": "实现导出结果的正式入口",
  "outcome": "用户通过正式入口获得约定格式的结果",
  "source_ids": ["SOL-001", "GAP-001", "DES-001", "AC-001", "REQ-001"],
  "dependencies": [
    {"id": "T000", "type": "hard", "consumes": ["公开接口合同"]}
  ],
  "mutation_scope": ["src/export/**"],
  "outputs": ["正式入口", "给 T002 使用的接口行为摘要"],
  "verification": ["运行入口并读回导出内容"]
}
```

工具把该语义输入规范化后保存为唯一 `tasks/<ID>.json` 永久机器记录：

```json
{
  "schema": "task.record",
  "id": "T001",
  "title": "实现导出结果的正式入口",
  "outcome": "用户通过正式入口获得约定格式的结果",
  "source_ids": ["SOL-001", "GAP-001", "DES-001", "AC-001", "REQ-001"],
  "dependencies": [
    {"id": "T000", "type": "hard", "consumes": ["公开接口合同"]}
  ],
  "mutation_scope": ["src/export/**"],
  "outputs": ["正式入口", "给 T002 使用的接口行为摘要"],
  "verification": ["运行入口并读回导出内容"],
  "suggested_skills": [],
  "reasoning_hint": "medium",
  "revision": 1
}
```

任务合同是程序消费、由模型根据上游语义编写的结构化真源。CLI 可用时，模型先形成任务语义，再通过 `draft/add/update` 写入永久记录；`add` 注入 `task.record` 与初始 revision，`update` 使用刚读取的 `--expected-task-revision` 比较并注入下一 revision。模型不能直接编辑 `tasks/*.json` 绕过 CAS、路径和原子写入职责。CLI 不可用时仍按本文永久合同维护，但不得同时保留另一份手工任务清单作为权威来源。

## 字段职责

- `id`：稳定任务身份，格式 `T` 加字母、数字、点、下划线或连字符。
- `title`：具体动作和对象。
- `outcome`：任务完成后真实成立的结果，不写执行过程。
- `source_ids`：精确引用直接支配本任务结果的上游语义条目，不复制其正文；传递祖先由执行上下文的来源快照保留。没有交付链时可以为空，但任务仍需有明确用户来源。
- `dependencies`：只登记真实任务依赖，并说明下游消费什么。
- `mutation_scope`：预计修改的项目相对路径或 glob，用于发现并行重叠，不授权扩大范围，也不决定行为属于哪个职责 owner。
- `outputs`：后继任务或用户会消费的结果；公共产出必须能对应当前消费者或直接用户结果。
- `verification`：与 outcome 同层级的验证方式；允许在探索任务中写明实际可验证边界。
- `suggested_skills`：任务开始时的路由提示，运行时仍按实际工作判断。
- `reasoning_hint`：`low/medium/high/xhigh/max/ultra` 的非权威起始建议。
- `revision`：永久机器记录由工具维护；语义 add 固定从 `1` 开始，update 前读取当前值并以 CAS 参数传回，再由工具递增，避免并发覆盖。模型 authoring 文件不复制该字段。

以上枚举、语义 ID 格式和项目相对描述是文档合同。CLI 对空白、缺失或其他可解析偏差保留原值（缺失文本以空值表达）并报告诊断，由模型决定修订、扩展合同或继续使用；它只对真实存储身份、revision、路径和无法解释的字段类型设门禁。已发布上一版的完整 `task.record` authoring 输入继续由 `add/update` 校验并规范化，但只出现 schema/revision 等部分机器字段的混合输入会被拒绝；兼容不产生第二种永久任务格式。

## 依赖类型

- `hard`：执行主体确实需要前置任务的产出；未完成时 `next` 默认不推荐。
- `ordering`：按此顺序通常降低返工，但不妨碍独立工作。
- `informational`：只提供上下文或可能相关的结果。

不得把所有早期任务都标为 `hard`，也不得把评审偏好伪装成真实依赖。CLI 会把依赖环、自依赖、重复依赖和未完成依赖都报告为诊断；它们可能要求模型修订任务设计，但不由 CLI 禁止读取、领取或更新任务。

`$execution-governor` 已确认多个任务共享未证前提时，证明任务和首个真实消费者产生的可复核证据是后续横向任务的真实消费输入，应按实际阻断关系记录为 `hard`；只有顺序更方便而结果不消费前置证据时仍用 `ordering`。任务表不自行识别或生成这类关系。

## 任务准入

任务应有可交付产出、明确消费者或用户结果、可界定范围和可判断验证。公共能力任务没有当前消费者时，应并入实际接入结果或退回上游裁决，不以创建模块或接口本身满足准入。需求编写、目标设计、现状调查和方案选择属于 `$delivery-workflow` 的阶段产物；只有它们本身需要跨轮执行、存在真实依赖或必须作为长期工作包管理时，才投影为任务。

任务表不得承载原始日志、长证据、完整设计正文或逐轮对话。删除一项不会丢失任何产出、状态变化或必要验证时，应合并或删除该项。

## 结果输入与永久文件

模型交给 `complete --result-file` 的输入只包含本次完成判断的语义正文；空列表字段可以省略：

```json
{
  "outcome": "实际完成的结果",
  "outputs": ["后继任务可直接消费的事实或接口"],
  "changed_files": ["src/export/service.py"],
  "verification": ["pytest tests/export - passed"],
  "evidence_for": ["REQ-001", "AC-001"],
  "evidence_refs": [
    {"ref": "tests/export-readback", "kind": "test", "note": "真实调用并读回"}
  ]
}
```

模型不在该文件重复 `schema`、`task_id`、`task_revision`、`source_snapshot` 或 `source_snapshot_ref`。`complete` 从 `--id` 取得任务身份，以 `--expected-task-revision` 绑定工作实际依据的任务合同，以 `--source-snapshot-ref` 接收执行时捕获的来源收据，并与 `--expected-state-revision` 一起在锁内校验。

`results/<ID>.r<state-revision>.json` 是工具规范化生成的一次完成提交，不可覆盖；历史由这些文件名派生，不在状态文件维护第二份列表。永久机器结果保持完整格式：

```json
{
  "schema": "task.result",
  "task_id": "T001",
  "task_revision": 1,
  "outcome": "实际完成的结果",
  "outputs": ["后继任务可直接消费的事实或接口"],
  "changed_files": ["src/export/service.py"],
  "verification": ["pytest tests/export - passed"],
  "unresolved": [],
  "invalidated_source_ids": [],
  "evidence_for": ["REQ-001", "AC-001", "UDES-001"],
  "evidence_refs": [
    {"ref": "tests/export-readback", "kind": "test", "note": "真实调用并读回"}
  ],
  "source_snapshot_ref": "sha256:..."
}
```

结果正文由模型裁决，机器 envelope 和来源引用由 `complete` 注入，永久文件按下一状态 revision 写入；生成的 `TASK_TABLE.md`、状态摘要或 completion-context 只提供读取面，不能通过编辑它们改写结果、证据或完成状态。

结果内容由模型根据有效证据填写。`evidence_for` 声明证据所支持的上游 ID，`evidence_refs` 指向可直接查看的证据。执行前的 `context --capture` 在最终模型投影后把实际可见直接来源及其传递祖先指纹写入 `snapshots/<sha256>.json`；模型只把返回引用作为 `complete --source-snapshot-ref` 参数，永久结果由工具附加 `source_snapshot_ref`。完成时不得重新采样当前版本替代实际输入。显式收据在新写入前必须存在、可读且内容身份与引用一致，否则本次结果与状态都不改变；未提供收据、覆盖不足或逐来源陈旧只形成对应诊断。已经落盘的历史结果后来出现资产缺失、损坏或身份不一致时仍隔离并诊断，不改写历史指针。CLI 不判断验证文案是否真实，也不把结果文件存在视为产品完成。

后继任务重新执行或验证旧结果覆盖的行为时，提交自己的新结果：`evidence_for` 明确列出本次直接支持的目标或合同 ID，`source_snapshot_ref` 指向本次模型实际读取且覆盖这些 ID 的语义闭包，`verification` 和 `evidence_refs` 指向本次直接复测。旧内联 `source_snapshot` 结果作为真实历史格式继续只读；已发布上一版的完整 `task.result` 输入仍由新写入口校验并规范化，旧式内联输入外部化且永久结果只写引用。该兼容只服务迁移，不定义新模型输入或第二种永久格式。新结果不会回写、抑制或把旧记录标为恢复有效；依赖、任务状态或候选关联本身不声明重新验证。最终复核由模型按目标选择直接适用的当前证据，不由 CLI 合并两个结果的有效性。
