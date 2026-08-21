# AgentBase

AgentBase 集中维护 Windows 上可迁移的 Codex 全局规则、设置、skill、插件、MCP、CLI 及其开发与部署合同。仓库内容是项目真源；只有用户针对当次发布明确同意后，正式部署入口才会把选定内容增量安装到 Codex。

## 从哪里开始

- [根本需求](docs/requirements.md)：项目长期用户目标、可验收结果和约束。
- [项目总计划](docs/plan.md)：总体方向、跨计划决策、子计划关系、实践结论和重开条件。
- [项目规则](AGENTS.md)：AgentBase 内的职责、维护、验证、发布和 Git 边界。
- [全局候选与可移植设置](global/README.md)：`global/AGENTS.md`、`config.toml`、hooks 和自定义子代理的职责与边界。

普通组件内工作从本页定位 owner 后读取对应说明；只有选择、新建、替代或重开子计划，改变跨组件方向，或需要裁决多个正式 owner 时继续读取总计划。

## 真源与职责

| 入口 | 职责 |
| --- | --- |
| [`global/`](global/README.md) | 候选全局规则、可移植 Codex 设置、hooks 模板和自定义子代理 |
| [`skills/`](skills/) | 各 skill 的唯一开发真源；触发边界由各 `SKILL.md` frontmatter 定义 |
| [`mcp/vscode-lsp-mcp/`](mcp/vscode-lsp-mcp/README.md) | VS Code LSP MCP server、companion、协议、安全边界和独立 Windows release |
| [`tools/srcq/`](tools/srcq/README.md) | Source Query Gateway 源码、测试、Windows 安装器和独立 release |
| [`development/codex-event-logger/`](development/codex-event-logger/) | 对话事件记录 hook 的开发资料；运行脚本仍由对应 skill 所有 |
| [`development/codex-qq-hook/`](development/codex-qq-hook/) | QQ Webhook 辅助程序与开发资料；运行脚本仍由对应 skill 所有 |
| [`development/source-query-gateway/`](development/source-query-gateway/plan.md) | 源码查询专项需求、设计、计划和实践证据 |
| [`development/skill-routing/`](development/skill-routing/README.md) | 静态触发合同与脱离仓库的分阶段路由评估 |
| [`development/agent-evaluation/`](development/agent-evaluation/README.md) | 固定 DeepSWE 题目/计分语义、Windows candidate/verifier 双工作区与逐题资格/结果组成的派生最终评测集 |
| [`development/plugin-packaging/`](development/plugin-packaging/README.md) | `agentbase-core` 插件模板、过滤打包和官方校验入口 |
| [`development/codex-deployment/`](development/codex-deployment/README.md) | Windows 主机准备、校验、增量发布、状态读回与回滚 |
| [`development/responsibility-lifecycle.md`](development/responsibility-lifecycle.md) | 公共职责形成、消费者接入和穿透式更新的设计分析 |
| [`.agents/plugins/marketplace.json`](.agents/plugins/marketplace.json) | 仓库级插件发现入口；只指向可重建的本地打包产物 |

`development/` 只承载验证、打包、部署和开发资料。Codex 根目录中的同名文件是安装目标或宿主状态，不反向定义项目，也不与仓库双向同步。构建目录、依赖树、缓存、日志、测试输出和部署沙箱不是项目真源。

项目只维护 Windows 宿主。外部协议或文件格式出现其他平台术语，不代表 AgentBase 承诺相应运行时、安装器或测试矩阵。

## 能力分层

全局内核只保留跨项目成立的目标、证据、授权、工具路由、修改、验证、记录和交付约束。领域协议按需进入对应 skill：

- 执行与交付：`execution-governor` 控制复杂工作的当前证据前沿与下一动作；`delivery-workflow`、`task-table-manager`、`change-governance`、`reasoning-governor` 分别维护交付语义、任务存储、深层治理和线程设置。
- 源码与工程：`source-query`、`symbol-structure-workflow`、`powershell-usage`、`cpp-engineering-rules`、`understand-space`。
- 运行协作：`codex-event-logger`、`codex-qq-hook`。

`source-query` 统一消费 PATH 中独立安装的 `srcq.exe`：普通文本、文件和源码统计分别直接使用 `srcq rg`、`srcq fd` 与 `srcq scc`，高级投影、续页和语义查询才按需加载 skill；可重复命令基准直接使用独立安装的 `hyperfine`。真实符号身份、类型、引用或层级仍有歧义时再渐进使用 `vscode-lsp-mcp`。插件包不复制 MCP、`srcq.exe`、scc 或 hyperfine，也不建立第二套安装入口。

组件许可证独立生效：`mcp/vscode-lsp-mcp` 使用 Apache-2.0，`tools/srcq` 使用 MIT OR Apache-2.0。仓库根目前没有统一 `LICENSE`，不能把组件许可证外推为整个 AgentBase 的授权。

## 验证与发布导航

本仓库不维护远程 CI，GitHub Actions 也不是项目验证入口；远端只承担源码与历史同步。按实际影响范围在 Windows 主机运行对应组件说明中的最小充分验证：[`test_routing_infrastructure.ps1`](development/skill-routing/test_routing_infrastructure.ps1) 并行运行零模型 Token 的路由基础设施回归，[`test_agent_evaluation_infrastructure.ps1`](development/agent-evaluation/test_agent_evaluation_infrastructure.ps1) 以 evaluator 禁用状态验证最终评测 corpus、宿主默认拒绝、候选 workspace 写入、完整 skill 树只读投影、逐 attempt 临时面、模型 shell/launcher 环境净化、题目固定运行时提示、工具身份、srcq 关键工作流、patch、报告、收据和恢复边界；该确定性入口不会克隆题目、安装依赖、执行 qualification、启动模型或触发 elevated sandbox 初始化。全局规则、skill 与项目静态关系由 [`validate_contract.ps1`](development/skill-routing/validate_contract.ps1) 检查。正式独立路由模型证据先由 [`get_routing_evaluation_plan.ps1`](development/skill-routing/get_routing_evaluation_plan.ps1) 按阶段裁决，再由 [`refresh_routing_evidence.ps1`](development/skill-routing/refresh_routing_evidence.ps1) 只运行必要阶段并登记复用；Windows SWE 通过 [`agent_eval.py`](development/agent-evaluation/agent_eval.py) 显式执行无模型权限验收、跨 owner 最终证据汇总及逐题资格/候选运行，部署合同由 [`manage_agentbase.ps1`](development/codex-deployment/manage_agentbase.ps1) 校验，其他组件沿各自 README 或清单中的正式本地入口验证。真实 `sandbox-check`/`assess` 可能请求管理员批准以初始化 elevated Windows sandbox，因此必须显式运行，不进入日常 Validate 或 Publish 前置。

插件构建、Codex 发布模式、主机前置条件、只读状态和回滚命令分别由[插件打包说明](development/plugin-packaging/README.md)与[部署说明](development/codex-deployment/README.md)维护。每次向真实 Codex 根目录执行 `Publish` 前都必须取得用户针对该次发布的明确同意；Git 同步、此前发布授权或验证通过均不能替代。

发布状态不在 README 手工维护。使用部署说明中的只读 `Status` 入口按所选分发范围读取当前项目、安装副本、发布清单和路由证据的关系。发布成功只证明文件已安装；当前 Codex 运行不会追溯加载新规则，需在新任务或重启后的运行中使用。
