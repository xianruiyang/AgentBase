# 深度排障

只有用户明确问为什么没收到、hook 是否触发、日志含义、或要验证链路时，才读取本文件。

## 判断顺序

1. Hook 是否触发：查全局和工作区 `qq-hook-debug.jsonl` 是否有 `start`。
2. 工作区是否正确：日志里的 `workspace_root` 应该是用户当前工作区。
3. 对话是否开启：当前对话 ID 不能在 `disabled_thread_ids`，且应在 `enabled_thread_ids`，除非 `default_enabled=true`。
4. 全局机器人是否正确：全局 `bot.app_id`、目标 ID、`target_type` 必须匹配同一个 QQ 机器人。
5. QQ API 是否返回错误：日志里 `notify_error` 的 `error` 字段是最终原因。

## 常见日志

- `thread_not_enabled`：把当前对话 ID 加入 `enabled_thread_ids`。
- `goal_active`：当前对话有正在进行中的 goal，完成提醒暂不发送；没有 goal、goal 阻塞、goal 完成、usage_limited、budget_limited、paused 时都正常发送。
- `appid invalid`：全局 AppID 错或仍是模板值。
- `Missing QQ_BOT_APP_ID or QQ_BOT_APP_SECRET`：全局 AppID 未填，或 Codex 进程读不到用户环境变量。
- `QQ_BOT_TARGET_TYPE=user requires QQ_BOT_OPENID`：全局 OpenID 未填。

## 安全输出

排障回复中默认只说“已设置/未设置/模板值/不匹配”，不要直接展示真实 AppID、OpenID、AppSecret。

## 验证发送链路

dry-run 不访问 QQ，适合先验证白名单和配置路径。

真实发送只在用户明确要求时执行。执行后查日志是否有：

```json
"event": "sent",
"dry_run": false
```
