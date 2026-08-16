# srcq

`srcq` 是 Windows 本地源码查询适配器。现有 ast-grep 命令、profile、cache、process、TTY/LSP 和 rewrite 合同保持不变；`srcq rg <native argv...>` 与 `srcq fd <native argv...>` 直接接受原生参数，并只在安全等价时压缩模型可见输出。

```text
完整事实源 → model 干净证据 / machine 稳定结构 / native 原生通道
```

## 当前状态

- 当前版本：`srcq 0.3.1`。
- 当前固定验证引擎：`ast-grep 0.42.0`。
- 精确验证的 ast-grep 版本：`0.41.1`、`0.42.0`、`0.44.1`；不外推为连续版本范围。
- rg/fd 候选命令域已在 `ripgrep 15.1.0`、Codex PATH 中的 `ripgrep 15.2.0` 与 `fd 10.4.2` 上验证；29 个公开主模式均有持久分类，版本只标识证据范围，不参与运行准入。
- 唯一维护平台是 Windows x86_64 MSVC，已完成真实引擎、协议、release 和安装生命周期。
- `srcq` 不包含 ast-grep、ripgrep 或 fd，也不安装语言运行时；必须另行提供可启动的原生引擎。
- 为保持迁移前 AST 结果与缓存可读，版本化数据合同继续使用既有 `_sgy` 字段和 `sgy.*` schema 命名；它们是协议兼容标识，不是可执行文件、安装目录或第二运行时入口。

## 快速开始

安装正式候选并检查环境：

```powershell
.\scripts\install-srcq.ps1 Install -Archive .\dist\srcq-<version>-x86_64-pc-windows-msvc.zip
srcq doctor
```

结构搜索时不必手写 JSON 参数；缺省 batch `run`/`scan` 会由 wrapper 补 `--json=stream`：

```powershell
srcq exec -- run -p 'console.log($A)' -l ts src
srcq exec -- scan --rule rules/no-console.yml src
```

rewrite 先预览，不传 `-U`：

```powershell
srcq exec -- run -p 'console.log($A)' -r 'logger.info($A)' -l ts src
```

确认范围后，只有显式传入 `-U` 才写文件：

```powershell
srcq exec -- run -p 'console.log($A)' -r 'logger.info($A)' -l ts -U src
```

wrapper 参数必须位于 `--` 前，原生 ast-grep 参数位于 `--` 后：

```powershell
srcq exec --profile lossless --cache off -- run -p 'foo($A)' -l ts src
```

普通文本与文件查询直接沿用原生命令直觉，不需要 `exec`、分隔符、view 或预算：

```powershell
srcq rg -n -F 'needle' -g '*.cpp' .
srcq fd -t f 'CommandDispatch' .
```

若把 `files`、`--files` 或 AST 原生命令误写到根级，srcq 只返回上述唯一入口的一行修正，不创建别名或猜测执行。

只有调用方明确需要 machine、native/artifact、定向投影、诊断或续页时进入独立控制面：

```powershell
srcq query rg exec --output machine --receipt full -- -n -F 'needle' .
srcq query rg defaults --view grouped -- -n -F 'needle' .
srcq query fd doctor
```

普通 rg、fd 与 AST 查询默认使用 model 输出：只输出干净证据，正常成功、完整和空结果不附 envelope 或回执；rg/fd 在取得真实结果后比较单行、文件 heading、路径树及组合表示。直接入口会在完整结果机械可证有界且整体表示足够小时一次闭环，其他结果才按内部预算和完整证据单元分页；只有分页、截断、歧义或写入事实追加最短 `@` 记录。parser、round-trip、完整诊断或旧结构化消费者通过 `srcq query` 或 AST 显式 `--output machine`；`--receipt full`、`--yaml-out`、`lossless` 和 `custom` 也保持机器合同。二进制、TTY、LSP 与完整原生字节走 native/artifact 通道。详见 [模型可见输出合同](docs/model-output.md) 和 [rg/fd 查询网关](docs/query-gateway.md)。

## Profile

| Profile | 用途 | 模型上下文建议 |
| --- | --- | --- |
| `token-safe` | 默认；model 输出文件、范围与源码，machine 保留既有完整性合同 | 默认使用 |
| `locations` | 仅保留每条命中的 0-based 文件与起止位置 | 已知只需定位、不需正文或捕获 |
| `lossless` | JSON value 与 YAML value 等价，保留未知字段 | 机器 round-trip 或完整审计 |
| `files` | 只关注命中文件与计数 | 先收窄范围 |
| `custom` | 显式 `--keep-fields`/`--prune-fields` | 已知字段需求 |

默认 Token-Safe 基线是 40 条详情、每个文本字段 400 字符、24 KiB 机器投影软预算。它们只影响输出；不会向 ast-grep 注入结果上限。model 在同一完整事实源之上移除机器 envelope 和重复捕获，machine 仍可用于解析与审计。

`locations` 的 model 项格式为 `file:start_line:start_column-end_line:end_column`；machine 沿用 `_sgy.total/shown/omitted/files/complete/cache` 和安全 YAML 合同。不要在仍需正文、捕获、rule 或 severity 时使用该 profile。

## 文档

- [CLI 使用](docs/usage.md)
- [安装、升级与卸载](docs/installation.md)
- [配置与诊断](docs/configuration.md)
- [缓存与取回](docs/cache.md)
- [安全边界](docs/security.md)
- [命令兼容](docs/compatibility.md)
- [rg/fd 查询网关](docs/query-gateway.md)
- [模型可见输出合同](docs/model-output.md)
- [排障](docs/troubleshooting.md)
- [开发与发布](docs/development.md)
- [第一版发布门禁](docs/release-checklist.md)
- [许可证与第三方组件](docs/licensing.md)
- [Benchmark 复现](benches/README.md)

## 开发门禁

```powershell
cargo ci-test
cargo ci-build
cargo lint
cargo fmt-check
```
