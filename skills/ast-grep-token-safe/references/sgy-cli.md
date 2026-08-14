# sgy CLI 按需参考

仅在基本 `run`/`scan` 之外需要 profile、cache、后处理、特殊输出或协议模式时读取。

## 目录

- [内置运行时](#内置运行时)
- [命令与输出](#命令与输出)
- [Profile](#profile)
- [Cache 与后处理](#cache-与后处理)
- [通道和退出码](#通道和退出码)

## 内置运行时

| 平台 | 启动器 | 二进制 |
| --- | --- | --- |
| Windows x86_64 | 直接调用 `scripts/bin/windows-x86_64/sgy.exe` | 同左 |

完整 hash 位于 `scripts/runtime-manifest.yml`；源码版本、Windows 原生构建 manifest、归档校验和与 RustSec 结果位于 `scripts/provenance/`，并由 `release-record.json` 汇总。许可证、Windows 目标第三方许可与 SBOM 位于 `scripts/legal/`。sgy 不包含 ast-grep、Node、Python 或语言运行时。

Windows 不使用 PowerShell `.ps1` 中转 `exec/defaults`：PowerShell 会吞掉独立的 `--` 参数终止标记，破坏 sgy 的 native argv 边界。直接调用 exe 可保持分隔符。

首次使用或异常时：

```text
sgy --version
sgy doctor [--engine PATH] [--cwd PATH]
sgy capabilities
sgy defaults [wrapper options] -- <ast-grep argv...>
```

## 命令与输出

```text
sgy exec [wrapper options] -- <ast-grep argv...>
sgy cache <get|query|info|remove|gc> ...
sgy process <validate|select|filter|count|group|sort|dedupe|merge|to-jsonl|from-jsonl|containing|group-locations> ...
sgy <schema|capabilities|doctor> ...
```

常用 wrapper 参数：

```text
--engine PATH
--cwd PATH
--profile token-safe|locations|lossless|files|custom
--cache auto|on|off
--fingerprint-file PATH
--max-detail-results N
--max-text-chars N
--max-context-bytes N
--keep-fields PATHS
--prune-fields PATHS
--yaml-out PATH
--stderr-yaml PATH
--meta-out PATH
--artifact-out PATH
--no-native-defaults
--strict
```

兼容行为：

| ast-grep 模式 | sgy 行为 |
| --- | --- |
| batch `run`/`scan` | 缺省补 `--json=stream`，转换为所选 YAML profile |
| rewrite/fix 与 `-U` | 原生执行/写入集合和退出码保持；YAML 只控制展示 |
| `test`、`new`、help/version | UTF-8 文本包装为有界 `sgy.raw/v1` |
| completions/二进制输出 | 显式使用 `--artifact-out`，stdout 返回 manifest |
| interactive | 继承 TTY，不注入 JSON，不转换交互字节 |
| `lsp` | stdin/stdout 字节透传，YAML 不进入协议 stdout |
| 未知未来命令 | raw fallback，不猜测结构化 schema |

## Profile

| Profile | 使用条件 |
| --- | --- |
| `token-safe` | 默认；模型查看搜索/扫描结果 |
| `locations` | 只需完整文件与 0-based 起止范围，不需正文、捕获或规则诊断 |
| `files` | 先只看文件集合和计数，快速收窄范围 |
| `lossless` | JSON value 等价 round-trip、未知字段或完整审计 |
| `custom` | 已知必要字段，显式 keep/prune |

Token-Safe envelope 至少检查：

```yaml
_sgy:
  profile: token-safe
  total: 80
  shown: 40
  omitted: 40
  files: 12
  complete: false
  cache: 01H...
results: []
```

`complete: false` 只表示模型可见详情不完整，不表示扫描不完整。lossless YAML 通常不比 compact JSON 短；节省来自投影、汇总和预算。

`locations` 仍使用 `sgy.context/v1` 包络和相同的 cache/截断合同，但以 JSON 兼容的安全 YAML 1.2 紧凑输出，`results` 项为 `file:start_line:start_column-end_line:end_column`。位置保持 ast-grep 的 0-based、end-exclusive 语义；需要其他字段时不要用此 profile。

## Cache 与后处理

`auto` 在结果无需省略时不保留 cache，需要取回时提交完整原生 JSON/JSONL；`on` 始终保留；`off` 从不保留。cache 可能含完整源码和路径，应按敏感代码处理。

```text
sgy cache info <ID>
sgy cache query <ID> --file PATH --rule-id ID --offset 0 --limit 20
sgy cache get <ID> --result N [--field /json/pointer]
sgy cache remove <ID>
sgy cache gc
```

优先直接处理 verified cache：

```text
sgy process count --cache-id <ID>
sgy process group --cache-id <ID> --field file
sgy process containing --cache-id <ID> --file src/app.ts --line 42 --column 8 [--include-text]
sgy process group-locations --cache-id <ID> [--file src/app.ts] --offset 0 --limit 40
```

位置投影前，原扫描必须使用 `--cache on --fingerprint-file <file>`；多文件可重复该参数，最多 256 项。`containing` 在完整 cache 结果中返回覆盖目标 0-based 行列的最小范围；并列最小项不会被伪装成唯一。`--include-text` 才返回完整缓存正文。`group-locations` 按文件分组范围，适合同一次扫描服务同文件多个目标。两者会复核执行前、执行后和查询时的整文件身份；缺少 fingerprint 或 stale 时必须重扫。它们只证明 cache 节点集合内的语法边界，不证明真实符号身份。

处理文件时先生成 lossless YAML，再传 `--input`：

```text
sgy exec --profile lossless --cache off --yaml-out results.yml -- run ...
sgy process validate --input results.yml
sgy process select --input results.yml --fields 'file,range,text'
sgy process filter --input results.yml --field ruleId --equals '"no-console"'
sgy process sort --input results.yml --by file
sgy process dedupe --input results.yml --on-conflict keep-first
```

## 通道和退出码

- stdout 输出 YAML、artifact manifest，或 LSP/TTY 透传字节。
- stderr 保留原生 stderr 与 wrapper 诊断；需要结构化 sidecar 时使用 `--stderr-yaml`。
- 原生退出码保持；120–127 保留给 wrapper 参数、转换、缓存、I/O 和协议错误。
- Token-Safe no-match 仍输出 `total: 0`、`complete: true`，同时保留 ast-grep 的退出码 1；不要把它误判为 wrapper 故障。
- 显式 SARIF 的 Token-Safe range 会从 SARIF 1-based 统一为 0-based；lossless 保持原始值。
