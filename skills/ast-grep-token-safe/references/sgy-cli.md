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
| Linux x86_64 GNU | `scripts/sgy.sh` | `scripts/bin/linux-x86_64/sgy` |

完整 hash 位于 `scripts/runtime-manifest.yml`；许可证、目标平台第三方许可与 SBOM 位于 `scripts/legal/`。sgy 不包含 ast-grep、Node、Python 或语言运行时。

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
sgy process <validate|select|filter|count|group|sort|dedupe|merge|to-jsonl|from-jsonl> ...
sgy <schema|capabilities|doctor> ...
```

常用 wrapper 参数：

```text
--engine PATH
--cwd PATH
--profile token-safe|lossless|files|custom
--cache auto|on|off
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
```

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
