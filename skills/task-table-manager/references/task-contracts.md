# 任务合同

## 任务文件

每个任务保存为 `tasks/<ID>.json`：

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

## 字段职责

- `id`：稳定任务身份，格式 `T` 加字母、数字、点、下划线或连字符。
- `title`：具体动作和对象。
- `outcome`：任务完成后真实成立的结果，不写执行过程。
- `source_ids`：精确引用上游语义条目，不复制其正文。没有交付链时可以为空，但任务仍需有明确用户来源。
- `dependencies`：只登记真实任务依赖，并说明下游消费什么。
- `mutation_scope`：预计修改的项目相对路径或 glob，用于发现并行重叠，不授权扩大范围。
- `outputs`：后继任务或用户会消费的结果。
- `verification`：与 outcome 同层级的验证方式；允许在探索任务中写明实际可验证边界。
- `suggested_skills`：任务开始时的路由提示，运行时仍按实际工作判断。
- `reasoning_hint`：`low/medium/high/xhigh/max/ultra` 的非权威起始建议。
- `revision`：每次更新递增，避免并发覆盖。

## 依赖类型

- `hard`：执行主体确实需要前置任务的产出；未完成时 `next` 默认不推荐。
- `ordering`：按此顺序通常降低返工，但不妨碍独立工作。
- `informational`：只提供上下文或可能相关的结果。

不得把所有早期任务都标为 `hard`，也不得把评审偏好伪装成真实依赖。CLI 会拒绝依赖环，因为它使任务图身份不明确；不会因依赖尚未完成而禁止读取、领取或更新任务。

## 任务准入

任务应有可交付产出、明确消费者或用户结果、可界定范围和可判断验证。需求编写、目标设计、现状调查和方案选择属于 `$delivery-workflow` 的阶段产物；只有它们本身需要跨轮执行、存在真实依赖或必须作为长期工作包管理时，才投影为任务。

任务表不得承载原始日志、长证据、完整设计正文或逐轮对话。删除一项不会丢失任何产出、状态变化或必要验证时，应合并或删除该项。

## 结果文件

`results/<ID>.r<state-revision>.json` 保存一次完成提交的不可覆盖摘要；历史由这些文件名派生，不在状态文件维护第二份列表：

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
  "invalidated_source_ids": []
}
```

结果内容由模型根据有效证据填写。CLI 校验每份历史结果的目录、身份和任务修订，并由状态文件只指向当前结果；重开后保留历史结果但不再把它当成当前证据。CLI 不判断验证文案是否真实，也不把结果文件存在视为产品完成。
