# rg/fd 查询合同

仅在文本或文件查询需要完整性、大结果压缩、可逆树或分页时读取。运行时为 `<skill_dir>\scripts\bin\windows-x86_64\sgy.exe`，只支持 Windows x86_64；`--` 后是原生 ripgrep 15.1.0 或 fd 10.4.2 argv，值、顺序、重复项和空参数不经 shell 重建。

## 入口与选择

```text
sgy rg <exec|defaults> [wrapper options] -- <rg argv...>
sgy fd <exec|defaults> [wrapper options] -- <fd argv...>
sgy <rg|fd> doctor [--engine PATH] [--cwd PATH]
```

`exec/defaults` 的 wrapper 选项是 `--engine PATH`、`--cwd PATH`、`--view VIEW`、`--limit N`、`--max-text-chars N`、`--receipt auto|full`、`--artifact-out PATH`、`--snapshot SHA256` 和 `--after CURSOR`。rg view 为 `auto|grouped|records|locations|files|summary|lossless|raw`；fd view 为 `auto|tree|flat|summary|lossless|raw`。wrapper help 使用 `sgy <rg|fd> exec --help`，原生 help 使用 `sgy <rg|fd> exec -- --help`。

rg/fd 的结构化结果是单行紧凑 JSON。默认 `_sgy` v2 固定返回 `result_total` 和 `complete.result|display|content`，只有非零退出或分页时才增加相应字段；`--receipt full` 用于确需 backend、引擎版本、mode、view、offset 和字节数的诊断或机器消费者。AST 仍使用既有安全 YAML，特殊模式仍可按合同透传、落产物或返回有界文本。

- rg 普通搜索优先 `auto`；只需位置、文件或汇总时显式选择对应 view，仍需正文或捕获时不得降级投影。
- fd 普通发现优先 `auto`；tree 只有比 flat 更短时自动选中，并通过根别名、可逆转义、类型和重复计数保留全部路径。
- `defaults` 只审查模式、处理类别和注入 argv，不发现或启动引擎；普通查询不预检。只有 `exec` 报告引擎或版本异常时运行 `doctor`，模式或转换异常且命令合同仍不清楚时才运行 `defaults` 或 wrapper help。
- `raw` 或 `--artifact-out` 是完整原生字节逃生口。NUL、null-data、generate 等二进制模式必须写 artifact；不把 artifact 正文读入模型上下文。
- fd exec/exec-batch 继承原生 stdin/stdout/stderr；rg preprocessor 和 search-zip 可启动外部程序。只有任务授权覆盖相应外部影响时执行。

## 完整性与续页

默认结构化回执显式报告结果总量与结果集合、当前投影内容、当前展示三类完整性；native exit 只在非零时出现，展示量、省略量和续页身份只在当前页未展示完时出现。rg exit 1 是完整无匹配；更高退出或 wrapper 转换失败不得解释为空集合。fd 无匹配仍可能 exit 0，结论必须同时绑定 pattern、path、ignore 和完整性。

首个未展示完的结果返回 `query_snapshot` 与 `next_cursor`。续页必须重用同一 backend、cwd、原生 argv、引擎、snapshot、cursor 和实际 view；未知、损坏或跨查询续点不得猜测。snapshot 已冻结原生结果和 fd 类型，续页不重新混入当前文件系统状态。

wrapper 参数只放在 `--` 前；原生参数只放在 `--` 后。`--max-items` 与 `--max-line-length` 分别是 `--limit` 与 `--max-text-chars` 的迁移别名；没有 `--max-bytes` wrapper 选项。限制模型可见页不缩小底层查询集合；若确实要限制查询本身，只能显式使用原生选项并把该限制计入结论。

保持默认模型可见预算，先读回完整性再决定是否提高；不要为预防性保留正文把 `--max-text-chars` 放大。以 `-` 开头的 rg pattern 使用原生 `-e VALUE`，避免原生 `--` 把后续选项改释为路径。
