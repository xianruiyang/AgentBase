# srcq

`srcq` 是 Windows 本地源码查询适配器。现有 ast-grep 命令、profile、cache、process、TTY/LSP 和 rewrite 合同保持不变；新增的 `srcq rg` 与 `srcq fd` 命令域把原生参数完整放在 `--` 后，并只在安全等价时压缩模型可见输出。

```text
ast-grep 原生输出 → 可选完整缓存 → YAML profile → 模型上下文
```

## 当前状态

- 当前版本：`srcq 0.2.0`。
- 当前固定验证引擎：`ast-grep 0.42.0`。
- 精确验证的 ast-grep 版本：`0.41.1`、`0.42.0`、`0.44.1`；不外推为连续版本范围。
- rg/fd 候选命令域精确验证 `ripgrep 15.1.0` 与 `fd 10.4.2`；29 个公开主模式均有持久分类，版本不匹配时执行入口局部拒绝，`doctor` 给出读回。
- 唯一维护平台是 Windows x86_64 MSVC，已完成真实引擎、协议、release 和安装生命周期。
- `srcq` 不包含 ast-grep、ripgrep 或 fd，也不安装语言运行时；必须另行提供相应精确版本的原生引擎。
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

文本与文件查询同样保持原生 argv，不引入第二套简化语法：

```powershell
srcq rg exec --view auto --limit 80 -- -n -F 'needle' -g '*.cpp' .
srcq fd exec --view auto --limit 80 -- -t f 'CommandDispatch' .
srcq rg exec --receipt full -- -n -F 'needle' .
srcq rg defaults --view grouped -- -n -F 'needle' .
srcq fd doctor
```

普通 rg 搜索和 fd 路径结果先完整有界捕获，再按所选 view 的证据单元投影：文件按去重文件、位置按真实匹配、正文按匹配与上下文、摘要按完整集合。默认 v2 回执固定返回总量与结果、展示、正文三类完整性；非零退出和分页字段只在发生时出现，显式 `--receipt full` 才返回 backend、引擎版本、mode、view 和字节数等诊断。只有分页或 full 回执需要身份时才持久化快照；分页响应中的 `query_snapshot` 与 `next_cursor` 必须原样用于下一页，backend、cwd、原生 argv、引擎版本、snapshot 或实际 view 不匹配时拒绝续页。二进制/NUL 模式要求 `--artifact-out`，fd exec/batch 直接透传，help、统计和其他显式文本报告默认有界。详见 [rg/fd 查询网关](docs/query-gateway.md)。

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
- [rg/fd 查询网关](docs/query-gateway.md)
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
