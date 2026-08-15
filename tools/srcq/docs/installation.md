# 安装、升级与卸载

## 前置条件

1. 从同一发布批次取得 Windows x86_64 ZIP、对应 `.sha256` 和安装脚本。
2. 单独安装精确受支持的 ast-grep；第一版推荐固定 `0.42.0`，已验证版本还包括 `0.41.1` 与 `0.44.1`。
3. 安装后运行 `srcq doctor`；srcq 不下载 ast-grep，也不安装 Node/Python 或语言运行时。

## Windows

```powershell
.\scripts\install-srcq.ps1 Install -Archive .\dist\srcq-<version>-x86_64-pc-windows-msvc.zip
.\scripts\install-srcq.ps1 Status
.\scripts\install-srcq.ps1 Uninstall
```

`Status` 不只读取状态文件；它还复核 manifest 与安装状态身份、全部受管文件的大小和 SHA-256、实际 `srcq --version`，以及由安装器管理的 PATH 项是否恰好出现一次。缺失、篡改或 PATH 漂移会返回 `ready=false`、原因和恢复动作，并以非零退出；重新使用同一受验证归档执行 `Install` 可以修复受管文件或缺失的 PATH 项。

默认安装到 `%LOCALAPPDATA%\Programs\srcq\current`，并把该目录添加到用户 PATH。PATH 修改只对新启动的终端生效。重复安装相同包不产生变化；升级使用 staging、旧目录备份和失败恢复，不从源码或 `target/` 安装。

测试或便携环境可使用 `-InstallRoot`，并以 `-PathBackend File -PathValueFile <file>` 验证 PATH 逻辑；`-PathBackend None` 禁止 PATH 修改。

升级使用同一 `Install` 命令指向新版本归档。成功前旧 `current` 会保留为临时 rollback；状态提交失败时恢复旧二进制、state 和 PATH。升级后重新打开终端并执行：

```powershell
srcq --version
srcq doctor
```

## 数据保留

- 安装、重复安装和升级不会写入用户配置。
- 默认卸载保留配置和 cache。
- 只有卸载时显式传入 `-RemoveCache` 才删除 srcq 的 cache v1。
- 安装目录是组件管理目录；卸载仍只删除安装状态中声明的成员，发现未知文件时保留文件和目录。
- PATH 回滚只移除由安装器新增的那一个条目/链接；安装后由用户或其他工具增加的 PATH 内容保持不变。

所有安装都先验证归档 SHA-256、精确成员集合、manifest target/version、包内文件 hash 和二进制 `--version`。目标架构不匹配、额外 ZIP 成员或路径穿越都会在写入当前版本前拒绝。

Windows PowerShell 5.1 原生生命周期已有自动化证据；平台声明以 [兼容边界](compatibility.md) 和 [发布门禁](release-checklist.md) 为准。
