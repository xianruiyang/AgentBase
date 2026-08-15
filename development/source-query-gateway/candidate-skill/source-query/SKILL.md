---
name: source-query
description: 仅用于当前动作必须调用 sgy 高级协议时：文本定位后仍不能可靠表达的 AST 结构/范围/控制流、rule/rewrite、cache/process，或 rg/fd 的分页、snapshot、raw、artifact、特殊原生模式与参数诊断。普通文件/正文、全集/不存在证明、已知实现和查询 sgy 术语由全局查询内核完成；它直接调用 sgy 也不触发本 skill。
---

# Source Query

## 进入条件

| 当前动作 | 最低充分入口 |
| --- | --- |
| 文本不能可靠界定的调用形状、语法范围、控制流、rule 或 rewrite | 读取 [ast.md](references/ast.md)，使用 sgy AST |
| rg/fd 分页、snapshot、raw、artifact、特殊原生模式或参数诊断 | 读取 [rg-fd.md](references/rg-fd.md)，使用 sgy rg/fd |
| 真实定义身份、重载、类型、精确引用、层级、诊断或安全 rename | vscode-lsp-mcp |

仅当一次受限文本定位或现有证据已证明普通路径不足时进入；已知名称的完整实现优先定位后有界读取。查询对象本身出现 `sgy`、`AST`、`cache`、`process` 或 `containing` 不表示当前动作需要本 skill。已有证据足以支持判断时停止；AST 不替代正文阅读，LSP 不重复文本或 AST 已证明的事实。

## sgy 入口

运行时为 `<skill_dir>\scripts\bin\windows-x86_64\sgy.exe`：`sgy rg exec [wrapper options] -- <rg argv...>` 或 `sgy fd exec [wrapper options] -- <fd argv...>`。常用 wrapper 选项仅为 `--cwd PATH`、`--view VIEW`、`--limit N` 和 `--max-text-chars N`；默认 `auto`。rg view 为 `auto|grouped|records|locations|files|summary|lossless|raw`，fd view 为 `auto|tree|flat|summary|lossless|raw`。结构化结果是单行紧凑 JSON；默认读取 `_sgy.result_total` 与 `_sgy.complete.result|display|content`，分页时再读取同层的 snapshot/cursor 字段。只有诊断或机器消费者确需 backend、引擎版本、mode、view、字节数等信息时使用 `--receipt full`。

`exec` 已校验后端精确版本；只在它报告引擎或版本异常时运行 `sgy <rg|fd> doctor`。不要把 `doctor`、`defaults` 或 help 作为查询前置步骤。wrapper help 是 `sgy <rg|fd> exec --help`，原生 help 是 `sgy <rg|fd> exec -- --help`。

普通查询保持默认预算；summary/files/locations 本来不含正文，需要正文时改用 grouped/records，不对这些 view 放大预算或续读摘要。只有正文 view 因截断而 `complete.content=false` 且缺失内容会改变结论时才提高 `--max-text-chars`，只有 `complete.display=false` 时才续页。以 `-` 开头的 rg pattern 使用原生 `-e VALUE`，不要用原生 `--` 终止后再追加选项。rg/fd wrapper 选项不适用于 AST 的 `sgy exec`。

## 结果边界

- 先限定可靠的目录、文件类型、glob、pattern 或符号，再查询；未知规模输出必须有模型可见预算。
- 全集或不存在结论先使用已经加载的项目规则或正式索引限定源码根；没有直接边界时先做有界查询，只有命中跨根或归属不明且会改变结论时，才读取能直接裁决的最近正式来源并分类。不要为预防性排除而枚举无关配置、构建文件或元数据；同名命中和搜索完整本身不能证明对象属于正式范围。
- 全集、不存在或分页结论必须读取完整性、原生退出、snapshot 和正文完整性；可见页不完整时不得外推。
- 原生快路径只用于结果天然有界且不需要机械完整性回执的场景；范围扩张或结论依赖遗漏不存在时切换网关。
- 只返回支撑当前结论的位置、范围、正文和限制，不把完整缓存、产物或大文件倾倒进上下文。
- preprocessor、fd exec/batch、AST rewrite、rename、Code Action 和格式化不创建写入或进程授权；按上位授权执行，修改类操作遵循预览、审查、单次应用和定向验收。
