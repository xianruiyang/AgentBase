# Global Codex payload

`global/` 维护 AgentBase 可跨 Windows 主机迁移的 Codex 全局候选与设置真源，不保存目标机器的认证、信任或运行状态。安装、增量合并、状态读回和回滚统一由[部署入口](../development/codex-deployment/README.md)负责。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| [`AGENTS.md`](AGENTS.md) | 跨项目执行内核，只约束目标、证据、授权、路由、修改、验证、记录和交付 |
| [`config.toml`](config.toml) | 经过筛选的机器无关 Codex 设置；部署时只合并受管键 |
| [`hooks.template.json`](hooks.template.json) | 推理档位状态投影、事件记录与按工作区开启的 QQ 完成提醒模板；部署时只解析 `{{CODEX_ROOT}}` |
| [`agents/`](agents/) | `evidence`、`experiment` 与 `operator` 三个语义稳定的自定义子代理角色；各文件唯一维护实际模型、档位和角色指令 |

## 全局内核边界

全局规则保持跨项目成立的最小内核：共同洞察并校准需求；区分规范来源与当前事实证据；依次保证质量、降低上下文成本并提升速度；多个动作共享未证判断时先由真实消费者的最小结果路径取得证据，反例出现时在扩展下游前返回失效层；用户裁决目标、范围与知情风险，模型负责事实、因果关系和有效执行顺序；把模型直接读取、生成或维护的工具返回与文件视为交互面，按事实 owner、消费者责任和生命周期选择最小充分读取面、可靠修改面或完整机器面；每轮重新路由 skill，但只在所需原文不再可用或已知变化时重读。复杂工作的运行期证据前沿、纵向消费者、昂贵验证和失败熔断由 `execution-governor` 承担；交付文档、任务存储、深层职责治理与线程设置分别由 `delivery-workflow`、`task-table-manager`、`change-governance` 与 `reasoning-governor` 承担，具体命令、字段、格式和领域协议继续留在对应 skill 或项目正式来源。

项目静态合同限制候选全局规则与项目规则的总体体积，并为 Codex 项目指令预算保留余量。不要把专项命令配方、组件状态、benchmark 数字或单项目领域约定加入全局文件。

## 可移植设置边界

`config.toml` 当前管理人格、审批、命令 sandbox 模式、实时网页搜索、低输出详细度、关闭推理摘要、标准服务层、项目指令预算、多代理开关、hooks 和桌面偏好。主线程模型、默认推理深度与 Windows sandbox 后端保持目标宿主所有；portable config 不维护主动委派 mode、tool hint 或递归策略。`global/AGENTS.md` 唯一维护 `/root` 的主动创建顺序与 child 默认不递归边界，`subagent-orchestration` 维护三种固定角色、真实创建、等待和交接。`[agents].max_concurrent_threads_per_session = 6` 只限制不含 root 的同时打开子代理线程，不参与是否委派的裁决；未显式选择角色时的模型和档位回退也由 `[agents]` 管理。`evidence.toml`、`experiment.toml` 与 `operator.toml` 分别唯一维护当前只读取证、可逆操作实验和合同已确认的有界执行角色的模型、推理档位与行为边界：`evidence` 可观察既有状态但不操作，`experiment` 通过可恢复的实际操作发现路径、错误或约束，`operator` 在冻结输入与既定 oracle 下完成难以脚本化的执行。全局规则和 skill 只按语义角色选择，不复制易变的模型名或档位。

部署只合并实际变化的受管键，并保留目标主机中的认证、项目 trust、MCP、插件/marketplace、Windows sandbox 后端、hook 信任哈希、宿主生成字段、历史、日志、缓存和秘密。`windows.sandbox` 的初始化依赖机器状态和用户批准，已从 AgentBase 受管键移交宿主；最终评测需要的 elevated 后端只由评测的显式 `sandbox-setup` 入口管理。可移植设置不包含机器绝对路径，也不伪装成可以复制的 MCP 或插件安装状态。

`hooks.template.json` 只描述 hook 入口与有界运行参数。`SessionStart` 通过 `reasoning-governor` 的权威线程读回，在新上下文和压缩后投影一行当前 next-turn 档位，并只用可丢弃的有限缓存抑制相同 `resume`；缓存不持有或设置推理状态。新机器仍须通过 `/hooks` 审查并信任实际命令；信任哈希不会迁移。`agents/` 只管理 `evidence`、`experiment` 与 `operator` 三个自定义角色，不覆盖 Codex 内置代理或目标主机的其他个人代理。旧 `luna`、`sol` 与更早的 `terra` 由部署生命周期作为退役受管资产处理，不保留同责候选。

修改这些文件后，按[部署说明](../development/codex-deployment/README.md#validate)运行部署合同验证。正式安装仍需要用户对当次 `Publish` 的明确同意。
