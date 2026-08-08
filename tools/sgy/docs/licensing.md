# 许可证与第三方组件

sgy 由使用者选择 MIT 或 Apache-2.0：根目录 `LICENSE` 说明选择，完整正文分别位于 `LICENSE-MIT` 和 `LICENSE-APACHE`。`NOTICE` 随发布包分发。

每个 target 的 release 构建从 `cargo metadata --locked --filter-platform <target>` 计算 `sgy-cli` 的 normal/build 可达依赖，并生成：

- `sbom.spdx.json`：SPDX 2.3 package、版本、声明许可证和依赖关系；
- `THIRD_PARTY_LICENSES.txt`：每个第三方 package 的声明表达式、来源、实际随 crate 分发的 LICENSE/COPYING/UNLICENSE/NOTICE 文件映射及完整正文；相同正文按 SHA-256 去重。

打包器拒绝无许可证、无实际许可证文件或未经审查的表达式。当前 Windows release 图为 52 个第三方 package，许可证集合仅含 MIT、Apache-2.0、BSD-2/3-Clause、Unicode-3.0 与 Unlicense 的允许组合；`unicode-ident` 的 Unicode-3.0 附加文本已包含。未发现 GPL/AGPL/LGPL 或未知许可证。

ast-grep 是外部可执行依赖，不在 sgy 归档或 SBOM 的链接依赖图中；用户仍需遵守其独立许可证。漏洞审计与许可证审计是不同门禁：许可证允许不代表依赖无安全 advisory。
