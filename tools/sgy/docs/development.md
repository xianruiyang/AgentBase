# 开发与发布

## 环境

- Rust 1.85.0，最小 profile；`rust-toolchain.toml` 固定版本及 rustfmt/clippy。
- ast-grep 0.42.0 用于固定版真实集成；多版本矩阵还使用 0.41.1 与 0.44.1。
- Node/Python 不是构建或运行依赖。

## Workspace

```text
crates/sgy-core/       协议无关核心、进程、codec、profile、cache、processor
crates/sgy-cli/        CLI、adapter、doctor 与命令入口
tools/sgy-release/     确定性 ZIP、manifest、SBOM、第三方许可证
tests/                 契约、集成、协议与压力测试
scripts/               release、安装和安装生命周期测试
```

常规门禁：

```powershell
cargo ci-build
cargo ci-test
cargo lint
cargo fmt-check
```

真实 ast-grep ignored 测试需要设置 `SGY_AST_GREP` 和 `SGY_AST_GREP_EXPECTED_VERSION`，并按 package/版本顺序运行；不要并行执行共享 fixture 的全部 ignored 测试。

`cargo lint` 与 `cargo ci-test` 都包含 `--all-targets --all-features`；不要用缺少 `test-helper` feature 的普通 workspace test 替代正式门禁。真实引擎测试还需要显式传入 `-- --ignored`。

## Release

```powershell
.\scripts\build-release.ps1 -Clean -SourceRevision <commit> -SourceDateEpoch <unix-seconds>
```

唯一目标见 `scripts/release-targets.json`。正式构建必须在 Windows x86_64 原生环境传入真实 commit 和对应时间戳，并验证 ZIP checksum、manifest version/target、SPDX、第三方许可证以及原生 smoke。

增加或升级依赖时必须重新生成并审查：

1. Cargo.lock 与 Windows target-filtered SBOM；
2. `THIRD_PARTY_LICENSES.txt` 中 package/文件映射和完整文本；
3. 许可证表达式 allowlist；
4. `cargo audit` 及高风险 advisory 处置；
5. 两次 clean 构建的归档哈希。

发布生成物只进入 `dist/`，临时对象只进入 `target/release-build/<target>/`。不要把本机路径、临时 fixture 或验证用 source revision 写入正式文档/manifest。

正式发布逐项执行 [release checklist](release-checklist.md)。源码目录没有 Git metadata 时，先运行：

```powershell
.\scripts\new-source-snapshot.ps1
```

将输出的 `sha256:<digest>` 传给构建脚本的 `-SourceRevision`，并保留 `dist/sgy-source-snapshot.json`。后续任何源码或文档变化都会使该 revision 失效，必须重新生成并重建全部候选包。
