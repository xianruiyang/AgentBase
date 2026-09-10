# 原生会话按需审计

## 来源与职责

`scripts/read_codex_session_audit.py` 只读消费一个明确指定的 Codex 原生 session JSONL，负责事件解析、筛选、聚合和模型投影。原生会话仍是事件真源，项目 Hook 恢复记录和任务文档各守原职责；消费者是追溯行为的模型或程序，不是每轮自动 Hook。此入口取代为子代理计数和等待分析临时编写的解析，不修改原始记录、不复制全量日志、不写审计缓存。

先从已确认任务、宿主任务读取工具或 Hook 的 `transcript_path` 定位文件；需要发现时只查已知日期/任务范围。不把任务标题猜成文件名，不递归扫描整个 Codex home；缺少来源即报告。归档删除后不制造历史，重新执行即可从仍存真源重建投影。

## 调用

```powershell
$SkillDir = '<skill_dir>'
$Transcript = '<已确认的原生会话 JSONL 绝对路径>'
python.exe (Join-Path $SkillDir 'scripts\read_codex_session_audit.py') --transcript $Transcript --mode agents
python.exe (Join-Path $SkillDir 'scripts\read_codex_session_audit.py') --transcript $Transcript --mode waits --from-time '2026-09-08T00:00:00+08:00' --to-time '2026-09-08T01:00:00+08:00'
```

- `agents`：直接创建调用及其返回结果、角色、源行号和后续派任务次数。创建失败、未知或尚未返回与成功创建分别统计；明确错误优先于返回的任务名称或身份。名称只帮助定位，不能把调用尝试算成真实子代理。
- `waits`：等待开始、结束、超时/唤醒/未知/尚未返回以及可配对的墙钟时长。
- `timeline`：创建、复用、发消息、等待、工具调用、命令完成、文件变更、输入、公开进度与压缩等可观察事件。仅审阅公开进度或命令原文时加 `--include-text`；每项最多投影 400 字符并沿用脱敏，完整内容仍按行号从原始来源定向读取。任何模式均不输出推理正文、加密消息或完整工具结果。

时间过滤使用带时区的 ISO 时间和 `[from-time, to-time)` 范围，按事件开始时间选择；所选等待可在窗口外完成。为配对会读取整个有界文件，不因过滤声称只读了该时段。默认最多扫描 128 MiB、单行 4 MiB、100,000 个投影事件；超限须按提示显式调整 `--max-scan-bytes`（上限 512 MiB）或 `--max-line-bytes`（上限 8 MiB），事件数超限则缩小来源。非法行、超长行、不完整尾行、未知事件和读取中变化均进入 `coverage.issues`。

## 输出、分页与结论

默认模型视图采用既有保守 Token 估算，预算 2,048，可用 `--model-token-budget` 显式提高。每页默认最多 20 项，`--limit` 上限 100，预算还可缩小当页；`page.returned` 与 `page.next_offset` 按实际返回项计算，summary 对应整个筛选范围且不随分页累加。

有下一页时，保留原文件、模式、时间过滤和文本选项，使用返回的 `page.next_offset`、`snapshot.bytes`、`snapshot.modified`：

```powershell
python.exe (Join-Path $SkillDir 'scripts\read_codex_session_audit.py') --transcript $Transcript --mode waits --offset 20 --snapshot-size 12345 --snapshot-modified '2026-09-08T00:00:00+00:00'
```

分页值仅为示意，必须替换为同次查询返回值。来源大小或修改时间变化会拒绝跨页混用；运行中会话继续追加时从第 0 页重查。读取途中发生变化，则统计仅代表已读前缀，不得合并为完整历史；源行号只供重新定位，不是跨改写的永久身份。

程序显式使用 `--view machine` 消费 `codex.session-audit/v1`；它与模型视图共享一次解析结果，保留机器侧会话/父会话身份、可用的子会话身份和完整当页结构，不等于输出原始信封。模型面仅显示角色、任务路径和源行号；需要定位某个子会话时，程序按所选行读取机器身份，再通过宿主任务入口或已知范围定位该子会话。逐个审阅子会话才能补足下一层关系，本文件没有子创建事件不证明整棵代理树不存在孙代理。

`coverage.complete_scan` 仅说明本次扫描无已识别读取缺口，不证明宿主记录了全部行为或加密内容可见。待返回等待与创建单独计数，等待时长含工具开销。`timeout_gaps_without_observed_activity` 只表示超时返回至下次等待间未观察到输入、代理消息、工具或文件动作；公开进度不算新证据，也不能据此判定无意义思考或 Token 浪费。模型检查相关 timeline 后按当前目标判断必要性，脚本不签发效率或完成结论。
