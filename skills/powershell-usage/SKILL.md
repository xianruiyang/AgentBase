---
name: powershell-usage
description: 在 Windows 上使用 PowerShell 7（pwsh）编写、执行或审查命令时使用，避免 Bash 语法、命令串联、数组、管道、路径、退出码和编码错误；宿主未达到 PowerShell 7 时先通过当前项目的正式环境准备入口补齐，不在本 skill 内维护旧版兼容；不用于没有 PowerShell 命令的普通 Windows 任务。
---

# PowerShell Usage

## 运行基线

* 以 PowerShell 7（`pwsh`）为支持基线；语法或编码依赖版本时，先读 `$PSVersionTable.PSEdition` 与 `$PSVersionTable.PSVersion`，不是 `Core` 或主版本低于 `7` 时先完成当前项目的正式主机准备并开启新任务，不增加旧版兼容分支
* Bash here-doc 不是 PowerShell 语法；向原生程序传递多行文本时使用 here-string 和管道

## 命令规则

* 命令优先分开执行；同一脚本中的必要控制流使用换行和语句块，不为展示分隔或方便复制而串联无关命令
* 原生程序失败检查 `$LASTEXITCODE`；PowerShell cmdlet 需要失败中断时使用 `-ErrorAction Stop`
* 精确路径使用 `-LiteralPath`，通配符使用 `-Path`；`rg` 等工具优先使用自身的 `-g/--glob`
* 明确调用原生程序时可写完整名称，如 `curl.exe`，避免同名 alias 或函数改变解析结果
* 数组中的命令结果使用换行分隔，不用逗号分隔命令
* range 作为参数时加括号，如 `Select-Object -Index (140..190)`
* PowerShell 数组索引从 `0` 开始；读取文本第 141 至 191 行使用 `[140..190]`
* `foreach (...) { ... }` 不能直接接管道；先赋值、包进 `& {}`，或使用 `ForEach-Object`
* 项目文本的局部修改优先使用 `apply_patch`；必须由命令写出 UTF-8 无 BOM 文本时显式使用 `-Encoding utf8NoBOM`

## 常用写法

```powershell
if ($PSVersionTable.PSEdition -ne 'Core' -or $PSVersionTable.PSVersion.Major -lt 7) {
    throw 'PowerShell 7 or newer is required'
}
```

```powershell
rg.exe -n --heading -M 240 --max-columns-preview `
    -F 'Target' <targets> |
    Select-Object -First 80
$rgExit = $LASTEXITCODE
if ($rgExit -gt 1) {
    throw "rg failed: $rgExit"
}
```

```powershell
$code = @'
print("hello")
'@
$code | python.exe -
```

```powershell
$rows = foreach ($item in $items) {
    $item
}
$rows | Sort-Object
```
