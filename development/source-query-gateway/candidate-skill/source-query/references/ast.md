# AST 查询与改写合同

仅在文本不能可靠表达语法结构、范围、控制流、rule 或 rewrite 时读取。AST 沿用 sgy 既有入口、profile、cache、fingerprint、process、TTY/LSP、artifact、诊断和退出合同，不使用 rg/fd 的 snapshot 代替 AST cache。

## 查询

```text
sgy exec [wrapper options] -- <ast-grep argv...>
sgy defaults [wrapper options] -- <ast-grep argv...>
sgy cache <get|query|info|remove|gc> ...
sgy process <validate|select|filter|count|group|containing|group-locations|sort|dedupe|merge|to-jsonl|from-jsonl> ...
sgy <schema|capabilities|doctor> ...
```

`sgy exec` 的 wrapper 选项必须放在第一个 `--` 前，原生 ast-grep 参数放在其后；不要把 rg/fd 的 `--view`、`--limit` 或 snapshot 选项用于 AST。常用 wrapper 选项为：

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

wrapper help 使用 `sgy exec --help`；原生 help 使用 `sgy exec -- run --help`。只在既有命令报告引擎、版本或协议异常时运行 `sgy doctor`、`sgy schema` 或 `sgy capabilities`，不要把探测命令作为查询前置步骤。

- 已知名称且文本定位后能用有界读取可靠取得完整实现时，不使用 AST。只有边界、关系或语法身份不能由文本可靠确定时，才先限定语言、目录、glob 和准确 pattern/rule。默认使用 token-safe；只需文件与完整 0-based、end-exclusive 范围时用 locations；需要正文、捕获或诊断时保留默认；只有机器 round-trip、未知字段或完整审计使用 lossless。
- 读取 `_sgy.total/files/shown/omitted/complete/cache`；可见详情不完整时不得从其外推全集。
- 已有位置但语法边界仍不稳时，才用 `--cache on` 和目标文件 fingerprint 建立完整 cache，再执行 `process containing`；同文件多目标复用一份 cache。源码身份变化时重扫。
- pattern 是目标语言语法；元变量、关系、constraints、context/selector 和 rule 只在结构要求需要时增加。调试先收窄到单文件或 stdin，再检查语言、解析、元变量和 strictness。
- LSP 与交互模式透传协议或 TTY，不进入 YAML；未知未来命令使用原生有界 fallback，不猜测 schema。

## Rewrite

不带 apply 选项预览，确认 workspace、glob、总数、文件集、replacement 和 diff 后，才对同一命令单次 apply。预览不完整、文件集未知、源码已变或授权不足时不应用。应用后检查相关 diff、残留匹配，并执行 formatter、lint/typecheck、构建或定向测试中适用的最小充分集合。
