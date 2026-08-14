# ast-grep pattern 与 rule 速查

仅在编写、调试 pattern/YAML rule 或 rewrite 时读取。

以下 PowerShell 示例中的 `$Sgy` 指向 `<skill_dir>\scripts\bin\windows-x86_64\sgy.exe`。

## Pattern

| 写法 | 含义 |
| --- | --- |
| `$A` | 捕获一个具名节点 |
| `$_` | 匹配但不关心该节点 |
| `$$A` | 捕获具名或非具名节点 |
| `$$$ARGS` | 捕获零个或多个节点 |
| 重复 `$A` | 各位置文本必须相同 |

- 元变量名使用大写字母、数字或下划线。
- pattern 是目标语言可解析的代码，不是正则。
- shell 中用单引号保护 `$`。
- 有语法歧义时使用 `context + selector`，不要反复猜 pattern。

```powershell
& $Sgy exec -- run -p 'foo($$$ARGS)' -l ts src
& $Sgy exec -- run -p '$A == $A' -l ts src
& $Sgy exec -- run -p '$A == $B' -l ts --strictness smart src
```

## YAML rule

只有 `inside`、`has`、否定、组合关系或 constraints 无法由简单 pattern 表达时才创建 rule：

```yaml
id: no-console-log
language: TypeScript
rule:
  pattern: console.log($A)
message: 避免使用 console.log
severity: warning
```

```yaml
id: await-inside-function
language: TypeScript
rule:
  all:
    - pattern: await $A
    - inside:
        kind: function_declaration
        stopBy: end
message: function 中的 await
severity: info
```

按需使用 `all`、`any`、`not`、`inside`、`has`、`precedes`、`follows` 和 `constraints`。关系规则明确 `stopBy`，避免意外跨越边界。

```yaml
constraints:
  A:
    regex: ^debug
```

局部节点无法独立解析时：

```yaml
rule:
  pattern:
    context: const $A = $B;
    selector: variable_declarator
```

## 调试顺序

1. 确认语言、后缀、路径、ignore 和 glob。
2. 把 pattern 缩成最小可解析片段，在单个已知文件或 stdin 验证。
3. 检查元变量大小写、单节点/多节点捕获和 strictness。
4. 最后才用 `--debug-query=pattern|ast|cst|sexp`。
5. 结合退出码和 stderr 区分无匹配、无效 pattern/rule、语言或路径错误。

## Rewrite

```powershell
# 预览
& $Sgy exec -- run -p 'console.log($A)' -r 'logger.info($A)' -l ts src

# 确认后应用
& $Sgy exec -- run -p 'console.log($A)' -r 'logger.info($A)' -l ts -U src
```

复杂 fix 写入 rule；先 `scan --rule ...`，确认后再对同一规则显式传 `-U`。应用后重跑旧 pattern、检查 diff，并执行 formatter、lint/typecheck 和定向测试。
