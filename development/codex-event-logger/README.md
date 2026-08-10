# Codex Event Logger 开发入口

运行时唯一真源位于 `../../skills/codex-event-logger/`。本目录只保存不应随 skill 安装的设计资料，不复制 Python 或 PowerShell 实现。

- `HOOK_LOGGING_DESIGN.md`：hook 事件、落盘结构和安全边界的设计依据。
- `../../skills/codex-event-logger/scripts/`：实际 Python 与 PowerShell 入口。
- `../../skills/codex-event-logger/event-logger-settings.json`：默认配置。

## 部署与迁移

`global/hooks.template.json` 是 AgentBase 的 hook 配置真源，`development/codex-deployment/manage_agentbase.ps1` 是把 skill 与 hooks 安装到 Codex home 的唯一项目入口。复制仓库到另一台 Windows 机器后，使用：

```powershell
& '.\development\codex-deployment\manage_agentbase.ps1' -Action Publish -ProjectRoot (Get-Location).Path -CodexRoot (Join-Path $env:USERPROFILE '.codex') -InstallPortableSettings
```

部署入口会解析目标机器的 Codex 根目录、备份并验证安装文件；不要复制旧机器绝对路径或手工维护第二份 `hooks.json` 示例。安装后重启 Codex，并在 `/hooks` 中审核和信任新机器上的实际命令。hook 信任哈希属于宿主状态，不随仓库迁移。

## 验证

开发环境需要 Python 3 与 Windows PowerShell 5.1。修改运行逻辑或读取协议后，应完成：

```powershell
python.exe '.\skills\codex-event-logger\tests\test_event_logger.py'
```

另外检查 Python/PowerShell 语法、空输入 smoke、代表性 hook payload 与落盘读回；设计发生变化时同步更新本目录的设计文档。日志读取统一使用 `read_codex_turn_log.py`，它在读取正文前检查大小，并限制读取字节、JSONL 记录数、单行和字符串长度。
