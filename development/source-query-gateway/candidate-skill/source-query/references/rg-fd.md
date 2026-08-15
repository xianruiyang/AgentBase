# rg/fd 查询合同

仅在文本或文件查询需要完整性、分页、特殊原生模式或显式控制时读取。运行时为用户 PATH 中的 `srcq.exe`，只支持 Windows x86_64；普通入口把 backend 后全部 token 作为原生 rg 或 fd argv，不经 shell 重建，后端版本只界定已验证证据而不参与运行准入。

## 入口与选择

```text
srcq rg <rg argv...>
srcq fd <fd argv...>
srcq query <rg|fd> <exec|defaults> [wrapper options] -- <native argv...>
srcq query <rg|fd> doctor [--engine PATH] [--cwd PATH]
```

普通入口隐式使用 model/auto 和内部上下文预算，所有参数都属于原生工具；原生 help 直接使用 `srcq <rg|fd> --help`。只有确实需要定向投影、machine、native/artifact、诊断或续页时进入 `srcq query`；其 wrapper 选项包括 `--engine`、`--cwd`、`--output`、`--view`、`--limit`、`--max-text-chars`、`--model-token-budget`、`--receipt`、`--artifact-out`、`--snapshot` 和 `--after`，原生参数仍放在 `--` 后。

srcq 取得真实结果后比较逐行 locator、文件 heading、共享目录树及其位置/正文叶子；fd 同样只在可逆、顺序保持且实际更短时选择紧凑树。内部预算按完整证据单元分页，正常完整结果不带 schema、`_sgy` 或完成回执；分页追加最短 `@more ... after=<cursor>`，正文截断追加 `@cut`。空 stdout 配合原生退出表达完整无匹配。parser、完整诊断或 round-trip 才使用显式 machine；`--receipt full` 和 `lossless` 保留既有 JSON/YAML 协议。

- 普通搜索不写 `auto`；只需文件、count、vimgrep 等对象时优先用原生命令语义表达。显式 view 只在调用方确实需要固定证据投影时使用；summary 对完整集合聚合且不续页。
- fd 普通发现不写 tree/flat；混合类型、重复项、顺序不能保持或路径不能消歧时自动退回最短可逆 flat。machine 仍保留根别名、类型和重复计数。
- `defaults` 只审查模式、处理类别和注入 argv，不发现或启动引擎；普通查询不预检。只有引擎不可启动或身份不清楚时才运行 `srcq query <backend> doctor`，模式合同不清楚时才运行显式 defaults 或控制面 help；版本字符串不同本身不是故障。
- `raw` 或 `--artifact-out` 是完整原生字节逃生口。NUL、null-data、generate 等二进制模式必须通过显式控制面写 artifact；不把 artifact 正文读入模型上下文。
- fd exec/exec-batch 继承原生 stdin/stdout/stderr；rg preprocessor 和 search-zip 可启动外部程序。只有任务授权覆盖相应外部影响时执行。

## 完整性与续页

默认 model 依靠进程退出与固定协议表达正常完整结果，只在偏离默认时追加 `@more` 或 `@cut`。rg exit 1 是完整无匹配；更高退出或 wrapper 转换失败不得解释为空集合。fd 无匹配仍可能 exit 0，结论必须同时绑定 pattern、path 和 ignore 范围。需要逐字段证明完整性或由程序解析时改用 machine，不从 model 文本反推内部字段。

首个未展示完的 model 结果在 `@more` 返回自带 snapshot 身份的精确 after；使用 `srcq query <backend> exec --after <cursor> -- <原查询 argv...>` 续页。machine 使用 `query_snapshot` 与 `next_cursor`。续页必须重用同一 backend、cwd、原生 argv、引擎、cursor 和实际 view；未知、损坏或跨查询续点不得猜测。snapshot 已冻结原生结果和 fd 类型，续页不重新混入当前文件系统状态。完整默认结果不返回 snapshot，也不会留下不可续读的持久副本。

显式控制面中 wrapper 参数只放在 `--` 前，原生参数只放在 `--` 后；普通入口没有 wrapper 参数。限制模型可见页不缩小底层查询集合；若确实要限制查询本身，只能使用原生选项并把该限制计入结论。保持默认预算，只有证据确因分页或正文截断不足时才定向续页或覆盖，不为预防性放大输出。以 `-` 开头的 rg pattern 使用原生 `-e VALUE`，避免原生 `--` 把后续选项改释为路径。
