# PTY, LSP, and artifact protocol gate

真实平台门禁需要 ast-grep 二进制和对应终端环境：

```powershell
$env:SGY_AST_GREP = '<absolute-path-to-ast-grep-binary>'
$env:SGY_AST_GREP_EXPECTED_VERSION = 'ast-grep 0.42.0'
cargo test -p sgy-protocol-tests --test real_protocol -- --ignored --test-threads=1
```

测试使用 `portable-pty` 的本机 backend：Windows 为 ConPTY，Unix 为 PTY。它不会把 Windows
结果标记为 Unix 通过。LSP 测试对直连与 wrapper 使用完全相同的输入字节并比较 stdout/stderr
字节和 SHA-256；completion 测试比较 artifact 与原生 stdout，并由目标 shell 实际加载。
Unix 的 Ctrl+C 门禁向 PTY 会话前台进程组发送真实 `SIGINT`；Windows 门禁在独立最小化
Console 中发送 `CTRL_C_EVENT`。不能用向 raw-mode TUI 写入字节 `0x03` 代替平台信号证据。

默认 `cargo ci-test` 只编译这些真实平台用例并保持 ignored。跨平台结果必须由目标操作系统运行
上述命令产生，不能由交叉编译替代。
