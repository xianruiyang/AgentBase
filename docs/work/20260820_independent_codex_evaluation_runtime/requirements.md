# 独立 Codex 评估运行时需求

## REQ-001 复用当前 Codex 的网络运行条件

- 状态: confirmed
- 来源: 用户 2026-08-20 指出独立运行未使用当前 Codex `.env` 设置并发生五次重连
- 关联: AC-001, AC-002, AC-003, AC-006, UDES-001

独立 Codex 评估必须显式取得当前宿主用于联网的最小环境投影，不得依赖启动 runner 的父 shell 恰好已经加载相同变量。

## REQ-002 在真实只读工具边界内验证行为

- 状态: confirmed
- 来源: 用户 2026-08-20 指出原验证边界使部分内容无法运行
- 关联: AC-004, AC-005, UDES-002

评估 subject 必须能够启动任务所需的真实只读工具及其后端；框架问题修复并通过确定性验证后，才可重新验证正常同 turn 的 srcq 分页续读友善程度。

## AC-001 `.env` 只投影明确允许的网络键

- 状态: confirmed
- 关联: REQ-001

runner 从显式 `.env` 路径读取固定 allowlist 中的代理与证书键，清除父进程中未冻结的同类键后再注入 subject。SOCKS 代理端 DNS 和 ALL_PROXY 到 HTTP/HTTPS 客户端的 fanout 只能由 config 显式选择并冻结，不能隐式猜测。必需键缺失、为空、重复或格式无效时在启动 Codex 前失败。

## AC-002 敏感值不进入长期产物

- 状态: confirmed
- 关联: REQ-001

`.env` 不复制到隔离 home、仓库、日志或 capsule；experiment 只记录来源、允许/必需/实际键名、脱敏声明与整体投影 SHA-256，不记录值。

## AC-003 网络投影属于实验身份

- 状态: confirmed
- 关联: REQ-001

prepare 后 `.env` 的实际投影键或值变化会使 run 在 subject 启动前拒绝；父 shell 中同类代理变量不能静默改变已冻结身份。

## AC-004 正式 sandbox 与真实后端预检一致

- 状态: confirmed
- 关联: REQ-002

正式独立评估继续只接受 `danger-full-access` 与 `approval_policy=never`，并显式冻结 `websocket` 或绑定同一 ChatGPT OAuth endpoint 的 `http-only` transport；只读约束由 prompt 和运行前后身份读回承担。含 srcq 的环境必须在同一个 Codex 预检中成功运行 `srcq.exe --version` 与 `srcq query scc doctor`，且 preflight/subject 不得出现 WebSocket 连接失败、sampling retry 或 HTTP fallback。

## AC-005 正常续读取得直接事件证据

- 状态: confirmed
- 关联: REQ-002

一次新鲜、无历史、正常同 turn 的 independent Codex 运行应先取得含 `@more` 的 `srcq scc --by-file` 页面，再使用返回的精确 cursor 执行一次续页；不得重新运行原生 scc 扫描。结论以命令事件和输出为准，不用最终回答代替工具证据，也不覆盖压缩后恢复。

## AC-006 服务网络投影不得进入模型 shell

- 状态: confirmed
- 来源: 用户继续要求独立 Codex 权限与能力边界完善
- 关联: REQ-001, REQ-002, AC-001, AC-003, AC-004

冻结的 proxy/证书键只供 Codex 服务连接。preflight 与 subject 必须消费仓库共享、哈希固定的模型 shell policy，过滤网络、OpenAI/Codex、Git/SSH、云/包管理器凭据命名空间、语言注入与工作流控制变量；策略进入 experiment identity，自由 extra config 不得覆盖，prepare 后变化必须在新 subject 前拒绝。

## CON-001 不以重试掩盖相同失败

- 状态: confirmed
- 来源: 全局验证规则与既有 benchmark 协议

输入、实现和环境没有变化时不重跑；预检或 subject 失败保留为真实失败。candidate-only 评估只预检实际调度的 candidate，不为形式完整额外启动 control subject。

## CON-002 本任务不授权 Publish

- 状态: confirmed
- 来源: 项目逐次发布合同；用户本次只要求修复与验证

可以完成源码、验证、Git 提交和既有私有远端同步，但不得向实际 Codex 根目录执行 Publish。
