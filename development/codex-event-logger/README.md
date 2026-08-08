# Codex Event Logger 开发入口

运行时唯一真源位于 `../../skills/codex-event-logger/`。本目录只保存不应随 skill 安装的设计资料，不复制 Python 或 PowerShell 实现。

- `HOOK_LOGGING_DESIGN.md`：hook 事件、落盘结构和安全边界的设计依据。
- `../../skills/codex-event-logger/scripts/`：实际 Python 与 PowerShell 入口。
- `../../skills/codex-event-logger/event-logger-settings.json`：默认配置。

开发环境需要 Python 3 与 Windows PowerShell 5.1。修改运行逻辑后，应在 skill 真源中完成语法检查、空输入 smoke、代表性 hook payload 与落盘读回验证；设计发生变化时同步更新本目录的设计文档。
