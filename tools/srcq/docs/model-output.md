# 模型可见输出合同

本文件定义 `srcq` 如何从同一完整事实源生成模型、机器和原生输出。目标顺序是证据充分、模型上下文最小、随后才是速度；格式统一本身不是目标。

## 输出面

| 输出面 | 使用方 | 默认合同 |
| --- | --- | --- |
| model | Codex 或其他直接阅读结果的模型 | 只输出当前命令请求的证据正文；正常成功和完整不带 envelope、schema 或回执 |
| machine | parser、round-trip、完整诊断和兼容消费者 | 稳定 JSON/YAML、全部必要身份与完整性字段 |
| native/artifact | TTY、LSP、二进制、原生字节和文件产物 | 保持原生字节、退出与副作用；普通模型上下文不展开产物正文 |

普通 `srcq rg|fd|scc <native argv...>` 和 AST `exec/defaults` 默认使用 model；rg/fd/scc 的显式控制位于 `srcq query` 命名空间，避免与原生参数冲突。`--output machine` 显式选择机器视图，`--receipt full` 继续隐含 machine。AST 的 `--yaml-out`、`--profile lossless|custom`、schema/capabilities、cache 的原始结果读取以及一般 process 转换是显式机器请求；`cache query`、`process containing` 和 `process group-locations` 默认提供模型证据，并可用 `--output machine` 取得稳定结构。

## 模型字段准入

字段只有在缺少它会改变当前模型的判断、定位、继续查询或失败恢复时才进入 model stdout。下列理由不足以准入：内部已经计算、机器 schema 要求、自描述更完整、以后可能有用、调试时方便或与其他 backend 表面对称。

| 输出族 | model 保留 | 正常 model 省略 | 例外 |
| --- | --- | --- | --- |
| fd 路径 | 可还原路径 | schema、根别名容器、逐项类型、空集合、escape 说明、统计 | 多根/混合类型/根外结果只增加消除歧义的最小标记 |
| rg 正文 | 路径一次、行号、正文、真实 context 区分 | event kind 字段、absolute offset、submatches、native 副本、重复 summary | 请求位置范围时保留必要 submatch 列范围；正文截断才给 cut 信息 |
| rg files/count/summary | 请求对象本身 | 与请求对象重复的 receipt | 分页才给续点；统计只在明确 summary/count 视图出现 |
| scc summary/languages | 语言、文件、代码、注释、空行、行数、复杂度和字节的当前请求投影 | 原生键名、重复 totals、COCOMO、estimated cost、schedule、people | lossless/raw/artifact 才保留完整原生估算字段；复杂度只作复核候选指标 |
| scc files/hotspots | 稳定规范化路径与直接指标；files 可用扁平行、单表头表格或目录树表格 | 未请求的语言容器、成本估算、重复路径 | files 仅在可逆、保序且实际更短时用树；分页给精确 cursor；hotspots 保持扁平排名且不声明缺陷 |
| AST | 文件、完整范围、源码正文；当前查询确需且不与正文重复的捕获/规则/诊断 | `_sgy` envelope、ordinal、正文的重叠捕获、固定 profile/cache 字段 | 省略结果、正文截断或 cache 是继续取回的唯一入口时给最短恢复信息 |
| doctor | 成功时 `ok` | 正常路径、cwd、expected/observed 重复、schema | 失败时给实际值、预期值和恢复入口 |
| defaults | 分类结果及实际注入、抑制或不可推导差异 | engine、cwd、原始 argv、完整 effective argv、engine_started | `--output machine` 返回完整决策 |
| artifact | 已写入的目标路径 | schema、backend、mode、重复目标、固定统计 | machine 视图或校验请求才给 bytes/hash/native exit |
| cache/process | 用户显式请求的值或变换结果 | 额外 wrapper envelope | query 分页保留必要 offset/续读事实；info/schema/转换命令按显式机器请求完整返回 |
| error | 直接原因和可执行恢复 | 成功字段、内部堆栈、重复命令 | 退出状态由进程通道持有；会发生部分写入时必须警告 |

## 紧凑文本语法

正常 model 输出不加开头或结尾标记。路径使用 `/`，只转义会破坏换行、缩进或路径分段的字符。

- fd 单根查询已由 argv 给出根时只写相对路径；无分叉链写成 `A/A0`，共享分支写成 `A/` 后以两空格缩进子链。只有该表示可逆且实际更短时使用树。
- rg 可以按结果形状选择逐行 `path:line:text`、文件 heading，或把共享目录压成路径树并在文件叶子下写 `line:text`/位置；match 使用 `line:text`，context 使用 `line-context`。locations 只在真实列范围存在时写范围。
- scc summary 使用一行 totals；languages 在多语言首个页面保留全局 totals，再列逐语言直接指标；files 的扁平标注以完整稳定 `/` 路径开头，表格只定义一次固定列，目录树以 `path(tree)` 表头、末尾 `/` 的目录和两空格层级表达同一完整路径；hotspots 每行仍以完整稳定路径开头。字段顺序固定，零值不被误删；模型格式不承诺原生 JSON round-trip。
- AST 每项先写 `file:startLine:startColumn-endLine:endColumn`，下一行起写源码正文；捕获只在不与正文重叠或调用方明确需要时追加。

正常 model 输出依靠固定协议和进程退出表达成功、完整与无匹配，不逐次复述。只有偏离默认时追加一行 `@` 记录：

```text
@more shown=<N> omitted=<N> after=<CURSOR>
@more shown=<N> omitted=<N> cache=<ID> [after=<OFFSET>]
@cut text|results|lines=<N>
@unprojectable <N>
```

`@more` 只表示存在明确的同快照续读入口；query cursor 自带 snapshot 身份，model 续页只需原查询加 `--after <CURSOR>`，也兼容同时显式传 `--snapshot`。不能续读的结果或行省略使用 `@cut`。`@unprojectable` 表示 cache 中存在无法形成位置投影的记录。同一结果同时发生分页和正文截断时可分别出现两行。真正未知不得省略成默认；无法可靠表达时返回错误并建议 machine/artifact，而不是输出看似完整的正文。

## 选择与验证

`auto` 只比较 EvidenceSignature 相同的 model 候选，并用实际渲染文本估算成本，不序列化内部 JSON/YAML 代理成本。普通直接入口已经持有完整事实时，会先判断完整结果能否在同一总预算和硬单元上限内形成一次闭环；可完整容纳才越过初始项数限制，单文件可在总预算不增加时提高单行完整度，多文件或过大结果不放宽。其余结果按页选择能够完整容纳的最大证据单元前缀；先最大化同页充分证据，再在同一前缀上选择成本最低的等价表示。显式控制面的 limit、正文和预算保持调用方指定语义。任何 model 格式变更都验证结果集合、顺序、路径、范围、正文、context、scc 直接指标、截断、分页快照、错误和恢复；machine round-trip、scc lossless、AST cache/process/rewrite、TTY/LSP 和原生字节必须分别非回退。字符差只证明格式机制；Token 收益需以真实 tokenizer 或项目已验证的保守估算测量，最终模型行为收益仍由项目内受监控隔离 Codex 对照按质量、总 Token、耗时顺序裁决。
