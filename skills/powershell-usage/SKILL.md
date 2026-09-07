---
name: powershell-usage
description: 在 Windows 上用 PowerShell 7（pwsh）编写、审查或执行尚无已验证模板覆盖，且涉及原生命令 argv 中会改变边界的正则、引号、反斜杠或空参数，或涉及管道、数组、控制流、多行文本、路径组合、原生退出码、编码或写入时使用；读取、解析与字段投影组成的管道即使只有一条命令也适用。不用于参数边界明确的单条精确只读命令、调用已知脚本或直接复用已加载正式来源的命令模板。
---

# PowerShell Usage

- 以 PowerShell 7（`pwsh`）为唯一项目基线；普通任务不重复探测版本，不增加旧版兼容分支。Bash here-doc 不是 PowerShell 语法。
- “单条精确只读 cmdlet”只指无需重新设计的一个已知 cmdlet 调用；组合读取、解析、过滤或字段投影的管道仍属于命令编写，不因物理上写在一行而排除本 skill。
- 精确路径用 `-LiteralPath`，通配符才用 `-Path`；原生程序用明确的 `.exe` 名称，cmdlet 需失败中断时用 `-ErrorAction Stop`。
- 原生命令结束后，在其他原生命令覆盖前读取或保存 `$LASTEXITCODE`，按该工具的正式退出码语义判断，不把所有非零值一律判为失败；确认失败时停止依赖其结果的后续动作。默认不把 `try/catch` 或 `-ErrorAction Stop` 当作原生命令失败已被捕获的保证；需要处理时见 [PowerShell 错误处理](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_error_handling#external-program-errors)。
- 原生命令参数逐个保持边界；复杂或动态参数优先用变量、数组与 splatting，简单且边界明确的字面量可直接传入。不插值文本优先用单引号，PowerShell 不以反斜杠转义双引号。不得把参数重新拼成一个命令字符串；对应工具提供 `-e`、`--` 等正式边界时使用其原生接口。
- 数组展开不保证所有调用链都原样传参。嵌入引号、空参数或 `.cmd/.bat` 调用使边界影响结果时，按已验证宿主与入口合同核对实际参数传递模式及下游解析；PowerShell 7.3 起的 `$PSNativeCommandArgumentPassing` 在 Windows 模式下对部分程序及脚本使用 Legacy 行为，见 [原生参数解析](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_parsing#passing-arguments-that-contain-quote-characters)。已有适用证据时直接复用，不例行探测版本或改变宿主偏好。
- 命令默认分开执行；必要控制流用换行和语句块。先把 `foreach` 结果赋给数组再接管道；range 作为参数时加括号，文本行号与数组 0-based 索引分开计算。
- 多行文本用 here-string；项目文本修改优先 `apply_patch`。修改既有文件保留其编码与 BOM 约定；新建文件遵守项目约定，没有明确约定时使用 UTF-8 无 BOM，命令写出时显式指定适用编码。不用命令串联无关动作或跨 shell 传递破坏性文件列表。
