# srcq fuzz targets

需要 `cargo-fuzz` 和 Rust nightly：

```powershell
cargo +nightly fuzz list
cargo +nightly fuzz run json_yaml -- -max_total_time=60 -max_len=65536
```

Windows 必须让与链接器匹配的 MSVC ASan 运行库目录位于 `PATH`。普通 PowerShell 若出现
`STATUS_DLL_NOT_FOUND` 或 `STATUS_ENTRYPOINT_NOT_FOUND`，请改用 Visual Studio Developer
PowerShell，确保加载的是当前 MSVC `Hostx64\x64` 下的
`clang_rt.asan_dynamic-x86_64.dll`，不要混用独立 LLVM 的同名 DLL。

Targets：

- `argv_defaults`：`--` 边界、原生 token 保持和 defaults 注入不变量。
- `json_yaml`：任意原生字节、JSON duplicate scanner 与 JSON→安全 YAML 等价。
- `safe_yaml`：安全 YAML parser、深度/节点/文档限制和重新编码等价。
- `config_schema_paths`：配置安全解析、完整配置 schema 和字段路径 parser。
- `budget_cache`：Unicode Token-Safe 预算、确定性聚合和 cache ID 验证。

固定 seeds 位于 `corpus/<target>/`。若发现 crash，cargo-fuzz 会把最小样本写入 `artifacts/<target>/`；保留该文件并用以下命令复现：

```powershell
cargo +nightly fuzz run <target> artifacts/<target>/<hash>
```

常规 CI 运行 `tests/unit` 中对应 proptest；不要求 CI 每次安装 nightly。
