# 主动 QQ 消息

## 责任与授权

- 主动直发仅用于通知延迟会实质影响安全、正确性、可恢复性或必须由用户完成的当前裁决；普通进度、完成、一般错误及可在当前对话等待的沟通留在当前对话，完成提醒仍由 Stop Hook 负责。
- `<CodexRoot>\qq-hook-global-settings.json` 中的 `direct_send.enabled=true` 表示用户已对当前配置的目标通道授予持续直发权限。模型不得自行开启、替换目标或从工作区 Hook 开关推导该授权；开关开启后，必要性成立的单次发送不再重复请求许可。
- 消息仅含用户及时判断所需的事实、影响和动作，不扩大任务授权，也不把送达视为用户答复。同一事实只发一次，失败不无界重试。

## 正式入口

只使用本 Skill 的 `scripts\send_qq_message.ps1`。它与 Hook 共享机器人配置解析和 Python 传输，但不读取对话白名单或 Goal 状态，不等待 Hook 事件。

状态查询只读，配置不存在时不创建：

```powershell
$SkillDir = '<skill_dir>'
& (Join-Path $SkillDir 'scripts\send_qq_message.ps1') status -CodexRoot (Join-Path $env:USERPROFILE '.codex')
```

只有用户明确要求时才改变持续授权：

```powershell
& (Join-Path $SkillDir 'scripts\send_qq_message.ps1') enable -CodexRoot (Join-Path $env:USERPROFILE '.codex')
& (Join-Path $SkillDir 'scripts\send_qq_message.ps1') disable -CodexRoot (Join-Path $env:USERPROFILE '.codex')
```

发送时同时提供最终消息和不含秘密的必要性说明；说明仅进入本地审计日志，不发给 QQ 用户：

```powershell
& (Join-Path $SkillDir 'scripts\send_qq_message.ps1') send `
    -CodexRoot (Join-Path $env:USERPROFILE '.codex') `
    -ProjectRoot (Get-Location) `
    -Message '<message>' `
    -Reason '<why delayed notice materially matters>'
```

验证配置与消息形态而不访问 QQ 网络时加 `-DryRun`。真实发送后在当前对话报告结果；失败时保留任务状态并说明错误，不得用 Hook 或底层 Python 脚本绕过直发开关。
