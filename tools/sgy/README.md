# sgy

`sgy` 是 ast-grep 的本地 CLI 适配器：原生参数放在 `--` 后交给 ast-grep，结构化结果先按原生 JSON 解析，再输出安全 YAML。默认 `token-safe` profile 会在完整执行之后压缩模型可见上下文；它不会缩小 ast-grep 的扫描或写入范围。

```text
ast-grep 原生输出 → 可选完整缓存 → YAML profile → 模型上下文
```

## 当前状态

- 当前版本：`sgy 0.1.2`。
- 当前固定验证引擎：`ast-grep 0.42.0`。
- 精确验证的 ast-grep 版本：`0.41.1`、`0.42.0`、`0.44.1`；不外推为连续版本范围。
- 唯一维护平台是 Windows x86_64 MSVC，已完成真实引擎、协议、release 和安装生命周期。
- `sgy` 不包含 ast-grep，也不安装语言运行时；必须另行提供可执行的 `ast-grep`。

## 快速开始

安装正式候选并检查环境：

```powershell
.\scripts\install-sgy.ps1 Install -Archive .\dist\sgy-<version>-x86_64-pc-windows-msvc.zip
sgy doctor
```

结构搜索时不必手写 JSON 参数；缺省 batch `run`/`scan` 会由 wrapper 补 `--json=stream`：

```powershell
sgy exec -- run -p 'console.log($A)' -l ts src
sgy exec -- scan --rule rules/no-console.yml src
```

rewrite 先预览，不传 `-U`：

```powershell
sgy exec -- run -p 'console.log($A)' -r 'logger.info($A)' -l ts src
```

确认范围后，只有显式传入 `-U` 才写文件：

```powershell
sgy exec -- run -p 'console.log($A)' -r 'logger.info($A)' -l ts -U src
```

wrapper 参数必须位于 `--` 前，原生 ast-grep 参数位于 `--` 后：

```powershell
sgy exec --profile lossless --cache off -- run -p 'foo($A)' -l ts src
```

## Profile

| Profile | 用途 | 模型上下文建议 |
| --- | --- | --- |
| `token-safe` | 默认；投影必要字段、聚合、省略和截断 | 默认使用 |
| `locations` | 仅保留每条命中的 0-based 文件与起止位置，并紧凑序列化 | 已知只需定位、不需正文或捕获 |
| `lossless` | JSON value 与 YAML value 等价，保留未知字段 | 机器 round-trip 或完整审计 |
| `files` | 只关注命中文件与计数 | 先收窄范围 |
| `custom` | 显式 `--keep-fields`/`--prune-fields` | 已知字段需求 |

默认 Token-Safe 基线是 40 条详情、每个文本字段 400 字符、24 KiB YAML 软预算。它们只影响输出；不会向 ast-grep 注入结果上限。完整 benchmark 显示 lossless YAML 本身通常比 compact JSON 更耗 Token，节省来自 Token-Safe 投影和预算。

`locations` 沿用同一 `_sgy.total/shown/omitted/files/complete/cache` 完整性合同，`results` 项格式为 `file:start_line:start_column-end_line:end_column`。输出采用 JSON 兼容的安全 YAML 1.2 紧凑表示；不要在仍需正文、metaVariables、rule 或 severity 时使用。

## 文档

- [CLI 使用](docs/usage.md)
- [安装、升级与卸载](docs/installation.md)
- [配置与诊断](docs/configuration.md)
- [缓存与取回](docs/cache.md)
- [安全边界](docs/security.md)
- [命令兼容](docs/compatibility.md)
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
