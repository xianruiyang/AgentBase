# srcq 命令兼容边界

正式命令、包和安装身份均为 `srcq`。既有 AST YAML、cache 与 process 文档中的 `_sgy` 字段及 `sgy.*` schema 保持不变，以保证迁移前产物可继续验证和读取；不得据此提供 `sgy.exe` 别名或旧安装 fallback。

## 参数优先级

srcq 的基本契约是“显式原生 argv 优先，缺省时做安全补全”：

- `--` 后用户 token 的值、顺序和重复项不改写。
- 缺省 batch `run`/`scan` 只补 `--json=stream`，不补语言、pattern、rule、glob、结果上限或写入参数。
- 用户显式 `--json`、`--format`、`--files-with-matches`、交互模式等输出选项会抑制缺省 JSON 注入。
- `--no-native-defaults` 禁止缺省补全；`--strict` 在需要 wrapper 保守失败时使用。
- `srcq defaults ... -- <argv>` 可在不启动引擎的情况下检查最终设置和 effective argv。

## 顶层命令

| ast-grep 命令/模式 | srcq 行为 |
| --- | --- |
| batch `run` | 结构化结果转为所选 profile；model 写定位与源码，machine 保留 YAML；files/text/debug 走有界 adapter |
| batch `scan` | finding、SARIF、files/text/GitHub report 按显式格式转为 model 证据、machine YAML 或有界报告；Token-Safe SARIF 提取真实 findings |
| rewrite/fix 预览与 `-U` | 原生执行/写入集合和退出码保持；model 追加 `@write`，machine 保留完整写入审计 |
| `test`、`new`、help/version | model 输出有界 UTF-8 正文，machine 包装为 `sgy.raw/v1`；文件副作用保持 |
| `completions`、二进制输出 | 需要显式 `--artifact-out`；model 只返回路径，machine 返回 manifest |
| interactive | 继承 TTY，不注入 JSON，不转换交互字节 |
| `lsp` | stdin/stdout 字节透传；YAML、日志和 telemetry 不进入协议 stdout |
| 未知未来命令 | raw fallback，不猜测为结构化结果，不注入 batch JSON |

显式 native JSON 支持 compact、pretty 和 stream；lossless YAML 以 JSON value 等价为目标并保留未知字段。默认 model 不承诺机器 round-trip；显式文本或特殊报告格式不会被伪装成 match records。

## 通道和退出状态

- stdout：model 证据、machine YAML/JSON、显式 artifact 结果，或 LSP/TTY passthrough。
- stderr：原生 stderr 与 wrapper 诊断，除非显式写入 `--stderr-yaml` sidecar。
- 原生退出码保持。wrapper 自身失败使用 120–127；不要把“非零但已有有效诊断 YAML”误判为无输出。
- Token-Safe no-match（code 1、空 stdout/stderr）在 model 保持空 stdout，在 machine 返回空上下文并保留 code 1；lossless 不制造原生不存在的 JSON value。
- stdin/EOF 透传给原生命令；`process` 未指定 input/cache 时则从 stdin 读取。

## rg/fd/scc 网关

普通 `srcq rg|fd|scc` 将 backend 后的原生 argv 保持为独立参数数组。rg/fd 的结构化、NUL、文本、二进制和副作用模式按[查询网关](query-gateway.md)分类；scc 常规汇总注入 JSON，`--by-file` 形成逐文件记录，json2 从 `languageSummary` 读取语言事实，显式非 JSON 格式保持有界文本，输出文件模式只透传一次。machine 使用稳定的 srcq query schema，lossless/raw 保留原生协议；解析失败、非零退出或未知字段不得伪装成完整空结果。

## 版本与平台声明

当前唯一验证基线为 ast-grep 0.44.1，普通 AST、透传、协议与 `srcq symbol` outline 关系能力均只在该版本声明；不维护较早版本的现行兼容矩阵。scc backend 当前精确验证 `scc 3.7.0`。未知命令继续使用 raw fallback，不能据此宣称其全部语义已认证。

唯一维护平台是 Windows x86_64 MSVC，现有证据覆盖 ast-grep 0.44.1 的真实 run/scan/rewrite/cache、TTY/LSP、确定性 release 和 PowerShell 5.1 安装生命周期。其他平台不进入构建、测试、安装或发布范围。
