# 原生会话按需审计

## 来源与职责

`scripts/read_codex_session_audit.py` 只读消费一个明确指定的 Codex 原生 session JSONL。它维护事件解析、筛选、聚合和模型投影；原生会话仍是事件真源，项目 Hook 恢复记录和任务文档各守原职责。使用者是正在追溯行为的模型或程序，不是每轮自动 Hook。此入口取代为子代理计数和等待分析临时编写的日志解析，不修改原始记录、不复制全量日志、不写审计缓存。

先从已确认任务、宿主任务读取工具或 Hook 的 `transcript_path` 定位精确文件；需要文件发现时只在已知日期/任务范围内查询。不要把任务标题猜成文件名，不递归扫描整个 Codex home。缺少来源就报告缺失。归档删除后不会制造历史；重新执行入口即可从仍存在的真源重建投影。

## 调用

```powershell
$SkillDir = '<skill_dir>'
$Transcript = '<已确认的原生会话 JSONL 绝对路径>'
python.exe (Join-Path $SkillDir 'scripts\read_codex_session_audit.py') --transcript $Transcript --mode agents
python.exe (Join-Path $SkillDir 'scripts\read_codex_session_audit.py') --transcript $Transcript --mode waits --from-time '2026-09-08T00:00:00+08:00' --to-time '2026-09-08T01:00:00+08:00'
```

- `agents`：直接创建调用及其返回结果、角色、源行号和后续派任务次数。创建失败、未知或尚未返回与成功创建分别统计；明确错误优先于返回的任务名称或身份。名称只帮助定位，不能把调用尝试算成真实子代理。
- `waits`：等待开始、结束、超时/唤醒/未知/尚未返回以及可配对的墙钟时长。
- `timeline`：创建、复用、发消息、等待、工具调用、命令完成、文件变更、输入、公开进度与压缩等可观察事件。需要审阅公开进度或命令原文时才加 `--include-text`，每项最多投影 400 字符并沿用脱敏；完整内容仍按行号定向取自原始来源。任何模式均不输出推理正文、加密消息或完整工具结果。

时间过滤使用带时区的 ISO 时间，范围为 `[from-time, to-time)`，按事件开始时间选择；选中等待的完成时间可落在窗口外。一次读完整个有界文件以配对，不因时间过滤宣称只读取了该时间段。默认最多扫描 128 MiB、单行 4 MiB、100,000 个投影事件；超限须按提示显式调整 `--max-scan-bytes`（上限 512 MiB）或 `--max-line-bytes`（上限 8 MiB），事件数超限则选择更小的来源。非法行、超长行、不完整尾行、未知事件形式和读取中变化都进入 `coverage.issues`。

## 输出、分页与结论

默认模型视图使用既有保守 Token 估算，预算 2,048；`--model-token-budget` 可显式提高。默认每页最多 20 项，`--limit` 上限 100，预算可进一步减小当页。`page.returned` 与 `page.next_offset` 始终按实际返回项计算；summary 对应整个筛选范围，不随分页累加。

有下一页时，保留原文件、模式、时间过滤和文本选项，使用返回的 `page.next_offset`、`snapshot.bytes`、`snapshot.modified`：

```powershell
python.exe (Join-Path $SkillDir 'scripts\read_codex_session_audit.py') --transcript $Transcript --mode waits --offset 20 --snapshot-size 12345 --snapshot-modified '2026-09-08T00:00:00+00:00'
```

上述分页值是示意，必须替换为同一次查询的返回值。来源大小或修改时间变化会拒绝跨页混用；运行中的会话继续追加时，从第 0 页重新查询。读取途中变化时本次统计只是已读前缀观察，不得合并为完整历史；源行号供重新定位，不是跨改写的永久身份。

程序显式使用 `--view machine` 消费 `codex.session-audit/v1`；它与模型视图共享一次解析结果，保留机器侧会话/父会话身份、可用的子会话身份和完整当页结构，不等于输出原始信封。模型面仅显示角色、任务路径和源行号；需要定位某个子会话时，程序按所选行读取机器身份，再通过宿主任务入口或已知范围定位该子会话。逐个审阅子会话才能补足下一层关系，本文件没有子创建事件不证明整棵代理树不存在孙代理。

`coverage.complete_scan` 只说明本次文件扫描没有已识别的读取缺口；不证明宿主记录了全部行为，也不证明加密内容可见。待返回等待与创建单独计数；等待时长含工具开销。`timeout_gaps_without_observed_activity` 仅表示超时返回与下一次等待之间未观察到输入、代理消息、工具或文件动作等事件；公开进度播报不算新证据，但这些间隙不能直接判成无意义思考或 Token 浪费。检查相关 timeline 后，由模型按当前目标判断必要性，不由脚本签发效率或完成结论。
