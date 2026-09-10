# Global Codex payload

`global/` 维护 AgentBase 可跨 Windows 主机迁移的 Codex 全局候选与设置真源，不保存目标机器的认证、信任或运行状态。安装、增量合并、状态读回和回滚统一由[部署入口](../development/codex-deployment/README.md)负责。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| [`AGENTS.md`](AGENTS.md) | 跨项目执行内核，只约束目标、证据、授权、路由、修改、验证、记录和交付 |
| [`config.toml`](config.toml) | 经过筛选的机器无关 Codex 设置；部署时只合并受管键 |
| [`hooks.template.json`](hooks.template.json) | 推理档位状态投影、事件记录与按工作区开启的 QQ 完成提醒模板；部署时只解析 `{{CODEX_ROOT}}` |
| [`agents/`](agents/) | `evidence`、普通/高级 experiment 与 `operator` 四个语义稳定的自定义子代理角色；各文件唯一维护实际模型、档位和角色指令 |

## 全局内核边界

全局规则用普通 Markdown 直接表达动作与边界，不要求 must/should 标签，不另定义宿主指令优先级。内容保留目标与事实的区别、授权、共享前提、消费者与旧路径闭合、最小充分上下文和验收；通用能力说明与重复流程不作为常驻教程。题面长短不决定影响范围，必要的真实调用和约束检查仍保留。

具体触发与读取规则以 `AGENTS.md` 和对应 skill 为准：普通查询控制单条及整批返回预算，截断按缺口恢复；普通 evidence 派发使用编排主文件与证据交接引用，跨分支归属或送达问题才加载 coordination。部署只证明文件状态，文本压缩与静态通过不证明端到端成本或行为已经改善。

项目静态合同限制候选全局规则与项目规则的总体体积，并为 Codex 项目指令预算保留余量。不要把专项命令配方、组件状态、benchmark 数字或单项目领域约定加入全局文件。

## 可移植设置边界

顶层 `developer_instructions` 由 `config.toml` 唯一维护，仅补充等待已派发子代理时的等待时长与进度约定，不替换内置指令或复制整套全局规则。部署将该完整字符串作为受管键合并、读回和回滚；为适配逐行合并，正文使用无转义的单行 TOML 字符串。Codex 在新运行中消费它；配置已安装不证明等待行为已改变，需从新任务的实际指令与调用确认。各子代理文件中的同名字段仍维护角色职责。

`config.toml` 当前管理人格、审批、命令 sandbox 模式、实时网页搜索、低输出详细度、关闭推理摘要、标准服务层、项目指令预算、多代理开关、hooks 和桌面偏好。主线程模型、默认推理深度与 Windows sandbox 后端保持目标宿主所有；portable config 不维护主动委派 mode、tool hint 或递归策略。`global/AGENTS.md` 维护用户优先、主代理定稿与子代理默认分工、允许等待及按角色限定的委派边界；`subagent-orchestration` 维护实际创建、按缺口选择角色、实验内按统一触发原则委派一层 evidence 与专属 operator、等待子代理、阅读审核与交接。`[agents].max_concurrent_threads_per_session = 6` 只限制不含 root 的同时打开子代理线程，不参与是否委派的裁决；未显式选择角色时的模型和档位回退也由 `[agents]` 管理。`evidence.toml`、`experiment.toml`、`advanced-experiment.toml` 与 `operator.toml` 分别唯一维护只读取证、普通实现实验、困难或视觉实验和合同已确认的有界执行角色；主代理保留规划、关键文档、正式质量与验收。全局规则和 skill 只按语义角色选择，不复制易变的模型名或档位。

部署只合并实际变化的受管键，并保留目标主机中的认证、项目 trust、MCP、插件/marketplace、Windows sandbox 后端、hook 信任哈希、宿主生成字段、历史、日志、缓存和秘密。`windows.sandbox` 的初始化依赖机器状态和用户批准，已从 AgentBase 受管键移交宿主；最终评测也不再选择、初始化或维护 elevated 后端，而是使用受信任本地 candidate 与独立 Verifier 工作区。可移植设置不包含机器绝对路径，也不伪装成可以复制的 MCP 或插件安装状态。

`hooks.template.json` 只描述 hook 入口与有界运行参数。`SessionStart` 通过 `reasoning-governor` 的权威线程读回，在新上下文和压缩后投影一行当前 next-turn 档位，并只用可丢弃的有限缓存抑制相同 `resume`；缓存不持有或设置推理状态，也不触发自主档位选择或变更。新机器仍须通过 `/hooks` 审查并信任实际命令；信任哈希不会迁移。`agents/` 只管理上述四个自定义角色，不覆盖 Codex 内置代理或目标主机的其他个人代理。旧 `luna`、`sol` 与更早的 `terra` 由部署生命周期作为退役受管资产处理，不保留同责候选。

修改这些文件后，按[部署说明](../development/codex-deployment/README.md#validate)运行部署合同验证。向真实 Codex 根执行 `Deploy` 仍需要用户对当次部署的明确同意。
