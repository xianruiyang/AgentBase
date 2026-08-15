# Real ast-grep integration gate

本包使用与正式 `srcq` 相同的 `crates/srcq-cli/src/main.rs` 构建测试 driver，并在隔离临时目录中
对照真实 ast-grep。默认工作区测试只编译并标记这些用例为 ignored；真实门禁显式运行：

```powershell
$env:SRCQ_AST_GREP = '<absolute-path-to-ast-grep-binary>'
$env:SRCQ_AST_GREP_EXPECTED_VERSION = 'ast-grep 0.42.0'
cargo test -p srcq-integration-tests --test real_workflow -- --ignored --test-threads=1
```

覆盖范围：

- run/scan 原生 JSONL 与 lossless YAML value 等价；
- Token-Safe 上下文限量不改变原生执行数，完整结果可从隔离 cache 取回并交给 processor；
- run/scan `-U` 的修改文件集合、SHA-256 和最终字节与原生一致；
- no-match、路径错误、rule 错误、engine probe timeout 与 real-process cancellation 可区分；
- 每项测试结束前移除 cache，并验证正式 fixture 未被修改。

TTY、LSP 和跨平台信号属于 P5-003；大结果、并发、backpressure 和 cache GC 属于 P5-004。
