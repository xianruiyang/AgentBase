# taskctl 共享入口

工具入口：

```text
python <SkillDir>/scripts/taskctl.py <command> --task-dir <AbsoluteTaskDir>
```

只在 CLI 能降低编辑、查询或恢复成本时使用；任务较少或 CLI 不可用时仍按正式文档合同继续。CLI 不签发开始、推进、完成或重开许可，也不把诊断、状态或计数升级为语义结论。

## 按命令加载

读取本文件后，只增加当前命令族对应引用：

```text
init/draft/add/update                         authoring-tooling.md
show/list/deps/dependents/impact/next/
status/render                                query-tooling.md
context/claim/start/note/complete/reopen/
release                                      execution-tooling.md
completion-context                           completion-tooling.md
```

一个动作跨越多个命令族时读取所有实际需要的引用；不要为发现命令而预读其他族。

## 消费者视图

- `--view model` 是默认值，面向直接进入 Codex 上下文的结果；使用分行的紧凑 HJSON 风格文本，只保留缺失后会改变当前判断、动作、验证或恢复的字段。该视图服务模型阅读，不承诺机器解析。
- `--view machine` 面向程序、测试和完整字段检查，保持稳定紧凑 JSON；需要缩进 JSON 时同时使用 `--pretty`，`--pretty` 不适用于 model 视图。
- 两种视图消费同一个命令 handler 的权威结果；renderer 不重新计算任务状态、诊断、候选关系、分页或证据时效。model 与 machine stdout/stderr 均固定为 UTF-8。
- 模型预算由 `--model-token-budget` 控制并在选择完整语义单元时生效；机器 `context/show/completion-context` 的既有 `--budget` 仍表示 JSON 字符预算。
- 若程序此前依赖默认 JSON，迁移为显式 `--view machine`；没有已证实消费者时不保留第二个隐式默认入口。

## 共享失败边界

门禁只保护路径/对象身份、破坏性覆盖、锁与 CAS 并发、输入输出上限、显式不可变收据身份和最终复核快照一致性。门禁错误返回 `gate.id`、`gate.risk`、`gate.scope`、`gate.recovery` 和 `gate.retryable`；当前命令族的具体门禁由对应引用维护。

依赖环、owner、状态流转、可解析非标准语义、重复值、上游未决、覆盖度、验证充分性、结果来源时效和整体完成均只诊断并交由模型按文档与证据裁决。

`TASK_TABLE.md` 是可重建派生物。`add/update` 与状态写命令在真源提交后刷新它；刷新失败只返回 `task_table_refresh_failed`、`table_view.status: stale` 和显式 `render` 恢复动作，不得把已提交的 task/state/result 回滚、伪装为未提交或变成生成视图门禁。machine 回执保留成功刷新状态，model 回执省略正常成功，只保留会改变恢复动作的失败诊断。
