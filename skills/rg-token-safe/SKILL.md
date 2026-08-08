---
name: rg-token-safe
description: 在 PowerShell/Codex 中以可定位、有限且低重复的格式运行 rg；用于任何 rg 输出会进入模型上下文的搜索，要求正文匹配显式选择 --heading 或 --no-filename，并分别限制单行宽度、总行数和重复路径。
---

## 决策规则

1. 先用准确目标路径、`-g`、`-t`、`.rgignore` 和排除目录缩小范围；不要同时搜索源码及其生成、镜像、缓存或旧版副本，除非任务需要比较。
2. 每条输出匹配正文的命令必须显式且只选择一个文件身份参数：多文件、目录、glob 或文件数未知时使用 `--heading`；单个已知文件使用 `--no-filename`。
3. `-M 240 --max-columns-preview` 只限制单行宽度，绝不能替代 `--heading` 或 `--no-filename`；不得只写宽度参数而省略文件身份参数。
4. 每条未知规模的正文命令还必须以 `Select-Object -First 80` 限制总行数；文件身份、单行宽度、总行数是三项独立且同时成立的约束。
5. `-l`、`rg --files` 和仅检查退出码时不使用文件身份参数。候选文件列表默认限制为 40 行，`rg --files` 默认限制为 60 行。
6. 预计命中文件很多时先用 `-l`，范围已小时直接搜索，避免扫描两次。
7. `-m N` 只限制每个文件，不能替代全局 `Select-Object -First N`；仅在不需要完整查看单文件命中时使用。
8. `-C N` 会扩大输出，只在范围已收窄且确实需要上下文时使用。
9. 仅在输出路径前缀长且大量重复时裁剪公共前缀；裁剪后必须仍可准确定位文件。仅在确实需要稳定顺序时使用 `Sort-Object`。

## 输出模式

| 场景 | rg 输出参数 | 默认总上限 |
| --- | --- | --- |
| 单个已知文件的正文 | `-n --no-filename -M 240 --max-columns-preview` | 80 行 |
| 目录、glob、多个路径或文件数未知的正文 | `-n --heading -M 240 --max-columns-preview` | 80 行 |
| 候选文件名 | `-l` | 40 行 |
| 文件枚举 | `--files` | 60 行 |

## 正文模板

已知文本优先使用 `-F`，多个条件各用一个完整的 `-e`：

```powershell
rg.exe -n --heading -M 240 --max-columns-preview `
    -F -e 'TextA' -e 'TextB' `
    -g '*.cpp' -g '*.h' `
    -g '!**/Generated/**' -g '!**/Intermediate/**' `
    <targets> |
    Select-Object -First 80

$rgExit = $LASTEXITCODE
if ($rgExit -eq 1) { exit 0 }
exit $rgExit
```

单个已知文件仍须同时写出文件身份、宽度和总行数限制：

```powershell
rg.exe -n --no-filename -M 240 --max-columns-preview `
    -F -e 'TargetText' <known-file> |
    Select-Object -First 80
```

沿用上面的退出码处理。需要逐文件限制时再加 `-m N`，需要上下文时再加 `-C N`。

## 候选与文件列表

```powershell
rg.exe -l -F -e 'TargetText' <targets> |
    Select-Object -First 40
```

```powershell
rg.exe --files <targets> -g '*.py' |
    Select-Object -First 60
```

搜索无匹配时退出码为 `1`；只有当无匹配符合当前命令语义时才转为成功。先保存 `$LASTEXITCODE`，将 `1` 转为 `0`，并原样传播大于 `1` 的真实错误。

## Pattern 与路径

- 字面文本优先使用 `-F`，尤其是原文包含 `( ) | .* \s TEXT("...")` 时。
- 确需正则时，用单引号包住完整 pattern；独立英文单词使用 `\bword\b`；不要让 PowerShell 引号提前结束并暴露 `|`。
- 裁剪路径前先加 `--path-separator /`。公共前缀与 rg 输出必须采用相同的绝对或相对形式、相同分隔符，并包含末尾分隔符。
- 多个目标没有共同前缀时，分别映射为 `plugin:/`、`cmd:/` 等稳定短标签；小结果不要增加裁剪逻辑。
