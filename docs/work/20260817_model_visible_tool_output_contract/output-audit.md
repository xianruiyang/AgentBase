# 模型可见工具输出真实审计

## 审计对象与方法

- 环境：2026-08-17 当前 Windows 宿主，项目源码 CLI，未向 Codex 发布。
- 固定真实工作区：`docs/work/20260816_task_result_diagnostic_semantics`；该工作区包含 2 个完成任务、真实结果诊断、来源快照与完整交付文档。
- machine 视图对高成本查询使用 `--budget 100000`，避免既有字符预算提前截断；model 视图使用各命令默认模型预算。
- Token 使用本机 `tiktoken 0.13.0` 的 `o200k_base` 计算；CLI 运行时另外使用与 srcq 同类的保守估算控制预算。该编码器结果证明本次候选的相对成本，不外推为所有未来模型的精确账单。
- 质量检查从同一次 handler 的 machine 事实确定必需信息，再检查 model 是否保留当前任务、直接来源、状态、异常、候选结果、验证和恢复信息；字节或 Token 下降不单独构成通过。

## 真实输出结果

| 场景 | machine tokens | model tokens | model/machine | 质量覆盖 |
| --- | ---: | ---: | ---: | --- |
| taskctl status | 270 | 89 | 0.330 | 保留任务状态、结果进展与 8 项结果诊断；省略 envelope、空数组、零值和完整 baseline |
| taskctl context `T002-VERIFY-DELIVER` | 11,736 | 5,400 | 0.460 | 保留任务、状态、依赖结果、完整执行 `source_snapshot`、6 个直接来源正文和 7 个后继祖先正文；其余祖先以精确 ID 提供渐进恢复 |
| taskctl completion-context `REQ-001` | 5,616 | 1,956 | 0.348 | 保留目标正文、候选任务、结果 outcome/outputs/verification、诊断、证据引用与分页身份；不复制候选完整 `source_snapshot` |
| workctl status | 360 | 85 | 0.236 | 保留阶段摘要、任务进展和实际诊断；省略正常目标保护身份、空值与零值 |
| workctl context `SOL-003` | 1,714 | 1,526 | 0.890 | 保留目标 section、邻接关系、正文、文档与行号；该场景绝大部分 machine 内容本来就是当前动作证据，因此只获得有限降本 |

所有 model 输出均在对应默认预算内；模型错误输出另由组件回归证明保留 `error`、结构化 gate 和 recovery。taskctl 低预算回归保留任务身份、状态与 `more`，workctl 低预算回归保留 section 身份、位置与恢复入口，不再退化为只有“提高字符预算”的提示。

## 表达格式裁决

先完成同一 model 字段投影，再用同一 `o200k_base` 比较 compact JSON 与当前分行紧凑 HJSON 风格 renderer：

| 同一投影 | compact JSON tokens | HJSON 风格 tokens | 最长物理行 |
| --- | ---: | ---: | ---: |
| taskctl status | 96 | 89 | 165 字符 |
| taskctl completion-context | 1,972 | 1,952 | 583 字符 |

因此本版本没有因为用户举例而直接指定 YAML；实际测试中块状 YAML 对上述投影分别为 108 和 2,132 tokens，均高于 compact JSON。当前 HJSON 风格通过省略重复键引号、在顶层分行并把局部对象内联，在所测投影上同时保持可定位结构和最低 Token。model 视图不承诺机器解析，程序继续使用稳定 JSON machine 视图。

## 编码与边界

- 直接宿主复测发现 Python 默认 stdout 为 GBK，而 Codex 终端按 UTF-8 接收；两项 CLI 现自行固定 stdout/stderr UTF-8，并在不设置 `PYTHONUTF8`、不使用 `-X utf8` 的回归入口读回中文。
- 本版本没有改变 `source_snapshot` 的事实表示、结果时效语义或分页合同。task context 保留完成结果直接消费的完整执行快照；completion-context 只省略当前完成判断不消费的映射副本。
- workctl context 的有限降幅是质量优先的预期结果，不为追求统一百分比删除必要正文。当前证据只支持表中场景及同类合同，不声明所有输入固定节省相同比例。
