# 查询后端冻结合同

本目录是统一源码查询网关分支的开发基线，只服务 `TSQG-002/003/060`。它不进入 Codex payload，也不替代 rg、fd 或 ast-grep 的原生帮助。

- [versions.json](versions.json) 固定正式支持的精确版本、平台和命令集合。
- [mode-matrix.json](mode-matrix.json) 给每个会改变输出通道、完整性或副作用边界的公开模式稳定 ID；普通筛选、遍历、匹配和展示 flag 作为 modifier family 保留原始 argv。
- `help/` 保存各精确版本主帮助与子命令帮助的 UTF-8 规范化快照；`help-manifest.json` 记录逐文件 SHA-256。
- `fixtures/` 与 `capture-native-oracle.ps1` 保存最小真实行为语料；生成的 `native-oracle.json` 记录原生退出、stdout/stderr 和结果身份，不定义包装后的预期格式。

“完整兼容”表示 `--` 后全部原生 argv 均可调用并保留其查询、副作用、stdin/TTY、输出和退出语义。矩阵只决定包装能否结构化、是否必须落 artifact 或是否应原样透传；没有单独列出的 modifier 仍受对应版本原生帮助约束，不得因包装器未解析而拒绝。

更新版本时必须重新采集帮助与原生 oracle，创建新的版本项和哈希；不得改写旧版本命令集合。ast-grep 0.44.1 新增 `outline`，0.41.1 与 0.42.0 没有该子命令，这是当前首个已确认的版本差异。
