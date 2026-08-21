# srcq Windows 发布门禁

本清单用于决定 Windows x86_64 MSVC 候选是否可以进入正式分发；其他平台不属于维护、验证或延期范围。

## 1. 来源与版本

- [ ] 版本与 `Cargo.toml`、`srcq --version`、manifest 和归档名一致。
- [ ] Git 工作区在 release record 中记录真实 commit；进入 skill 运行时时使用 `scripts/new-source-snapshot.ps1` 生成的 `sha256:<digest>` 作为不可变 `SourceRevision`，并随 release 保存完整 snapshot manifest。
- [ ] source snapshot 在最终源码/文档变更后生成；`target/`、`dist/` 和 `.git/` 不参与 digest；没有 Git 元数据时只省略 commit，不降低快照要求。
- [ ] `Cargo.lock`、Rust 1.85.0 和 `release-targets.json` 已固定。

## 2. Windows 原生门禁

- [ ] 在 Windows x86_64 原生 runner 上 clean build；`srcq --version` 可启动。
- [ ] archive checksum、精确成员集合、manifest 文件 hash、target 和 SBOM 可验证。
- [ ] GitHub Release 同批上传 archive、`.sha256`、外部 manifest、外部 SBOM、`install-srcq.ps1` 与 `install-srcq-release.ps1`；私有仓库中以有读取权限的 `gh` 身份完成一次真实下载。
- [ ] 安装 → `doctor` → `query scc doctor` → 核心 AST/rg/fd/scc、cache/process smoke → 同版幂等安装 → 升级/失败回滚 → 卸载通过。
- [ ] ast-grep 固定版 0.42.0 可用；兼容声明中的其他版本只按已有精确矩阵声明。
- [ ] scc 3.7.0 的 summary/languages/files/hotspots、json2、分页、协议回退、错误退出与输出副作用边界通过；缺失 scc 时发布前置检查失败而不是静默降级。
- [ ] 验证 PowerShell 5.1、用户 PATH、配置/cache 路径和失败回滚。
- [ ] TTY/LSP 只在原生协议证据存在时签署，不能从普通 batch smoke 推断。

## 3. 共存与安全

- [ ] `srcq` 不安装或覆盖 `ast-grep`/`sg`、scc 或 hyperfine，不修改这些工具自身安装。
- [ ] srcq 配置/cache/安装根与 `source-query`、vscode-lsp-mcp 和其他语义编辑组件无路径冲突。
- [ ] 安装、失败回滚和卸载前后，其他组件与用户配置/cache 的 hash 不变。
- [ ] 卸载只删除 install state 声明的受管文件和自身 PATH 条目；未知文件、预存 PATH 条目与并发 PATH 编辑保留。
- [ ] checksum 错误、路径穿越、额外成员、target 不匹配、manifest hash 错误和篡改 state 均被拒绝。

## 4. 质量、许可与漏洞

- [ ] `cargo fmt --all -- --check`、严格 Clippy、workspace tests 通过。
- [ ] Windows target 的 normal/build 可达依赖许可证审计通过，包内第三方许可证使用 `SRCQ THIRD-PARTY LICENSES` 产品标题，全文与 SBOM 一致。
- [ ] 使用当前 RustSec advisory-db 对最终 `Cargo.lock` 审计；高风险发现必须修复或记录明确的发布阻断处置。
- [ ] 文档链接、命令示例、机器绝对路径和内部验证标识检查通过。

## 5. 发布记录与回滚

- [ ] release record 列出 source revision、Windows archive/checksum、原生证据和已知限制。
- [ ] 回滚使用上一份已验证 archive 重新执行安装器；配置/cache 默认保留。
- [ ] 若安装状态损坏，先保存诊断证据，再按安全文档处理；不得删除源码、Skill、ast-grep 或其他组件作为清理手段。

## 发布判定

只有所有通用项与 Windows 原生项均有证据时，Windows x86_64 MSVC 候选才可发布。
