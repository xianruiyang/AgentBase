# 可复现发布构建

发布入口：

```powershell
.\scripts\build-release.ps1 -Clean -SourceRevision <commit> -SourceDateEpoch <unix-seconds>
```

```sh
./scripts/build-release.sh --clean --source-revision <commit> --source-date-epoch <unix-seconds>
```

脚本从 `Cargo.toml`/Cargo metadata 取得默认版本，通过 `SGY_BUILD_VERSION` 注入二进制，并在原生目标上验证 `sgy --version`。固定 Rust 版本由 `rust-toolchain.toml` 提供。

目标矩阵见 `release-targets.json`。每个目标必须在相同操作系统/架构的原生 runner 上执行；交叉 `cargo check` 只能作为源码兼容证据，不能替代原生链接、启动和协议 smoke。

## 目录边界

- 源码与正式脚本：workspace 内，不能由构建覆盖。
- 临时编译、目标过滤 metadata：`target/release-build/<target>/`；`-Clean`/`--clean` 只清理该受限目录。
- 正式候选产物：`dist/sgy-<version>-<target>.*`。

构建统一使用源码路径 remap；MSVC 目标额外传递 `/Brepro`，避免 PE 链接时间戳破坏相同输入的字节复现。

每个目标生成：

- 确定性 stored ZIP；内部固定文件顺序、时间戳和权限位；
- `<archive>.sha256`；
- 外部 release manifest；
- SPDX 2.3 JSON SBOM。

ZIP 内含 `sgy`/`sgy.exe`、README、项目双许可证、NOTICE、target-filtered 第三方完整许可证、manifest 和 SBOM。二进制本身不依赖 Node 或 Python；运行 ast-grep 功能时仍需可发现的 `ast-grep` 可执行文件。
