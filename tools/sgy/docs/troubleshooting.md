# sgy 排障

先运行：

```text
sgy --version
sgy doctor
sgy capabilities
```

`doctor` 输出 `sgy.doctor/v1`，逐项区分配置、workspace、engine、cache、YAML 和协议状态；它不会执行真实扫描。

## 安装问题

| 现象 | 检查与处理 |
| --- | --- |
| checksum mismatch | 确认 ZIP 与 `.sha256` 来自同一发布批次；不要重新生成 checksum 绕过失败 |
| target does not match host | 下载与 OS/架构一致的 target；不要强制安装交叉目标 |
| unexpected/unsafe ZIP member | 丢弃归档并从受控发布源重新取得；安装器不会部分提取 |
| 安装成功但找不到 `sgy` | 新开 Windows 终端，使用户 PATH 更新生效 |
| 升级失败 | 安装器应恢复旧 `current`；用 `Status`/`status` 和 `sgy --version` 验证，不手工删除 state |
| 卸载后目录仍存在 | 检查是否有未知用户文件；安装器只删除受管成员 |

## Engine 与执行问题

- `engine_not_found`：安装 ast-grep，或向 `sgy doctor --engine <path>` / `sgy exec --engine <path> -- ...` 传绝对可执行文件。
- `unexpected_version`：路径指向的可能不是 ast-grep；执行该文件的 `--version`，预期前缀为 `ast-grep `。
- 无匹配：缺省 Token-Safe 在 ast-grep 返回 code 1 且 stdout/stderr 均为空时输出空上下文 YAML并保留 code 1；lossless 不生成 YAML。其他非零状态结合 stderr 判断，不要一概视为 no-match。
- wrapper 120–127：检查 stderr；这一区间用于超时、转换、缓存、I/O、参数或协议边界错误。
- LSP/TTY：这两类通道不产生 YAML。若 stdout 出现包装内容，应停止使用并报告协议污染。

## 配置、输出与 cache

- 配置拒绝：执行 `sgy schema`，检查 `schema: sgy.config/v1`、scope、64 KiB 上限及未知字段。
- `_sgy.complete=false`：详情或文本被省略；使用 `_sgy.cache` 分页取回，不能声称可见结果完整。
- cache 权限：执行 `sgy doctor`；共享机器可临时使用 `--cache off`，但省略内容将不可恢复。
- cache 损坏/过期：`cache info/query/get` 会拒绝 hash、TTL 或状态异常；重新运行有界查询，不直接读取内部文件。
- YAML 太大：先用 `files` profile 或收窄目录/语言；不要把模型预算转成 ast-grep 扫描上限。

仍无法定位时，保留 `sgy --version`、`ast-grep --version`、目标平台、退出码和已脱敏 stderr；不要附带 cache 中的完整源码。
