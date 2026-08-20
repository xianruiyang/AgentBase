# scc 查询合同

仅在普通 `srcq scc <scc argv...>` 的最低充分结果无法完成判断，或任务明确需要 files、hotspots、lossless、raw、machine、native、artifact、结构化续页或输出副作用时读取。运行时为用户 PATH 中的 `srcq.exe`，由它启动 PATH 中的 `scc.exe`；只支持 Windows x86_64，普通统计不读取本引用。

## 入口与视图

```text
srcq scc <scc argv...>
srcq query scc <exec|defaults> [wrapper options] -- <scc argv...>
srcq query scc doctor [--engine PATH] [--cwd PATH]
```

普通入口使用 model/auto，并在可结构化的常规统计中注入 `--format=json`。auto 默认提供语言汇总；原生 `--by-file` 时提供文件记录。显式控制面的 `--view` 支持 `summary`、`languages`、`files`、`hotspots`、`lossless` 与 `raw`：

- `summary` 聚合文件、代码、注释、空行、行数、复杂度和字节数；`languages` 保留逐语言指标。
- `files` 只在原生 argv 含 `--by-file` 时可用，按稳定路径分页；`hotspots` 从同一文件记录按复杂度、代码行和路径稳定排序，不声称发现缺陷。
- `lossless` 保留 scc 的完整 JSON 结构；`raw` 或 `--artifact-out` 保留完整原生字节。只有模型确需缺失字段或程序需复核时才使用，不把大型产物直接读入上下文。
- `machine` 返回稳定的 srcq 协议、归一化语言或文件记录、query snapshot 和精确 cursor；程序不得从 model 文本反推字段。

默认模型投影有意省略 COCOMO、estimated cost、schedule 与 people 等成本推算。复杂度同样只是 scc 的词法启发式指标，适合定位复核候选，不等于缺陷、可维护性结论、实际工期或完成状态。需要这些原始字段时使用 lossless 或 artifact，并在结论中保留估算边界。

## 原生模式与副作用

`--format` 的显式非 JSON 格式、`--help`、`--version` 和 `--languages` 使用有界文本，不再注入 JSON。`--output` / `-o` 与 `--format-multi` 可能写文件，srcq 只透传且不把文件存在解释为统计已验证；执行前必须已有相应外部写入授权。普通扫描保持只读。

wrapper 参数只放在 `--` 前，原生参数只放在 `--` 后。`defaults` 只审查处理分类和注入 argv，不发现或启动引擎；只有引擎不可启动或身份不清楚时运行 doctor。scc 原生退出码保留，非零退出、解析失败或协议变化不得解释为空结果；协议无法结构化时只允许使用同一次捕获的有界回退，不重复执行扫描。

## 完整性与续页

普通完整结果不带续页回执；未展示完的 query model 结果先返回 `@more` 数量事实，再在 `@next` 后给出 PowerShell 7 可直接执行的完整命令；直接执行该命令，不自行重组 cursor、控制面或原生 argv。machine 返回 `query_snapshot` 与 `next_cursor`。续页必须重用同一 cwd、原生 argv、引擎、实际 view 和 snapshot；缺少 `@next`、未知、损坏或跨查询 cursor 时不得猜测。

语言和文件总数只由完整捕获计算，分页只限制模型可见页而不缩小底层扫描集合。全集、不存在、最大值或热点排序结论必须覆盖所声明的权威源码范围，并明确 ignore、generated、vendor、minified 等原生 scc 选项是否改变了集合。
