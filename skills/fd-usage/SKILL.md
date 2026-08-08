---
name: fd-usage
description: 使用 fd 有界查找文件或目录；用于文件发现、目录发现以及按文件名或完整路径匹配，强制区分 pattern 与 path、以 -C 固定基准目录并用 --max-results 控制输出。
---

# fd Usage

## 决策规则

1. 使用语法 `fd [选项] [pattern] [path]...`；pattern 在前，搜索路径在后。`fd -t f src` 表示在当前基准目录查找名称匹配 `src` 的文件，不是搜索 `src` 目录。
2. 每条命令都使用 `-C <root>`，将 `<root>` 设为能覆盖目标且保持输出可定位的最长公共父目录。`-C` 会同时改变输出基准及其后相对搜索路径的解析基准。
3. 明确选择对象类型：文件使用 `-t f`，目录使用 `-t d`；只有任务确实需要混合结果时才省略 `-t`。
4. 先用类型、准确 pattern、相对搜索路径、`-d` 和 `-E` 缩小范围，再设置结果上限；不得用较小的 `--max-results` 掩盖过宽搜索，否则目标可能尚未遍历到。
5. 输出规模未知时使用 `--max-results` 从源头停止搜索，不要仅依赖 `Select-Object -First`。普通发现默认 40 条，文件枚举默认 60 条；只有证据表明需要时才提高。只需一个结果时使用 `-1`。
6. fd 默认跳过隐藏项，并遵守 `.gitignore`、`.ignore`、`.fdignore` 和全局 ignore；仅在任务需要时加 `-H/--hidden` 或 `-I/--no-ignore`，不要无理由使用 `-u` 扩大范围。
7. `-p/--full-path` 只把 pattern 的匹配对象改为完整路径，不负责缩短输出；仍使用 `-C` 控制输出前缀。Windows 完整路径正则以 `\\` 匹配反斜杠；`--path-separator /` 只改变打印格式。剩余长前缀大量重复时再映射为稳定短标签。
8. fd 没有匹配时退出码仍为 `0`；空输出不是命令错误，但在断言文件不存在前先检查 ignore、hidden、pattern、path 和结果上限。
9. fd 仅用于发现，不使用 `-x/--exec` 或 `-X/--exec-batch` 批量执行操作。不确定参数含义时先以小上限验证。

## Pattern 模式

| 意图 | 参数 | 语义 |
| --- | --- | --- |
| 正则匹配文件名 | 无额外参数 | 默认模式 |
| 字面子串匹配 | `-F/--fixed-strings` | 不是精确文件名匹配 |
| 精确文件名或 glob | `-g/--glob` | 如 `SKILL.md`、`*.cpp` |
| 匹配完整路径 | `-p/--full-path` | pattern 仍默认为正则，可与 `-F` 或 `-g` 组合 |

## 模板

```powershell
# 在两个相对路径内正则查找文件
fd.exe -t f -C '<common-root>' --max-results 40 `
    'pattern' 'src' 'tests'

# 精确查找目录名
fd.exe -t d -g -C '<root>' --max-results 40 `
    'Generated'

# 列出 src 下文件；`.` 是匹配所有名称的 pattern
fd.exe -t f -C 'src' --max-results 60 .

# 用正则匹配完整路径
fd.exe -t f -p -C '<root>' --max-results 40 `
    'Utilities\\.*Authoring' 'src'

# 限制遍历深度；深度从搜索路径开始计算
fd.exe -t f -d 2 -C '<root>' --max-results 40 `
    . 'src'
```
