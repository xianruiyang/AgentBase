# 现状与差距

## OBS-001 当前身份把无关内容绑定到所有阶段

- 状态: confirmed
- 证据: 修改前 `routing_evaluation_common.ps1`、`routing_fingerprint.ps1`
- 关联: GAP-001

Routing capsule 只暴露 description，但候选哈希包含 11 个完整 `SKILL.md` 和 `agents/openai.yaml`；Policy 和 References 又绑定完整 Routing evaluator/result 身份。任何 skill 正文或 metadata 变化都会使三阶段整体陈旧。

## OBS-002 当前完整 capsule 输入成本为 36785 Token

- 状态: confirmed
- 证据: 2026-08-20 当前 96 用例候选，tiktoken 0.13.0 / o200k_base
- 关联: GAP-001, GAP-002

Routing 为 14746 Token，Policy 为 13805 Token，References 为 8234 Token；数值不含模型输出和三次进程启动。Routing/Policy 都重复携带 96 个请求，普通成功结果还要求逐项 note。

## OBS-003 WindowsApps CLI 不能由普通子进程直接执行

- 状态: confirmed
- 证据: 文件 ACL、AppxManifest、真实进程启动与独立 CLI 烟测
- 关联: GAP-003

商店包 `codex.exe` 的执行 ACE 要求 `OPENAI.CODEX_...` package identity，普通 PowerShell 只有读取权。当前已安装官方 npm `@openai/codex@0.148.0`，调整用户 PATH 后完成登录读回和仓库外 read-only/ephemeral/schema 烟测；临时 home 未扫描真实 skills，认证文件未变化。

## GAP-001 阶段证据无法安全复用

- 状态: confirmed
- 关联: OBS-001, DES-001, DES-002

现有 `current.json` 只能表示一次完整三阶段运行，不能证明某一阶段的真实可见输入未变，也不能在其他阶段变化时保留它。

## GAP-002 运行顺序和输出包含不必要成本

- 状态: confirmed
- 关联: OBS-002, DES-002, DES-003

Policy 被迫等待 Routing，模型重复生成 evaluator envelope 与 215 个普通用例 note；没有正式 planner 告知零运行或最小阶段集合。

## GAP-003 PATH 解析和运行隔离没有正式入口

- 状态: confirmed
- 关联: OBS-003, DES-003

修改前手工调用 `codex` 会先命中不可执行的 WindowsApps 路径；即使使用 runnable 副本，真实 CODEX_HOME 仍会扫描用户 skills。烟测已证明用户 npm 原生二进制与临时 home 可行，但当时尚未进入仓库 runner 和回归合同。

## OBS-004 评估机制缺少统一零模型回归入口

- 状态: confirmed
- 证据: 修改前 `development/skill-routing` 独立测试脚本与 `manage_agentbase.ps1`
- 关联: GAP-004

修改前静态合同、指纹、capsule、attempt history 和部署测试由多个入口分别运行；部署 Validate 只校验证据产物，没有一次命令覆盖 planner、隔离 runtime、并发账本和崩溃恢复，也没有机械阻止恢复测试在回归时意外启动 evaluator。

## GAP-004 后续评估改动仍可能漏测或误触发模型

- 状态: confirmed
- 关联: OBS-004, DES-006

没有统一确定性入口和部署消费者时，维护者需要人工记忆测试集合；恢复路径退化可能直到正式模型运行才暴露，甚至让本应零 Token 的测试调用外部 evaluator。

## OBS-005 服务进程环境与模型 shell 曾只有一个继承面

- 状态: confirmed
- 证据: 2026-08-21 shared runtime、路由 runner 与 Codex config reference 对照
- 关联: GAP-005

路由 evaluator 的成功合同禁止任何 tool event，所以既有成功 evidence 没有通过 shell 观察宿主环境；但 runner 仍缺少一条显式、共享并固定身份的模型 shell 过滤策略。以后如果模型偏离并尝试工具，结果虽会失败，却不应先获得 proxy、Git/SSH 或其他 ambient 控制变量。

## GAP-005 模型 shell 隔离曾依赖“成功时不用工具”的间接边界

- 状态: superseded
- 关联: OBS-005, DES-003, AC-006

runner 必须在保持 cases-only/tool-event failure oracle 的同时注入共享 shell policy，并把 policy hash 记入新运行 runtime；因为通过结果从未消费工具且 capsule 未变化，该安全加强不使当前 oracle-valid evidence 失效，也不能作为重新采样理由。
