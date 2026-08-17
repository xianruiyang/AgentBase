# Global Codex payload

`global/` 维护 AgentBase 可跨 Windows 主机迁移的 Codex 全局候选与设置真源，不保存目标机器的认证、信任或运行状态。安装、增量合并、状态读回和回滚统一由[部署入口](../development/codex-deployment/README.md)负责。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| [`AGENTS.md`](AGENTS.md) | 跨项目执行内核，只约束目标、证据、授权、路由、修改、验证、记录和交付 |
| [`config.toml`](config.toml) | 经过筛选的机器无关 Codex 设置；部署时只合并受管键 |
| [`hooks.template.json`](hooks.template.json) | 事件记录与按工作区开启的 QQ 完成提醒模板；部署时只解析 `{{CODEX_ROOT}}` |
| [`agents/`](agents/) | `luna`、`sol`、`terra` 三个自定义子代理角色 |

## 全局内核边界

全局规则保持跨项目成立的最小内核：共同洞察并校准需求；区分规范来源与当前事实证据；依次保证质量、降低上下文成本并提升速度；让必要改动进入唯一正式入口；在 active Goal 中按真实不确定性和后果动态选择最低充分推理深度；工具同时服务模型和程序时从同一权威事实选择与当前消费者相符的最小充分输出面。复杂根因、职责迁移和共享门禁由 `change-governance` 承担，具体命令、字段、格式和领域协议由对应 skill 或项目正式来源承担。

项目静态合同限制候选全局规则与项目规则的总体体积，并为 Codex 项目指令预算保留余量。不要把专项命令配方、组件状态、benchmark 数字或单项目领域约定加入全局文件。

## 可移植设置边界

`config.toml` 当前管理人格、审批、sandbox、实时网页搜索、低输出详细度、关闭推理摘要、标准服务层、项目指令预算、Windows sandbox、多代理、hooks 和桌面偏好。主线程模型与默认推理深度保持目标宿主所有；未显式覆盖时，子代理默认使用 `gpt-5.6-luna` 与 `max` 推理深度。

部署只合并实际变化的受管键，并保留目标主机中的认证、项目 trust、MCP、插件/marketplace、hook 信任哈希、宿主生成字段、历史、日志、缓存和秘密。可移植设置不包含机器绝对路径，也不伪装成可以复制的 MCP 或插件安装状态。

`hooks.template.json` 只描述 hook 命令。新机器仍须通过 `/hooks` 审查并信任实际命令；信任哈希不会迁移。`agents/` 只管理三个同名自定义角色，不覆盖 Codex 内置代理或目标主机的其他个人代理。

修改这些文件后，按[部署说明](../development/codex-deployment/README.md#validate)运行部署合同验证。正式安装仍需要用户对当次 `Publish` 的明确同意。
