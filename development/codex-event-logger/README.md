# Codex Event Logger 开发入口

运行时唯一真源位于 `../../skills/codex-event-logger/`。本目录只保存不应随 skill 安装的设计资料，不复制 Python 或 PowerShell 实现。

- `HOOK_LOGGING_DESIGN.md`：hook 事件、落盘结构和安全边界的设计依据。
- `../../skills/codex-event-logger/scripts/`：实际 Python 与 PowerShell 入口。
- `../../skills/codex-event-logger/event-logger-settings.json`：默认配置。

## 部署与迁移

`global/hooks.template.json` 是 AgentBase 的 hook 配置真源，[Codex 部署说明](../codex-deployment/README.md)是安装 skill 与 hooks 的唯一命令 owner；本文件不复制部署命令。部署入口会解析目标机器的 Codex 根目录、备份并验证安装文件；不要复制旧机器绝对路径或手工维护第二份 `hooks.json` 示例。安装后重启 Codex，并在 `/hooks` 中审核和信任新机器上的实际命令。hook 信任哈希属于宿主状态，不随仓库迁移。

## 验证

开发环境需要 Python 3 与 PowerShell 7。修改运行逻辑或读取协议后，应完成：

```powershell
python.exe '.\skills\codex-event-logger\tests\test_event_logger.py'
```

另外检查 Python/PowerShell 语法、空输入 smoke、代表性 hook payload 与落盘读回；设计发生变化时同步更新本目录的设计文档。日志读取统一使用 `read_codex_turn_log.py`：默认 model 视图验证恢复信息充分且在预算内，显式 `--view machine` 验证原有有界 JSON 合同；两者共享同一次文件大小、读取字节、JSONL 记录数、单行和字符串限幅事实。
