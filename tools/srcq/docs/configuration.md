# srcq 配置与只读诊断

## 配置位置与优先级

有效值从高到低选择：

```text
显式 ast-grep argv > 显式 srcq 参数 > 当前目录 .srcq.yml > 用户配置 > 内置默认值
```

用户配置位置为 `%APPDATA%\srcq\config.yml`。

项目配置只读取启动目录中的 `.srcq.yml`，不会向父目录递归搜索。两个配置文件都必须声明 `schema: sgy.config/v1`，大小不超过 64 KiB，并使用不含 tag、anchor 或 alias 的安全 YAML。

## 配置字段

项目配置只允许影响模型上下文和缺省输出策略：

```yaml
schema: sgy.config/v1
profile: token-safe
native_defaults: true
max_detail_results: 40
max_text_chars: 400
max_context_bytes: 24576
```

`profile` 可选 `token-safe`、`locations`、`lossless`、`files` 或 `custom`；`profile: custom` 时还可以使用 `keep_fields` 和 `prune_fields`。项目配置禁止 `engine`、`cwd` 和 `cache`，未知字段也会被拒绝；因此仓库内配置不能选择可执行文件、扩大工作目录、开启 cache 写入或指定输出路径。

用户配置额外允许：

```yaml
schema: sgy.config/v1
engine: C:\tools\ast-grep.exe
cwd: D:\work\repo
cache: auto
profile: token-safe
```

完整字段及数值约束以 `srcq schema` 输出为准。`engine`、`cwd` 和字符串字段必须是 YAML string；预算必须是整数。显式 CLI 参数始终覆盖配置文件。

## 检查命令

以下命令都输出有界安全 YAML：

```text
srcq schema
srcq capabilities
srcq doctor [--engine PATH] [--cwd PATH]
srcq defaults [wrapper options] -- <ast-grep argv...>
```

- `schema` 输出 `sgy.config/v1` 的 JSON Schema 表达和项目/用户 scope 规则。
- `capabilities` 输出 wrapper 命令、格式、安全 YAML、配置和协议能力；不查找或启动 engine。
- `defaults` 加载配置并展示最终设置、每个设置的来源、注入项和 effective argv；不查找或启动 engine。
- `doctor` 检查配置、工作目录、engine 路径与 `--version`、cache 位置/权限、安全 YAML 往返和 LSP/TTY 限制；不会执行真实扫描。

`doctor` 全部必要检查通过时退出 0；发现配置、路径、engine、版本、cache 权限或 YAML 问题时仍输出 `sgy.doctor/v1`，并退出 1。wrapper 自身无法编码或写出诊断时使用保留的 120–127 错误码。

cache root 已存在时，doctor 会在其中创建并立即删除一个临时探针文件；root 尚未创建时不会在其父目录试写，而是明确报告权限尚未验证。
