# rg/fd 查询网关

## 命令边界

```text
sgy <rg|fd> <exec|defaults> [wrapper options] -- <native argv...>
sgy <rg|fd> doctor [--engine PATH] [--cwd PATH]
```

`exec/defaults` 的 wrapper 选项是 `--engine PATH`、`--cwd PATH`、`--view VIEW`、`--limit N`、`--max-text-chars N`、`--artifact-out PATH`、`--snapshot SHA256` 和 `--after CURSOR`。rg view 为 `auto|grouped|records|locations|files|summary|lossless|raw`；fd view 为 `auto|tree|flat|summary|lossless|raw`。`--max-items` 与 `--max-line-length` 是前述两项预算的迁移别名；没有 `--max-bytes` wrapper 选项。wrapper help 使用 `sgy <rg|fd> exec --help`，原生 help 使用 `sgy <rg|fd> exec -- --help`。

`--` 后的值、顺序、重复项和空参数原样交给对应原生引擎；sgy 不用 shell 重建命令。为取得机器表示而增加的参数插在原生参数终止符之前，不能把负号开头的 pattern 或 path 重新解释成选项。`defaults` 只返回用户 argv、注入项、最终 argv、模式和处理类别，不查找或启动引擎。`exec` 与 `doctor` 只支持 ripgrep 15.1.0 和 fd 10.4.2 的精确版本读回。

rg/fd 的结构化查询结果使用单行紧凑 JSON；JSON 同时是可由现有安全 YAML 读取器解析的 YAML 1.2 子集。AST 输出和特殊模式的原生透传、产物或有界文本合同不改变。

## 处理类别

- 普通 rg 搜索追加原生 `--json --color=never`，保留 path、match/context、行、绝对偏移、submatch 和正文；`grouped` 只压缩重复路径。
- rg 文件列表和 fd 普通路径追加 NUL 输出，完整解析后选择 flat/tree 或 files；fd tree 为每个显式根建立稳定别名，逐段可逆转义，保留类型、内部目录结果、重复计数和无法归根的 flat 项。
- count、JSON、vimgrep 使用各自机器或稳定结构；`lossless` 保留完整原生 JSON 事件，其他 view 只投影声明的证据。显式 view 不适用于当前模式时局部拒绝，不静默换 view。
- help/version/list-details/format/hyperlink/replace/passthru/pre/stats/quiet 等文本模式返回有界行；`--view raw` 或 `--artifact-out` 请求完整原生 stdout，stderr 在显式原生通道中保持，否则只转发有界诊断。
- rg NUL/null-data/generate 与 fd print0 要求 `--artifact-out`，避免二进制进入 YAML。
- fd exec/exec-batch 使用继承 stdin/stdout/stderr 的原生透传；包装器不创建副作用授权。

## 完整性与快照

结构化执行对 stdout 设置 256 MiB、stderr 设置 16 MiB 的硬捕获上限；超过上限会终止整个原生进程组并返回 wrapper 错误。成功捕获保存为最多 32 份本机快照。输出分别报告原生退出、结果总数、展示数、省略数、底层结果集合完整性、当前投影内容完整性和当前展示完整性；rg 无匹配继续返回原生 exit 1 和完整空集合，原生错误不能伪装成完整空结果。

首个不完整页返回 `query_snapshot` 与 `next_cursor`。续页必须再次提供相同原生 argv、cwd、backend 和引擎，并传入：

```powershell
sgy rg exec --view auto --snapshot <id> --after <cursor> -- -n -F needle .
```

`auto` 的首个实际 view 会写入 cursor，后续页固定复用，避免页形状变化导致表示切换。snapshot 身份绑定 backend、引擎路径与版本、cwd、原生 argv、退出、stdout、stderr 和 fd 类型快照；目录、文件、reparse point、大小与哈希均读回校验。未知、损坏、跨查询或跨 view 的续点局部拒绝。

## 失败与安全

原生 stderr 不混入结构化 stdout。原生退出码原样返回；wrapper 输入/转换、进程/资源和原子产物错误使用独立错误路径。显式产物在启动引擎前固定目标指纹，完成后原子提交，防止并发覆盖。非 UTF-8 路径或正文不会伪装为空结果，而会要求显式原生产物路径。
