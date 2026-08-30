# AST 查询与改写合同

仅在已经查看必要文本、但语法边界、候选歧义、控制流或结构关系仍不能可靠确定，或任务明确需要 rule/rewrite 时读取。“完整定义”是验收结果，不是 AST 触发词。AST 沿用 srcq 既有入口、profile、cache、fingerprint、process、TTY/LSP、artifact、诊断和退出合同，不使用 rg/fd 的 snapshot 代替 AST cache。

## 查询

```text
srcq exec [wrapper options] -- <ast-grep argv...>
srcq defaults [wrapper options] -- <ast-grep argv...>
srcq cache <get|query|info|remove|gc> ...
srcq process <validate|select|filter|count|group|containing|group-locations|sort|dedupe|merge|to-jsonl|from-jsonl> ...
srcq <schema|capabilities|doctor> ...
```

`srcq exec` 的 wrapper 选项必须放在第一个 `--` 前，原生 ast-grep 参数放在其后；不要把 rg/fd 的 `--view`、`--limit` 或 snapshot 选项用于 AST。常用 wrapper 选项为：

```text
--engine PATH
--cwd PATH
--output model|machine
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

wrapper help 使用 `srcq exec --help`；原生 help 使用 `srcq exec -- run --help`。只在既有命令报告引擎、版本或协议异常时运行 `srcq doctor`、`srcq schema` 或 `srcq capabilities`，不要把探测命令作为查询前置步骤。

- 已知名称且文本定位后能用有界读取可靠取得完整实现时，不使用 AST。只有边界、关系或语法身份不能由文本可靠确定时，才先限定语言、目录、glob 和准确 pattern/rule。默认 token-safe model 每项只写文件、完整 0-based end-exclusive 范围与一次源码正文；只需范围时用 locations。`@more` 或 `@cut` 表示当前可见证据不完整，不得外推全集。
- C/C++ 单文件只需函数轮廓时，不启动冷 LSP `document_symbols`；在文件范围内使用 `run --kind function_declarator -l cpp <file>`，按源码顺序取得签名与位置，必要时再对少量目标有界读取。需要命名空间、类型嵌套或 Provider 符号分类且语法位置不足时，才升级到 LSP 文档符号。
- cpptools C/C++ 不提供 Type Hierarchy；已知类型的继承关系先用文本定位名称，再在相关文件内查询 `run --kind base_class_clause -l cpp <files...>`，按直接基类逐层扩展所需关系。只在活动语言扩展真实实现 Type Hierarchy 且 AST 不能裁决语义身份时调用 LSP `get_type_hierarchy`。
- parser、完整捕获、未知字段、稳定 schema 或 round-trip 使用 `--output machine`；`--yaml-out`、lossless 与 custom 本身也选择 machine。普通 model 不读取 `_sgy`，machine 才按 `_sgy.total/files/shown/omitted/complete/cache` 裁决。
- 已有位置但语法边界仍不稳时，才用 `--cache on` 和目标文件 fingerprint 建立完整 cache，再执行 `process containing`；`containing` 与 `group-locations` 默认返回无 envelope 的定位正文，程序消费时加 `--output machine`。`cache query` 同样默认 model，完整原生 result 用 `cache get`。同文件多目标复用一份 cache，源码身份变化时重扫。
- pattern 是目标语言语法；元变量、关系、constraints、context/selector 和 rule 只在结构要求需要时增加。调试先收窄到单文件或 stdin，再检查语言、解析、元变量和 strictness。无匹配不是继续猜 pattern 的依据；先读取实际候选源码，只有新观察能说明语言、节点形状、限定名、修饰符或 strictness 为什么应改变时才再查询，否则采用文本证据或明确当前结构结论未证。
- LSP 与交互模式透传协议或 TTY，不进入 YAML；未知未来命令使用原生有界 fallback，不猜测 schema。

## Rewrite

不带 apply 选项预览，确认 workspace、glob、总数、文件集、replacement 和 diff 后，才对同一命令单次 apply。预览不完整、文件集未知、源码已变或授权不足时不应用。应用后检查相关 diff、残留匹配，并执行 formatter、lint/typecheck、构建或定向测试中适用的最小充分集合。
