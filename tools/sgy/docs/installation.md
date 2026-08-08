# 安装、升级与卸载

## 前置条件

1. 从同一发布批次取得目标平台 ZIP、对应 `.sha256` 和安装脚本。
2. 单独安装精确受支持的 ast-grep；第一版推荐固定 `0.42.0`，已验证版本还包括 `0.41.1` 与 `0.44.1`。
3. 安装后运行 `sgy doctor`；sgy 不下载 ast-grep，也不安装 Node/Python 或语言运行时。

## Windows

```powershell
.\scripts\install-sgy.ps1 Install -Archive .\dist\sgy-<version>-x86_64-pc-windows-msvc.zip
.\scripts\install-sgy.ps1 Status
.\scripts\install-sgy.ps1 Uninstall
```

默认安装到 `%LOCALAPPDATA%\Programs\sgy\current`，并把该目录添加到用户 PATH。PATH 修改只对新启动的终端生效。重复安装相同包不产生变化；升级使用 staging、旧目录备份和失败恢复，不从源码或 `target/` 安装。

测试或便携环境可使用 `-InstallRoot`，并以 `-PathBackend File -PathValueFile <file>` 验证 PATH 逻辑；`-PathBackend None` 禁止 PATH 修改。

升级使用同一 `Install` 命令指向新版本归档。成功前旧 `current` 会保留为临时 rollback；状态提交失败时恢复旧二进制、state 和 PATH。升级后重新打开终端并执行：

```powershell
sgy --version
sgy doctor
```

## Linux/macOS 便携安装

```sh
./scripts/install-sgy.sh install --archive ./dist/sgy-<version>-<target>.zip
./scripts/install-sgy.sh status
./scripts/install-sgy.sh uninstall
```

默认安装到 `${XDG_DATA_HOME:-$HOME/.local/share}/sgy/current`，并在 `$HOME/.local/bin/sgy` 创建受管符号链接。脚本不修改 shell profile；若 `$HOME/.local/bin` 尚未在 PATH，应由用户按 shell 约定加入。可用 `--path-dir` 指定已有 PATH 目录，或用 `--no-path` 禁止创建链接。

Unix 安装需要系统自带/包管理器提供的 `unzip`，以及 `sha256sum` 或 `shasum`；不需要 Node、Python 或 jq。

升级仍执行 `install --archive <new.zip>`。首次使用前确保脚本可执行，并检查链接目录已在 PATH：

```sh
chmod +x ./scripts/install-sgy.sh
sgy --version
sgy doctor
```

## 数据保留

- 安装、重复安装和升级不会写入用户配置。
- 默认卸载保留配置和 cache。
- 只有卸载时显式传入 `-RemoveCache`（Windows）或 `--remove-cache`（Unix）才删除 sgy 的 cache v1。
- 安装目录是组件管理目录；卸载仍只删除安装状态中声明的成员，发现未知文件时保留文件和目录。
- PATH 回滚只移除由安装器新增的那一个条目/链接；安装后由用户或其他工具增加的 PATH 内容保持不变。

所有安装都先验证归档 SHA-256、精确成员集合、manifest target/version、包内文件 hash 和二进制 `--version`。目标架构不匹配、额外 ZIP 成员或路径穿越都会在写入当前版本前拒绝。

Windows PowerShell 5.1 与 Linux x86_64 GNU 原生生命周期已有自动化证据。macOS 原生安装 smoke 尚未完成，第一版不发布 macOS 包；平台声明以 [兼容边界](compatibility.md) 和 [发布门禁](release-checklist.md) 为准。
