# 查询后端冻结合同

本目录是统一源码查询网关分支的开发基线，只服务 `TSQG-002/003/060`。它不进入 Codex payload，也不替代 rg、fd 或 ast-grep 的原生帮助。

- [versions.json](versions.json) 固定已验证后端身份、平台和命令集合，只界定证据范围，不形成运行许可名单。
- [mode-matrix.json](mode-matrix.json) 给每个会改变输出通道、完整性或副作用边界的公开模式稳定 ID；普通筛选、遍历、匹配和展示 flag 作为 modifier family 保留原始 argv。
- `help/` 保存各精确版本主帮助与子命令帮助的 UTF-8 规范化快照；`help-manifest.json` 记录逐文件 SHA-256。
- `fixtures/` 与 `capture_native_oracle.py` 保存最小真实行为语料；生成的 `native-oracle.json` 记录原生退出、stdout/stderr 和结果身份，不定义包装后的预期格式。
- `verify_candidate.py --srcq <srcq.exe>` 核对每个 rg/fd 主模式的显式 `defaults` 分类不启动引擎，并通过 raw/artifact 逃生口重放七个原生 oracle；该入口只属于项目验证，不进入候选 skill 或 Codex payload。

“完整兼容”表示 rg/fd 普通入口在 backend 后、显式 query 与 AST 入口在各自 `--` 后的全部原生 argv 均可调用，并保留其查询、副作用、stdin/TTY、输出和退出语义。矩阵只决定包装能否结构化、是否必须落 artifact 或是否应原样透传；没有单独列出的 modifier 仍受对应版本原生帮助约束，不得因包装器未解析而拒绝。

扩展验证身份时必须重新采集帮助与原生 oracle，创建新的版本项和哈希；不得改写旧版本命令集合。未列出的可启动版本仍可执行，只是质量结论不外推到尚未验证的模式。ast-grep 0.44.1 新增 `outline`，0.41.1 与 0.42.0 没有该子命令，这是当前首个已确认的版本差异。
