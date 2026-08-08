# Codex QQ Hook 开发入口

完成提醒的运行时唯一真源位于 `../../skills/codex-qq-hook/`。本目录不保留旧兼容脚本副本，避免与 skill 内的通知、开关和安装脚本形成双重实现。

- `../../skills/codex-qq-hook/scripts/`：正式 Python 与 PowerShell 实现。
- `../../skills/codex-qq-hook/templates/`：正式配置模板。
- `qq_event_capture.go`：仅用于 Webhook 验证或事件捕获的辅助程序，不是普通 Codex 完成提醒的主路径。

PowerShell 和 Python 修改直接在 skill 真源中开发。Go 辅助程序只依赖标准库，可用以下命令做编译检查：

```powershell
go test .\qq_event_capture.go
```

`QQ_BOT_APP_SECRET` 只通过环境变量提供，不得写入仓库、模板、日志或测试夹具。
