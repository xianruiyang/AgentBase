# sgy 安全边界

## sgy 提供什么

- 使用参数数组启动 ast-grep，不拼接 shell command；`--` 后的 token 不做二次 shell 解析。
- 对 JSON/JSONL 做确定性解析，并输出无 tag、anchor、alias、merge key 或重复键的安全 YAML。
- `process` 限制输入字节、文档数、记录数和嵌套深度；字段选择、过滤与分组不执行代码。
- 显式文件输出先写临时文件，再原子提交；失败时不把半成品冒充成功结果。
- cache ID、root、hash、TTL、配额和 active lease 都在服务端逻辑中校验。
- LSP stdout 逐字节透传，TTY 继承终端；telemetry/sidecar 不混入协议 stdout。

## sgy 不是什么

sgy 不是 sandbox、权限系统或事务引擎。它会在用户授权的 cwd 中以当前用户权限运行 ast-grep，并原样转发搜索、ignore、follow、rewrite、`-U` 等原生语义。显式 `--engine`、`--cwd`、输出路径和原生参数都属于调用者授权范围。

因此必须遵守：

1. 只在已确认的 workspace、语言、目录和 glob 上运行。
2. rewrite 首次调用不传 `-U`；先预览匹配、replacement 和受影响文件，再显式应用。
3. 不把模型可见的 `shown` 当作实际写入数；上下文预算从不限制 ast-grep 写入集合。
4. 应用后检查 diff、重跑旧 pattern，并执行 formatter、lint/typecheck 和定向测试。
5. 不信任仓库内 `.sgy.yml` 扩大权限；项目配置本身也禁止 engine、cwd、cache 和输出路径。

## 配置和路径

- 显式 CLI 参数优先于项目/用户配置；项目 `.sgy.yml` 只控制 profile、缺省 JSON 和上下文字段/预算。
- 用户配置可设置 engine、cwd 和 cache，因为它位于用户配置目录，不受仓库内容控制。
- cache 默认位于系统 cache 目录并拒绝落在 workspace 内；项目目录不会被静默写入 cache。
- `--yaml-out`、`--artifact-out`、`--stderr-yaml`、`--meta-out` 只在用户显式指定时写入；调用前自行确认目标路径。

## 完整性与信息泄漏

- `lossless` 保留原生完整字段，适合机器处理，但不应默认进入模型上下文。
- `token-safe` 的 `_sgy.complete=false`、`omitted` 和 `_sgy_text_truncated` 是完整性信号；不得省略这些信号后声称结果完整。
- `cache auto/on` 可能保存完整原生输出；见 [缓存与取回](cache.md) 的清理和隐私要求。
- stderr 可能包含原生路径、rule 或诊断；只有确有需要时才把 `--stderr-yaml` sidecar 提供给模型。

## 发布与安装供应链

- 安装器在提取前验证 `.sha256`，并拒绝绝对路径、`..`、重复/额外成员和目标架构不匹配。
- 提取后逐项验证 manifest 的大小与 SHA-256，再执行包内 `sgy --version`；通过后才替换 `current`。
- release archive 包含项目 LICENSE/NOTICE、target-filtered `THIRD_PARTY_LICENSES.txt` 和 SPDX 2.3 SBOM。
- 升级失败恢复旧目录、state 和 PATH。安装 state 的受管成员集合也要验证，不能通过篡改 state 扩大卸载范围。
- checksum 证明完整性，不提供发布者身份认证；正式分发仍应通过受控发布渠道，并在 release checklist 中记录来源 commit 与 checksum。
