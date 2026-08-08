# sgy 命令兼容边界

## 参数优先级

sgy 的基本契约是“显式原生 argv 优先，缺省时做安全补全”：

- `--` 后用户 token 的值、顺序和重复项不改写。
- 缺省 batch `run`/`scan` 只补 `--json=stream`，不补语言、pattern、rule、glob、结果上限或写入参数。
- 用户显式 `--json`、`--format`、`--files-with-matches`、交互模式等输出选项会抑制缺省 JSON 注入。
- `--no-native-defaults` 禁止缺省补全；`--strict` 在需要 wrapper 保守失败时使用。
- `sgy defaults ... -- <argv>` 可在不启动引擎的情况下检查最终设置和 effective argv。

## 顶层命令

| ast-grep 命令/模式 | sgy 行为 |
| --- | --- |
| batch `run` | 结构化结果转为所选 YAML profile；files/text/debug 输出走有界 adapter |
| batch `scan` | finding、SARIF、files/text/GitHub report 按显式格式转为 YAML 或有界报告；Token-Safe SARIF 提取真实 findings |
| rewrite/fix 预览与 `-U` | 原生执行/写入集合和退出码保持；YAML 只控制展示 |
| `test`、`new`、help/version | UTF-8 文本包装为 `sgy.raw/v1`；文件副作用保持 |
| `completions`、二进制输出 | 需要显式 `--artifact-out`，stdout 只返回 manifest |
| interactive | 继承 TTY，不注入 JSON，不转换交互字节 |
| `lsp` | stdin/stdout 字节透传；YAML、日志和 telemetry 不进入协议 stdout |
| 未知未来命令 | raw fallback，不猜测为结构化结果，不注入 batch JSON |

显式 native JSON 支持 compact、pretty 和 stream；lossless YAML 以 JSON value 等价为目标并保留未知字段。显式文本或特殊报告格式不会被伪装成 match records。

## 通道和退出状态

- stdout：YAML、显式 artifact manifest，或 LSP/TTY passthrough。
- stderr：原生 stderr 与 wrapper 诊断，除非显式写入 `--stderr-yaml` sidecar。
- 原生退出码保持。wrapper 自身失败使用 120–127；不要把“非零但已有有效诊断 YAML”误判为无输出。
- Token-Safe no-match（code 1、空 stdout/stderr）返回空上下文 YAML并保留 code 1；lossless 不制造原生不存在的 JSON value。
- stdin/EOF 透传给原生命令；`process` 未指定 input/cache 时则从 stdin 读取。

## 版本与平台声明

当前固定基线为 ast-grep 0.42.0；Windows x86_64 还精确验证了 0.41.1 与 0.44.1。支持声明只覆盖这三个精确版本，不把中间未运行版本推断为兼容。未知命令继续使用 raw fallback，不能据此宣称其全部语义已认证。

| 平台 | 当前证据 |
| --- | --- |
| Windows x86_64 MSVC | 三版本真实 run/scan/rewrite/cache、TTY/LSP、确定性 release、PowerShell 5.1 安装生命周期 |
| Linux x86_64 GNU | 0.42.0 真实 run/cache/process、TTY/LSP/协议测试、原生 release、symlink 安装、失败升级回滚与卸载闭环 |
| macOS x86_64/arm64 | 当前源码 target check 与脚本协议；原生运行未签署，第一版暂不发布 |

构建成功或交叉 `cargo check` 不能替代目标平台的原生链接、启动、TTY/LSP 和安装—卸载 smoke。最终发布范围以 release checklist 的原生证据为准；当前只有 Windows x86_64 与 Linux x86_64 可进入第一版分发。
