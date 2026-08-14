---
name: ast-grep-token-safe
description: 使用 skill 内置的 Windows x86_64 sgy 驱动原生 ast-grep，以有界 Token-Safe YAML 完成结构化代码搜索、规则扫描、pattern 调试、结果缓存/后处理和安全批量改写。用于按语法结构定位调用、声明/定义范围或控制流，编写/调试 pattern 或 YAML rule，预览与应用 rewrite，或文本搜索无法可靠表达结构关系时；不用于单纯字符串、注释、日志文案、文件名搜索，也不替代 LSP 对真实定义身份、精确引用、类型和安全重命名的裁决。
---

# ast-grep 低 Token 工作流

## 选择工具

- 语法结构搜索、声明/定义的完整语法范围和局部语法改写使用 ast-grep。
- 字符串、注释、日志、文件名使用 `rg`/`fd`。
- 已知名称先用受限 `rg` 缩小候选；唯一候选配合定向读取已足够时不升级 AST。
- 从用法解析真实定义/实现身份、精确引用、类型、继承和安全 rename 使用 LSP/编译器。
- 先限定语言、目录和 glob；不要从仓库根目录无界扫描。
- 编写 pattern、YAML rule 或 rewrite 时按需读取 [references/rules.md](references/rules.md)。使用 cache、后处理、LSP/TTY 或特殊输出时读取 [references/sgy-cli.md](references/sgy-cli.md)。

## 使用内置 sgy

不要依赖全局 `sgy`。将当前 `SKILL.md` 所在目录记为 `<skill_dir>`。Windows 直接调用内置 exe，避免 PowerShell 脚本吞掉独立的 `--`：

```powershell
$Sgy = '<skill_dir>\scripts\bin\windows-x86_64\sgy.exe'
& $Sgy --version
& $Sgy doctor --cwd '<repo>'
```

仅在环境首次使用、引擎变更或执行失败时运行 `doctor`。内置 sgy 只维护 Windows x86_64 运行时。

sgy 不内置 ast-grep。确保 `ast-grep` 在 PATH，或向 wrapper 显式传 `--engine <path>`；不要假定 `sg` 的身份。优先使用已验证的 ast-grep 0.44.1；只有引擎缺失且任务允许安装依赖时才按需安装。

## 输入契约

命令结构固定为：

```text
sgy exec [wrapper options] -- <原生 ast-grep argv...>
```

- `--` 左侧由 sgy 解析，右侧参数按值、顺序和重复项交给 ast-grep，不经二次 shell 解析。
- 显式原生参数优先；未指定时，sgy 只为 batch `run`/`scan` 补结构化输出，并使用低 Token 默认值。
- 不自动补语言、pattern、rule、glob、结果上限或 `-U`。
- 不确定 effective argv 时先运行 `sgy defaults -- <argv>`；它不启动 ast-grep。

```powershell
# 简单结构搜索
& $Sgy exec --cwd '<repo>' -- run -p 'console.log($A)' -l ts src

# 复杂规则扫描
& $Sgy exec --cwd '<repo>' -- scan --rule rules/no-console.yml src
```

## Token-Safe 读取协议

1. 默认使用 `token-safe`，不要额外请求 raw JSON。
2. 已知只需每条命中的文件和完整起止范围、不需正文、捕获或规则诊断时，使用 `--profile locations`；其结果为 0-based 紧凑位置串。
3. 读取 `_sgy.total/files/shown/omitted/complete`；`complete: false` 表示详情或文本被省略，不能从可见列表推断全部结果。
4. 先利用文件/规则汇总缩小范围；需要遗漏详情时，用 `_sgy.cache` 进行分页查询，不要重新无界扫描。
5. 已有准确源码位置但边界不稳时，用 `--cache on --fingerprint-file <file>` 建立可验证 cache，再使用 `process containing`；同文件多个目标复用同一 cache，需浏览多个范围时用 `group-locations`，不要把整份 locations 列表交给模型。
6. 需要完整机器 round-trip 或未知字段时才用 `--profile lossless`，并通过 `--yaml-out` 写本地文件；不要把完整 lossless/cache 输出倾倒到模型上下文。
7. 默认 40 条详情、单文本 400 字符、约 24 KiB 上下文预算只限制可见 YAML，不限制 ast-grep 的扫描或写入集合。
8. 显式 SARIF 可由 Token-Safe 提取 finding；只有完整 SARIF 审计才使用 lossless。

常用取回与聚合：

```powershell
& $Sgy exec --cwd '<repo>' --cache on --fingerprint-file src/a.ts --profile locations -- run --kind function_declaration -l ts src/a.ts
& $Sgy cache query <ID> --file src/a.ts --limit 20
& $Sgy cache get <ID> --result 12
& $Sgy process count --cache-id <ID>
& $Sgy process group --cache-id <ID> --field file
& $Sgy process containing --cache-id <ID> --file src/a.ts --line 42 --column 8 --include-text
& $Sgy process group-locations --cache-id <ID> --file src/a.ts --limit 40
```

位置参数和返回 range 均为 0-based、end-exclusive。`containing` 并列时返回全部最小项，且只证明当前 AST 查询集合内的语法包含；源码变化会被拒绝并要求重扫。正文可能较大，只在它能替代后续定向读取时请求。

## Rewrite 安全门

先预览，不传 `-U`：

```powershell
& $Sgy exec --cwd '<repo>' -- run -p 'console.log($A)' -r 'logger.info($A)' -l ts src
```

确认 workspace、glob、总匹配数、文件集合、replacement 和 diff 后，才对同一命令显式增加 `-U`。应用后重跑旧 pattern，检查相关 diff，并执行 formatter、lint/typecheck 和定向测试；不得覆盖无关用户改动。

`_sgy.write.applied_changes` 来自原生 stderr。`affected_files_complete: false` 表示 ast-grep 没有报告精确文件集合，必须沿用 preview 的文件列表核验，不能把 `null` 当作零文件。

## 原生 fallback

内置和全局 sgy 都不可用时，直接使用完整命令 `ast-grep`。小结果使用 `--json=compact`，大结果使用 `--json=stream`；本地处理后只向模型提供总数、文件数和少量必要字段。不要直接倾倒 pretty JSON、完整 JSONL、整文件或重复上下文，也不要为了模型预算给原生扫描增加 `--max-results`。

原生 range 为 0-based；机器处理保持原值，面向用户转为 1-based 时明确说明。

## 最终回复

只报告 pattern/rule、范围、总数/文件数、少量代表性定位和截断说明。发生改写时补充修改文件、残留匹配与验证结果；版本、依赖或环境未验证时明确限制。
