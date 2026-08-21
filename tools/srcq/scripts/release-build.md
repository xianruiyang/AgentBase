# 可复现发布构建

发布入口：

```powershell
.\scripts\build-release.ps1 -Clean -SourceRevision <commit> -SourceDateEpoch <unix-seconds>
```

脚本从 `Cargo.toml`/Cargo metadata 取得默认版本，通过 `SRCQ_BUILD_VERSION` 注入二进制，并在原生目标上验证 `srcq --version`。固定 Rust 版本由 `rust-toolchain.toml` 提供。

唯一目标见 `release-targets.json`。构建必须在 Windows x86_64 原生 runner 上执行；其他平台不属于维护或发布范围。

## 目录边界

- 源码与正式脚本：workspace 内，不能由构建覆盖。
- 临时编译、目标过滤 metadata：`target/release-build/<target>/`；`-Clean`/`--clean` 只清理该受限目录。
- 正式候选产物：`dist/srcq-<version>-<target>.*`。

构建使用源码路径 remap 和 MSVC `/Brepro`，避免 PE 链接时间戳破坏相同输入的字节复现。

每个目标生成：

- 确定性 stored ZIP；内部固定文件顺序、时间戳和权限位；
- `<archive>.sha256`；
- 外部 release manifest；
- SPDX 2.3 JSON SBOM。

ZIP 内含 `srcq.exe`、README、项目双许可证、NOTICE、target-filtered 第三方完整许可证、manifest 和 SBOM。二进制本身不依赖 Node 或 Python；运行 ast-grep 功能时仍需可发现的 `ast-grep` 可执行文件。

发布到 GitHub 时还要把 `install-srcq.ps1` 和 `install-srcq-release.ps1` 作为同一 Release 的独立资产上传。下载入口不复制安装逻辑：它只通过已认证的 GitHub CLI 下载精确 tag 的归档、校验和与底层安装器。
