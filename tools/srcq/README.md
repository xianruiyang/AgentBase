# srcq

`srcq` 是 Windows 本地源码查询与指标适配器。现有 ast-grep 命令、profile、cache、process、TTY/LSP 和 rewrite 合同保持不变；`srcq rg <native argv...>`、`srcq fd <native argv...>` 与 `srcq scc <native argv...>` 直接接受原生参数，并只在安全等价时压缩模型可见输出。

```text
完整事实源 → model 干净证据 / machine 稳定结构 / native 原生通道
```

## 当前状态

- 当前正式 Release：`srcq 0.6.0`。
- `0.6.0` 在不依赖 LSP 的前提下增加 C# 词法作用域内的显式类型调用、partial 成员/短属性链、源码静态类型和 `.sln`/`.csproj` Compile 范围解析；Go、Python、Rust、JavaScript、TypeScript/TSX 复用一套 typed relation 中间层，从显式类型、构造、当前接收者、字段和静态限定形成类型候选，并只读恢复本地项目引用范围。当前源码还会为 JavaScript、TypeScript/TSX 类方法的 incoming 调用者保留由 AST 外层 class 直接证明的可选限定身份；动态分派、函数值、宏/生成代码和不能唯一证明的类型仍保持 unknown。
- 当前固定验证引擎：`ast-grep 0.44.1`；`srcq symbol` 的 outline 关系能力以该版本为正式开发基线。
- 当前 AST、透传、协议、压力与发布验证统一使用 ast-grep `0.44.1`；不再维护较早版本的现行兼容矩阵。
- rg/fd 候选命令域已在 `ripgrep 15.1.0`、Codex PATH 中的 `ripgrep 15.2.0` 与 `fd 10.4.2` 上验证；29 个公开主模式均有持久分类，版本只标识证据范围，不参与运行准入。
- scc 查询域已在 `scc 3.7.0` 上验证，覆盖语言汇总、逐文件记录、json2、显式文本格式、输出文件、分页、快照、协议变化回退与非零退出；版本只标识证据范围，不参与运行准入。
- 唯一维护平台是 Windows x86_64 MSVC，已完成真实引擎、协议、release 和安装生命周期。
- `srcq` 不包含 ast-grep、ripgrep、fd 或 scc，也不安装语言运行时；必须另行提供可启动的原生引擎。hyperfine 是 AgentBase 独立的命令基准工具，不是 srcq backend 或运行依赖。
- 为保持迁移前 AST 结果与缓存可读，版本化数据合同继续使用既有 `_sgy` 字段和 `sgy.*` schema 命名；它们是协议兼容标识，不是可执行文件、安装目录或第二运行时入口。
- 发布生成的 `THIRD_PARTY_LICENSES.txt` 使用 `SRCQ THIRD-PARTY LICENSES` 产品标题；兼容协议标识不得重新成为发布产物品牌。

## 快速开始

从私有 GitHub Release 认证下载正式版本并安装，不需要 Rust 或本仓库工作区；目标账号必须有仓库读取权限，且本机 `gh` 已完成认证：

```powershell
gh release download srcq-v0.6.0 --repo xianruiyang/AgentBase --pattern install-srcq-release.ps1
.\install-srcq-release.ps1 Install -Version 0.6.0
& (Join-Path $env:LOCALAPPDATA 'Programs\srcq\current\srcq.exe') doctor
```

已有同一发布批次的本地归档、校验和与安装脚本时可离线安装：

```powershell
.\scripts\install-srcq.ps1 Install -Archive .\dist\srcq-<version>-x86_64-pc-windows-msvc.zip
srcq doctor
```

安装器直接输出默认是最小模型回执；程序需要完整安装、完整性和 PATH 合同时显式传入 `-View Machine`。两种视图来自同一检查结果，详见[安装、升级与卸载](docs/installation.md)。

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
srcq scc --exclude-dir target,node_modules .
```

需要定义、引用或有界调用关系时，`srcq symbol` 在一次只读调用中组合 rg 与 AST；优先使用 0-based 源码位置，目录可省略：

```powershell
srcq symbol definition --at 'Source/Module/File.cpp:41:9'
srcq symbol references --at 'Source/Module/File.cpp:41:9'
srcq symbol calls --at 'Source/Module/File.cpp:41:9' --direction outgoing --depth 2
```

它返回带范围与歧义边界的候选，不冒充编译器或 LSP 精确语义。语言能力、外部源码根和输出合同见[快速源码关系](docs/symbol-relations.md)。

关系查询不等待常驻 Provider：每次调用都启动新的 srcq、rg 与 ast-grep 进程。默认共享 7500 ms 扫描预算，为端到端 10 秒快速路径保留包装开销；达到预算会以退出 124 明确报告结果不完整。优先传入源码位置或限定名，宽范围超时时先用 `--only-root` 收窄模块；只有确实需要更宽证据时才提高 `--time-budget-ms`。

若把 `files`、`--files` 或 AST 原生命令误写到根级，srcq 只返回上述唯一入口的一行修正，不创建别名或猜测执行。分页结果的下一页只需执行页尾短命令，例如 `srcq more q17`；不要重组控制面、cursor 或原生 argv。

只有调用方明确需要 machine、native/artifact、定向投影、诊断或续页时进入独立控制面：

```powershell
srcq query rg exec --output machine --receipt full -- -n -F 'needle' .
srcq query rg defaults --view grouped -- -n -F 'needle' .
srcq query fd doctor
srcq query scc doctor
```

普通 rg、fd、scc 与 AST 查询默认使用 model 输出：只输出干净证据，正常成功、完整和空结果不附 envelope 或回执；rg/fd 在取得真实结果后比较单行、文件 heading、路径树及组合表示，scc 从同一次完整捕获投影语言或逐文件指标并省略成本估算，files 还会在同一证据页上按实际成本选择扁平行、单表头表格或可逆目录树表格。直接入口会在完整结果机械可证有界且整体表示足够小时一次闭环，其他结果才按内部预算和完整证据单元分页；query 分页用 `@more` 表达剩余数量，并在 `@next` 后提供 `srcq more q<number>` 短续页命令。新句柄只使用不补零的 `q1` 至 `q999999`，在上限后循环选择当前 128 条记录窗口之外的空闲编号；它是临时游标，不是持久身份。其他截断、歧义或写入事实同样只追加必要 `@` 记录。完整 cursor、snapshot 与 argv 绑定保留在同一 query owner 内；parser、round-trip、完整诊断或旧结构化消费者仍通过 `srcq query` 或 AST 显式 `--output machine`，`--receipt full`、`--yaml-out`、`lossless` 和 `custom` 也保持机器合同。二进制、TTY、LSP 与完整原生字节走 native/artifact 通道。详见 [模型可见输出合同](docs/model-output.md) 和 [rg/fd/scc 查询网关](docs/query-gateway.md)。

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
- [rg/fd/scc 查询网关](docs/query-gateway.md)
- [快速源码关系](docs/symbol-relations.md)
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
& '.\scripts\test-install-srcq-views.ps1'
& '.\scripts\test-install-srcq-release.ps1' -Archive <release-zip> -ExpectedVersion <version>
```
