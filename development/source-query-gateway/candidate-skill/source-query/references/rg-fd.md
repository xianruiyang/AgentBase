# rg/fd 查询合同

仅在文本或文件查询需要完整性、大结果压缩、可逆树或分页时读取。运行时为 `<skill_dir>\scripts\bin\windows-x86_64\sgy.exe`，只支持 Windows x86_64；`--` 后是原生 ripgrep 15.1.0 或 fd 10.4.2 argv，值、顺序、重复项和空参数不经 shell 重建。

## 入口与选择

```text
sgy rg <exec|defaults> [wrapper options] -- <rg argv...>
sgy fd <exec|defaults> [wrapper options] -- <fd argv...>
sgy <rg|fd> doctor [--engine PATH] [--cwd PATH]
```

- rg 普通搜索优先 `auto`；只需位置、文件或汇总时显式选择对应 view，仍需正文或捕获时不得降级投影。
- fd 普通发现优先 `auto`；tree 只有比 flat 更短时自动选中，并通过根别名、可逆转义、类型和重复计数保留全部路径。
- `defaults` 只审查模式、处理类别和注入 argv，不发现或启动引擎；首次使用、版本异常或转换异常时运行 `doctor`。
- `raw` 或 `--artifact-out` 是完整原生字节逃生口。NUL、null-data、generate 等二进制模式必须写 artifact；不把 artifact 正文读入模型上下文。
- fd exec/exec-batch 继承原生 stdin/stdout/stderr；rg preprocessor 和 search-zip 可启动外部程序。只有任务授权覆盖相应外部影响时执行。

## 完整性与续页

结构化回执分别报告 native exit、结果总量、展示量、省略量、结果集合完整性、当前投影内容完整性和展示完整性。rg exit 1 是完整无匹配；更高退出或 wrapper 转换失败不得解释为空集合。fd 无匹配仍可能 exit 0，结论必须同时绑定 pattern、path、ignore 和完整性。

首个未展示完的结果返回 `query_snapshot` 与 `next_cursor`。续页必须重用同一 backend、cwd、原生 argv、引擎、snapshot、cursor 和实际 view；未知、损坏或跨查询续点不得猜测。snapshot 已冻结原生结果和 fd 类型，续页不重新混入当前文件系统状态。

wrapper 参数只放在 `--` 前；原生参数只放在 `--` 后。限制模型可见页不缩小底层查询集合；若确实要限制查询本身，只能显式使用原生选项并把该限制计入结论。
