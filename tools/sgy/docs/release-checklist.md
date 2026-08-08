# sgy 第一版发布门禁

本清单用于决定某个目标是否可以进入正式分发。v0.1 正式支持范围是 Windows x86_64 MSVC 与 Linux x86_64 GNU，这两个目标必须分别独立通过。构建能力矩阵中的 macOS 目标属于延期平台；缺少原生证据时不得发布，也不能用其他平台或交叉编译结果代替。

## 1. 来源与版本

- [ ] 版本与 `Cargo.toml`、`sgy --version`、manifest 和归档名一致。
- [ ] Git 工作区使用真实 commit；没有 Git 元数据的来源运行 `scripts/new-source-snapshot.ps1`，将 `sha256:<digest>` 作为 `SourceRevision`，并随 release 保存完整 snapshot manifest。
- [ ] source snapshot 在最终源码/文档变更后生成；`target/`、`dist/` 和 `.git/` 不参与 digest。
- [ ] `Cargo.lock`、Rust 1.85.0 和 `release-targets.json` 已固定。

## 2. 每目标原生门禁

- [ ] 在与目标匹配的原生 runner 上 clean build；`sgy --version` 可启动。
- [ ] archive checksum、精确成员集合、manifest 文件 hash、target 和 SBOM 可验证。
- [ ] 安装 → `doctor` → 核心 `exec`/cache/process smoke → 同版幂等安装 → 升级/失败回滚 → 卸载通过。
- [ ] ast-grep 固定版 0.42.0 可用；兼容声明中的其他版本只按已有精确矩阵声明。
- [ ] Unix 目标验证可执行位、真实 symlink、权限、配置/cache 路径和 shell argv；Windows 验证 PowerShell 5.1 与 PATH 回滚。
- [ ] TTY/LSP 只在原生协议证据存在时签署，不能从普通 batch smoke 推断。

## 3. 共存与安全

- [ ] `sgy` 不安装或覆盖 `ast-grep`/`sg`，不修改 ast-grep 自身安装。
- [ ] sgy 配置/cache/安装根与 `ast-grep-token-safe`、ast-mcp、vscode-lsp-mcp 和其他 SymbolStructureWorkflow 组件无路径冲突。
- [ ] 安装、失败回滚和卸载前后，其他组件与用户配置/cache 的 hash 不变。
- [ ] 卸载只删除 install state 声明的受管文件和自身 PATH 条目；未知文件、预存 PATH 条目与并发 PATH 编辑保留。
- [ ] checksum 错误、路径穿越、额外成员、target 不匹配、manifest hash 错误和篡改 state 均被拒绝。

## 4. 质量、许可与漏洞

- [ ] `cargo fmt --all -- --check`、严格 Clippy、workspace tests 通过。
- [ ] 构建能力矩阵四目标的 normal/build 可达依赖许可证审计通过，包内第三方许可证全文与 SBOM 一致。
- [ ] 使用当前 RustSec advisory-db 对最终 `Cargo.lock` 审计；高风险发现必须修复或记录明确的发布阻断处置。
- [ ] 文档链接、命令示例、机器绝对路径和内部验证标识检查通过。

## 5. 发布记录与回滚

- [ ] release record 列出 source revision、每个已发布目标的 archive/checksum、原生证据和已知限制。
- [ ] 未通过原生门禁的目标明确标记为“未发布”，不得生成看似正式的 release archive。
- [ ] 回滚使用上一份已验证 archive 重新执行安装器；配置/cache 默认保留。
- [ ] 若安装状态损坏，先保存诊断证据，再按安全文档处理；不得删除源码、Skill、ast-grep 或其他组件作为清理手段。

## 发布判定

只有所有通用项与某目标的原生项均有证据时，该目标才可发布。v0.1 只有 Windows x86_64 MSVC 与 Linux x86_64 GNU 两个正式支持目标；二者门禁全部通过、延期平台明确标为未发布且不存在看似正式的 artifact 时，v0.1 可以签署完成。macOS 后续版本仍必须分别补齐原生门禁，不能继承 v0.1 的其他平台结论。
