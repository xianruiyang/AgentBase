# AgentBase 最小恢复入口

本文件只维护跨对话稳定的恢复步骤，不保存版本、哈希、安装状态、历史完成项或待办镜像。当前事实分别由 Git、组件 `Status`、MCP 查询和 [`docs/plan.md`](plan.md) 的正式 owner 提供。

## 下个对话的最小恢复步骤

1. 读取根 [`README.md`](../README.md) 和本文件，运行 `git status --short`；保留并确认未知未提交修改，不清理、回退或自动提交。
2. 只读确认 `HEAD`、upstream 与 ahead/behind。任务需要选择、替代或重开子计划时才读取 [`docs/plan.md`](plan.md)。
3. 需要 AgentBase 安装状态时，使用[部署说明](../development/codex-deployment/README.md)中的 `Status`，并按实际部署模式与设置范围读取 `managed_payload_formally_deployed` 和 `formal_deployment_gaps`；安装副本不得反推项目真源。
4. 需要 `srcq` 状态时，运行其正式安装器 `Status`、`srcq doctor` 和 `srcq query scc doctor`；源码版本、已发行版本和本机已安装版本分别取证，不互相外推。
5. 需要 LSP 时读取 `vscode-lsp-mcp` 的 status 与 `list_workspaces`。若 VS Code 已打开而 workspace 为 0，先请用户执行 **Reload Window**；不自行关闭编辑器、重装扩展或重复部署。
6. 新任务应从当前运行时暴露的自定义角色确认 `evidence`、`experiment`、`advanced-experiment` 与 `operator` 已加载；不要从安装文件存在推断运行时已经生效。新建或实质变化的角色只在明确需要验证时做一次有界真实调用；若新任务仍暴露旧角色集合，完整退出并重启 Codex 桌面宿主后再开任务。
7. 默认分工由 `subagent-orchestration` 维护：困难推理或需要截图、渲染反馈的实现实验使用 `advanced-experiment`；普通和高级 experiment 在当前实验范围内按需委派一层 `evidence` 分担搜索，无需另行授权，不得创建其他角色。evidence 与 operator 不得创建子代理，简单查询由当前执行者直接完成。
8. 线程推理深度只在用户明确要求查看、设置、固定、改变、重评或解除时操作；不得因任务难度、成本、Goal、计划或后继工作自主查询、升降或恢复。SessionStart 的状态投影只读，不是变更授权。
9. `Deploy` 只把仓库候选应用到指定 Codex 消费者；每次写入真实 Codex 根都需要用户对当次部署的明确授权。`Release` 是形成版本、标签或分发资产的独立发行合同，也不得从部署、Git 或历史授权继承。
10. 没有相关改动时不运行完整验证、真实模型评测或九项评测；候选稳定后只按实际影响范围运行一次必要验证。
