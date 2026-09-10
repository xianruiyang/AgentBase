---
name: powershell-usage
description: 在 Windows 上用 PowerShell 7（pwsh）编写、审查或执行尚无已验证模板覆盖，且涉及原生命令 argv 中会改变边界的正则、引号、反斜杠或空参数，或涉及管道、数组、控制流、多行文本、路径组合、原生退出码、编码或写入时使用；读取、解析与字段投影组成的管道即使只有一条命令也适用。不用于参数边界明确的单条精确只读命令、调用已知脚本或直接复用已加载正式来源的命令模板。
---

# PowerShell Usage

- 以 PowerShell 7（`pwsh`）为唯一基线；普通任务不重复探测版本或新增旧版兼容。Bash here-doc 不是 PowerShell 语法。
- “单条精确只读 cmdlet”仅指无需重设计的已知调用；读取、解析、过滤或投影组合成的管道即使写在一行，仍适用本 skill。
- 精确路径用 `-LiteralPath`，通配符才用 `-Path`；原生程序用明确的 `.exe` 名称，cmdlet 需失败中断时用 `-ErrorAction Stop`。
- 原生命令结束后，在被覆盖前读取或保存 `$LASTEXITCODE`，按工具合同解释非零值；确认失败则停止依赖动作。`try/catch` 或 `-ErrorAction Stop` 不默认保证捕获原生失败，见 [PowerShell 错误处理](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_error_handling#external-program-errors)。
- 参数逐个保持边界：复杂或动态参数优先用变量、数组与 splatting，明确的字面量可直传。不插值文本优先单引号，反斜杠不转义双引号。不将参数拼成命令字符串；工具提供 `-e`、`--` 等边界时使用其原生接口。
- 数组展开不保证所有调用链都原样传参。嵌入引号、空参数或 `.cmd/.bat` 调用使边界影响结果时，按已验证宿主与入口合同核对实际参数传递模式及下游解析；PowerShell 7.3 起的 `$PSNativeCommandArgumentPassing` 在 Windows 模式下对部分程序及脚本使用 Legacy 行为，见 [原生参数解析](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_parsing#passing-arguments-that-contain-quote-characters)。已有适用证据时直接复用，不例行探测版本或改变宿主偏好。
- 命令默认分开执行，控制流用换行与语句块。`foreach` 结果先赋数组再接管道；range 参数加括号，文本行号与数组 0-based 索引分算。
- 多行文本用 here-string，项目文本修改优先 `apply_patch`。既有文件保留编码与 BOM；新文件沿项目约定，无约定用 UTF-8 无 BOM，命令写出须显式指定编码。不串联无关动作或跨 shell 传递破坏性文件列表。
