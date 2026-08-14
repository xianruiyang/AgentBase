# Codex QQ 通知开发入口

QQ 完成提醒与主动直发的运行时唯一真源位于 `../../skills/codex-qq-hook/`。本目录不保留旧兼容脚本副本，避免与 Skill 内的通知、开关和安装脚本形成双重实现。

- `../../skills/codex-qq-hook/scripts/`：正式 Python 与 PowerShell 实现。
- `../../skills/codex-qq-hook/templates/`：正式配置模板。
- `qq_event_capture.go`：仅用于 Webhook 验证或事件捕获的辅助程序，不是普通 Codex 完成提醒的主路径。

PowerShell 和 Python 修改直接在 Skill 真源中开发。QQ 开关、主动直发与独立安装器分别运行：

```powershell
& '.\skills\codex-qq-hook\tests\test_qq_hook_switch.ps1'
& '.\skills\codex-qq-hook\tests\test_send_qq_message.ps1'
& '.\skills\codex-qq-hook\tests\test_install_global_qq_hook.ps1'
```

主动直发测试只使用 `-DryRun`，不得把真实 QQ 网络发送作为常规回归步骤。

Go 辅助程序只依赖标准库，可用以下命令做测试和编译检查：

```powershell
go test '.\development\codex-qq-hook\qq_event_capture.go' '.\development\codex-qq-hook\qq_event_capture_test.go'
```

辅助服务默认只监听 `127.0.0.1:8080`，请求体上限为 1 MiB，并配置 HTTP 读写超时；只有明确需要接受非本机直连时才通过 `-addr` 改为其他监听地址。

`QQ_BOT_APP_SECRET` 只通过环境变量提供，不得写入仓库、模板、日志或测试夹具。
