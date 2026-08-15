---
name: powershell-usage
description: 在 Windows 上用 PowerShell 7（pwsh）编写或审查命令，或执行尚无已验证模板覆盖的管道、数组、控制流、多行文本、路径组合、原生退出码、编码或写入时使用；不用于单条精确只读 cmdlet、调用已知脚本，或直接复用已加载正式来源给出的命令模板。
---

# PowerShell Usage

- 以 PowerShell 7（`pwsh`）为唯一项目基线；普通任务不重复探测版本，不增加旧版兼容分支。Bash here-doc 不是 PowerShell 语法。
- 精确路径用 `-LiteralPath`，通配符才用 `-Path`；原生程序用明确的 `.exe` 名称并检查 `$LASTEXITCODE`，cmdlet 需失败中断时用 `-ErrorAction Stop`。
- 命令默认分开执行；必要控制流用换行和语句块。先把 `foreach` 结果赋给数组再接管道；range 作为参数时加括号，文本行号与数组 0-based 索引分开计算。
- 多行文本用 here-string；项目文本修改优先 `apply_patch`，必须命令写出时显式使用 UTF-8 无 BOM。不用命令串联无关动作或跨 shell 传递破坏性文件列表。
