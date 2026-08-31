---
name: powershell-usage
description: 在 Windows 上用 PowerShell 7（pwsh）编写、审查或执行尚无已验证模板覆盖，且涉及原生命令 argv 中会改变边界的正则、引号、反斜杠或空参数，或涉及管道、数组、控制流、多行文本、路径组合、原生退出码、编码或写入时使用；读取、解析与字段投影组成的管道即使只有一条命令也适用。不用于参数边界明确的单条精确只读命令、调用已知脚本或直接复用已加载正式来源的命令模板。
---

# PowerShell Usage

- 以 PowerShell 7（`pwsh`）为唯一项目基线；普通任务不重复探测版本，不增加旧版兼容分支。Bash here-doc 不是 PowerShell 语法。
- “单条精确只读 cmdlet”只指无需重新设计的一个已知 cmdlet 调用；组合读取、解析、过滤或字段投影的管道仍属于命令编写，不因物理上写在一行而排除本 skill。
- 精确路径用 `-LiteralPath`，通配符才用 `-Path`；原生程序用明确的 `.exe` 名称并检查 `$LASTEXITCODE`，cmdlet 需失败中断时用 `-ErrorAction Stop`。
- 原生命令参数含正则、引号、反斜杠、空字符串或前导 `-` 且边界会影响语义时，每个 argv token 用单独变量或数组持有并通过 splatting 传入；不插值文本优先用单引号，PowerShell 不以反斜杠转义双引号。不得把参数重新拼成一个命令字符串；对应工具提供 `-e`、`--` 等正式边界时使用其原生接口。
- 命令默认分开执行；必要控制流用换行和语句块。先把 `foreach` 结果赋给数组再接管道；range 作为参数时加括号，文本行号与数组 0-based 索引分开计算。
- 多行文本用 here-string；项目文本修改优先 `apply_patch`，必须命令写出时显式使用 UTF-8 无 BOM。不用命令串联无关动作或跨 shell 传递破坏性文件列表。
