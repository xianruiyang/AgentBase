# taskctl 使用合同

工具入口：

```text
python <SkillDir>/scripts/taskctl.py <command> --task-dir <AbsoluteTaskDir>
```

## 合同与图查询

```text
init        建立固定 tasks/state/results 目录和 task-table.json
draft       将最小候选任务 JSON 输出到 stdout，不写文件
add         新增一项任务、建立 todo 状态并返回即时软诊断
update      按 expected revision 更新任务合同并返回即时软诊断
show        返回任务合同、状态和结果摘要
list        有界列出任务
deps        返回直接或递归前置任务
dependents  返回直接或递归后继任务
next        返回推荐任务和软诊断
context     在字符预算内组合当前任务、依赖结果、上游条目和后继消费者
completion-context  从受保护基线精确分页 REQ/AC/UDES，再汇总关联结果与验证引用
status      汇总任务、上游未决和结果验证状态
impact      返回任务图中的潜在后继影响
render      生成 TASK_TABLE.md 只读视图
```

## 状态命令

```text
claim       领取任务
start       开始任务
note        写入有界进度、阻塞或下一动作
complete    从结果 JSON 完成任务
reopen      由当前 owner 因明确原因重开已完成任务
release     释放未完成任务
```

写命令返回新的 state revision；后续写入用 `--expected-state-revision` 防止覆盖。`update` 始终使用 `--expected-task-revision`，任务已有 owner 时还必须传相同 `--owner` 和当前 state revision。`reopen` 必须传当前 `--owner`。查询默认使用紧凑 JSON 并限制条目数量，人工阅读时使用 `--pretty`。

`add` 和 `update` 先验证生成诊断所依赖的 task/state 存储集合，再写入并返回当前上游索引能够确定的合同诊断，例如未知 source ID、上游未决、缺少产出或验证。存储损坏会在本次候选落盘前失败；语义诊断帮助模型立即修订任务，但不会回滚成功写入、签发执行许可或判断任务语义正确。

`task-table.json` 的 `tasks/`、`state/`、`results/`、`.work-cache/index.json` 和 `TASK_TABLE.md` 路径是固定存储合同，避免生成物被重定向到语义真源或结果记录。

## 诊断语义

- `next` 中的 `recommended` 只表示当前依赖和状态下适合优先考虑。
- `hard_dependency_incomplete`、`upstream_index_missing`、`upstream_unresolved`、`mutation_overlap`、`verification_empty` 都是提示，不改变状态。
- 依赖环、重复 ID、任务文件与内部 ID 不一致、路径逃逸、非法状态变换和并发 revision 冲突是写入安全错误。
- `status`、`render`、依赖完成和结果文件都不能产生“允许执行”或“产品已经完成”的判定。
- `completion-context` 只建立最终目标到候选证据的有界映射，不返回 pass/fail；目标集合直接来自 `protected-baseline.json`，可修订文档的新增同前缀条目不能扩张它。CLI 会由当前阶段文档重新派生索引并与缓存逐字段比较，缓存陈旧或被改写时返回诊断而不输出候选目标。
- 首次查询返回 `snapshot_id`。目标页使用 `--after-id`；单目标候选任务续页使用 `--target-id` 与 `--candidate-after-id`；约束和延后项分别使用 `--constraint-after-id`、`--deferred-after-id`。所有续页都传首次返回的 `--snapshot-id`，游标在 `pagination` 中返回；任务、状态、结果或索引改变会要求从第一页重新复核。

`context` 的 `--budget` 是字符预算。输出被截断时按返回的任务或语义 ID继续精确查询，不直接读取整个任务目录。
