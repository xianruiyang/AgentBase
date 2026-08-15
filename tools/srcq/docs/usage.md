# srcq CLI 使用

## 命令结构

```text
srcq exec [wrapper options] -- <ast-grep argv...>
srcq defaults [wrapper options] -- <ast-grep argv...>
srcq cache <get|query|info|remove|gc> ...
srcq process <validate|select|filter|count|group|sort|dedupe|merge|to-jsonl|from-jsonl|containing|group-locations> ...
srcq <schema|capabilities|doctor> ...
```

`--` 是强制边界。左侧由 srcq 解析，右侧 token 作为参数数组交给 ast-grep，不经二次 shell 解析。显式原生参数保持值和顺序；不要把 wrapper 参数放到右侧。

## 搜索、扫描与改写

简单 pattern：

```powershell
srcq exec -- run -p 'console.log($A)' -l ts src
```

复杂 rule：

```powershell
srcq exec -- scan --rule rules/no-console.yml src
```

使用项目 `sgconfig.yml`：

```powershell
srcq exec -- scan src
srcq exec -- test
```

rewrite 预览和应用：

```powershell
srcq exec -- run -p 'legacy($A)' -r 'modern($A)' -l ts src
srcq exec -- run -p 'legacy($A)' -r 'modern($A)' -l ts -U src
```

srcq 不会自动添加 `-U`，也不会把 40 条模型可见详情变成 40 条写入上限。应用前先检查 `_sgy.total`、文件汇总、replacement 和 diff。

成功的原生文本写入会在 `_sgy.write.applied_changes` 中记录可从 stderr 可靠提取的应用数量；ast-grep 不报告精确文件列表，因此 `affected_files: null`、`affected_files_complete: false`，文件集合以应用前 preview 为准。

## 输出选择

默认 `--output model` 输出干净证据正文。机器解析、完整捕获和 round-trip 使用 `--output machine`；需要稳定机器文件时使用原子提交的 `--yaml-out`：

```powershell
srcq exec --yaml-out results.yml -- run -p 'foo($A)' -l ts src
```

常用 wrapper 选项：

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
--no-native-defaults
--strict
```

`token-safe` 的 model 每项只写文件、完整范围、源码和实际存在的 rule/severity/message/replacement；不重复 metaVariables 捕获或固定 envelope。分页、截断和写入事实才追加最短 `@` 记录。

machine 输出的 `_sgy` 至少用于判断：

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

- `total` 是完整引擎结果数，`shown` 是当前 YAML 的详细结果数。
- `complete: false` 表示详情或文本被省略/截断；不要把可见列表当作全部结果。
- 出现 `cache` 时按 [缓存文档](cache.md) 精确取回，不要重新无界扫描。
- `lossless` 不生成 Token-Safe envelope；其目标是值等价，不是低 Token。

只需完整命中集合的文件和起止位置时使用 `locations`：

```powershell
srcq exec --profile locations --cache off -- run -p 'function $F($$$A) { $$$B }' -l ts src
```

model 每项为 0-based `file:start_line:start_column-end_line:end_column`；machine 保留相同完整性包络和 JSON 兼容的紧凑安全 YAML。若仍需正文、捕获或规则诊断，使用 token-safe model；完整捕获或自定义字段使用 machine/custom。

## 先预览 effective argv

`defaults` 不查找或启动 ast-grep：

```powershell
srcq defaults --profile files -- run -p 'foo($A)' -l ts src
```

model 只返回分类与实际注入或 `unchanged`；需要 `effective_argv`、`suppressed_by` 和设置来源时加 `--output machine`。确认后再改为 `srcq exec`。

## 后处理

输入来源三选一：`--input PATH`、`--cache-id ID`、stdin。`validate` 可检查任意安全 YAML 并报告 schema 是否被识别；其它操作只接受 generic/lossless 记录、已知 srcq schema 或 verified cache。当前 `sgy.context/v1` envelope 应通过 `_sgy.cache` 处理，不能直接作为 count/select/filter 输入。`from-jsonl` 读取有界 JSONL。

先按需生成 lossless 记录文件：

```powershell
srcq exec --profile lossless --cache off --yaml-out lossless.yml -- run -p 'foo($A)' -l ts src
```

```powershell
srcq process validate --input lossless.yml
srcq process count --input lossless.yml
srcq process group --input lossless.yml --field file
srcq process select --input lossless.yml --fields 'file,range,text'
srcq process filter --input findings-lossless.yml --field ruleId --equals '"no-console"'
srcq process sort --input lossless.yml --by file
srcq process dedupe --input lossless.yml --on-conflict keep-first
srcq process to-jsonl --input lossless.yml
srcq process from-jsonl --input results.jsonl
```

合并必须显式列出来源，输出携带 provenance：

```powershell
srcq process merge --source 'file=lossless.yml' --source 'cache=01H...' --on-conflict error
```

`filter` 只做字段与 JSON value 相等比较，`select` 只做字段投影；二者都不执行表达式或代码。`sort`/`dedupe`/`merge` 对大输入使用稳定外部排序。

已知源码位置需要完整语法边界时，先用 `--cache on --fingerprint-file <file>` 在执行前固定需要复用的源码，再按 0-based 行列投影最小包含范围；只有确需正文时才加 `--include-text`：

```powershell
srcq process containing --cache-id <ID> --file src/app.ts --line 42 --column 8
srcq process containing --cache-id <ID> --file src/app.ts --line 42 --column 8 --include-text
srcq process group-locations --cache-id <ID> --file src/app.ts --limit 40
```

`containing` 只在 cache 的节点集合内做几何包含；并列最小项全部保留，不声明真实符号身份。位置投影只接受执行前已登记 fingerprint、且执行结束与查询时整文件哈希均一致的源码；旧 cache、未登记文件或任意位置变化都会要求重扫。`group-locations` 让路径只出现一次，适合同文件多目标复用；model 续页使用 `@more cache/after`，machine 的 `complete/next_offset` 只描述投影视图。

## 诊断与退出码

```powershell
srcq --version
srcq capabilities
srcq schema
srcq doctor
```

- 原生命令退出码被保留；无匹配和执行错误应按 ast-grep 语义区分。
- 缺省 model 遇到退出码 1 且 stdout/stderr 均为空时保持空 stdout；machine Token-Safe 返回显式空集合，lossless 保持原生空字节。
- `doctor` 成功时 model 只输出 `ok`；失败时输出失败项与 machine 重试入口并退出 1。`--output machine` 返回完整 `sgy.doctor/v1`。
- 120–127 保留给 wrapper 自身的解析、转换、缓存、I/O 或协议错误。
- stderr 与 YAML stdout 分离；需要结构化 sidecar 时使用 `--stderr-yaml PATH`。`--meta-out PATH` 适用于 batch、TTY 和 LSP，并记录 argv hash、引擎版本、耗时与退出状态，不记录源码正文。

显式 `scan --format sarif` 默认仍可使用 Token-Safe：wrapper 从 `runs[].results[]` 提取 finding，并将 SARIF 1-based region 规范化为统一的 0-based range。需要完整 SARIF、未知字段或机器 round-trip 时改用 `--profile lossless`。
