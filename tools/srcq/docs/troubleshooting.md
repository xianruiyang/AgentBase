# srcq 排障

先检查当前失败入口；只有 engine、配置或协议原因仍不清楚时运行：

```text
srcq --version
srcq doctor
srcq query scc doctor
```

`doctor` 正常只输出 `ok`，失败只输出失败项和恢复入口；需要逐项区分配置、workspace、engine、cache、YAML 和协议状态时运行 `srcq doctor --output machine`。`capabilities` 只在能力合同本身未知时使用。它们都不会执行真实扫描。

## 安装问题

| 现象 | 检查与处理 |
| --- | --- |
| checksum mismatch | 确认 ZIP 与 `.sha256` 来自同一发布批次；不要重新生成 checksum 绕过失败 |
| target does not match host | 下载与 OS/架构一致的 target；不要强制安装交叉目标 |
| unexpected/unsafe ZIP member | 丢弃归档并从受控发布源重新取得；安装器不会部分提取 |
| 安装成功但找不到 `srcq` | 新开 Windows 终端，使用户 PATH 更新生效 |
| 升级失败 | 安装器应恢复旧 `current`；用 `Status`/`status` 和 `srcq --version` 验证，不手工删除 state |
| 卸载后目录仍存在 | 检查是否有未知用户文件；安装器只删除受管成员 |

## Engine 与执行问题

- `engine_not_found`：安装 ast-grep，或向 `srcq doctor --engine <path>` / `srcq exec --engine <path> -- ...` 传绝对可执行文件。
- scc backend 不可用：确认独立安装的 `scc.exe` 已进入当前进程 PATH，或向 `srcq query scc doctor --engine <path>` 和后续控制命令传同一绝对路径。刚由 bootstrap 修改 PATH 时必须重启 Codex 桌面宿主。
- scc 投影失败：保留原生退出码和有界诊断；model 的协议回退来自同一次捕获，不要无变化重跑。确需原始字段时使用 lossless/raw/artifact，不把 COCOMO 或复杂度估算当作缺陷结论。
- `unexpected_version`：路径指向的可能不是 ast-grep；执行该文件的 `--version`，预期前缀为 `ast-grep `。
- 无匹配：缺省 model 在 ast-grep 返回 code 1 且 stdout/stderr 均为空时保持空 stdout 和 code 1；machine Token-Safe 返回显式空集合；lossless 不生成 YAML。其他非零状态结合 stderr 判断，不要一概视为 no-match。
- wrapper 120–127：检查 stderr；这一区间用于超时、转换、缓存、I/O、参数或协议边界错误。
- LSP/TTY：这两类通道不产生 YAML。若 stdout 出现包装内容，应停止使用并报告协议污染。

## 配置、输出与 cache

- 配置拒绝：执行 `srcq schema`，检查 `schema: sgy.config/v1`、scope、64 KiB 上限及未知字段。
- `@more`：query 路径原样传回自带 snapshot 身份的 after，cache 路径沿 cache/after 续读；`@cut`：当前显示有不可续读省略或截断，收窄查询、提高对应预算或改用 machine/artifact。machine 的 `_sgy.complete=false` 仍按 `_sgy.cache` 取回。
- cache 权限：执行 `srcq doctor`；共享机器可临时使用 `--cache off`，但省略内容将不可恢复。
- cache 损坏/过期：`cache info/query/get` 会拒绝 hash、TTL 或状态异常；重新运行有界查询，不直接读取内部文件。
- YAML 太大：先用 `files` profile 或收窄目录/语言；不要把模型预算转成 ast-grep 扫描上限。

仍无法定位时，保留 `srcq --version`、`ast-grep --version`、目标平台、退出码和已脱敏 stderr；不要附带 cache 中的完整源码。
