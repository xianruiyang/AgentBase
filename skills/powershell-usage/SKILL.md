---
name: powershell-usage
description: 在 Windows PowerShell 中编写或审查命令时使用，避免 Bash 语法、命令串联、数组、管道、路径、退出码和编码错误；不用于没有 PowerShell 命令的普通 Windows 任务。
---

# PowerShell Usage

* 默认兼容 Windows PowerShell 5.1，不使用 `&&`、`||` 或 Bash here-doc
* 命令优先分开执行；同一脚本中的必要控制流使用换行和语句块，不为展示分隔或方便复制而用 `;` 串联无关命令
* 原生程序失败检查 `$LASTEXITCODE`；PowerShell cmdlet 需要失败中断时使用 `-ErrorAction Stop`
* 精确路径使用 `-LiteralPath`，通配符使用 `-Path`；`rg` 等工具优先使用自身的 `-g/--glob`
* 明确调用原生程序时可写完整名称，如 `curl.exe`，避免同名 alias
* 数组中的命令结果使用换行或分号分隔，不用逗号分隔命令
* range 作为参数时加括号，如 `Select-Object -Index (140..190)`
* PowerShell 数组索引从 `0` 开始；读取文本第 141 至 191 行使用 `[140..190]`
* `foreach (...) { ... }` 不能直接接管道；先赋值、包进 `& {}`，或使用 `ForEach-Object`
* Windows PowerShell 5.1 不使用未指定编码的 `Out-File`、`>` 或 `>>` 修改项目文本；局部修改优先使用 `apply_patch`

## 常用写法

```powershell
rg.exe -n -F 'Target' <targets>
if ($LASTEXITCODE -ne 0) {
    throw "rg failed: $LASTEXITCODE"
}
```

```powershell
$code = @'
print("hello")
'@
$code | python.exe -
```

```powershell
$targets = @(
    Join-Path $root 'A'
    Join-Path $root 'B'
)
```

```powershell
Get-Content -LiteralPath $path |
    Select-Object -Skip 140 -First 51
```

```powershell
$rows = foreach ($item in $items) {
    $item
}
$rows | Sort-Object
```
