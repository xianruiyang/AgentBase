# Workflow CLI 运行时与模型输入输出：验证

更新时间：2026-09-02

## 组件行为

- taskctl 的来源短回执、复核分页短回执、缺失/陈旧/冲突 gate、machine 完整身份及模型来源语义定向测试通过；最新低预算恢复提示测试通过，不再建议模型切换 machine 视图。
- workctl 的默认稀疏视图、protect 确认来源隔离、baseline 诊断去重和低预算恢复 4 项最新定向测试在 1.622 秒内通过；此前 39 项受影响投影测试通过。
- workflow-cli 安装器测试在 9 秒内通过 Install、幂等、篡改、PATH 漂移、回滚与 Uninstall 场景；构建包清单、成员哈希与 ZIP 路径约束由该入口验证。
- 一次 146 项组件发现运行超过 60 秒后仍未结束，已按有界验证规则终止；随后定位的第 21 项分页测试单独在 2.121 秒内通过。该无界运行不记作通过，也未重复全量运行。

## 合同与集成

- `development/skill-routing/validate_contract.ps1` 通过：132 个 case、87 个严格路由 case、28 个严格引用 case，13/13 skill 均有正向与非触发覆盖。
- `manage_agentbase.ps1` 的 PowerShell 语法和差异格式通过；从脚本 AST 直接加载正式 `Get-WorkflowCliRuntimePreflight` 并对当前主机执行，读回 0.1.0、User PATH 条目数 1、两个命令检查均为 true。完整部署测试在消费 payload 前被“routing evidence 不属于当前可见候选”阻断；当前任务未刷新或运行模型路由评测，因此没有把整条部署链误记为通过。
- 当前正式来源已无 skill 内旧 `workctl.py`/`taskctl.py`、旧模板或旧测试路径引用；历史交付证据未改写。

## 当前主机读回

- 已从本地受验证包安装 workflow-cli 0.1.0 到 `C:\Users\gzxt\AppData\Local\Programs\AgentBase\workflow-cli\current`。
- Machine Status 读回 `ready=true`、User PATH、受管 PATH 条目数 1；从安装目录直接执行得到 `workctl 0.1.0` 与 `taskctl 0.1.0`。
- 当前 Codex 宿主进程尚未继承新增 PATH，命令名解析需要完整重启 Codex 桌面宿主；当前任务已使用安装目录直接完成读回。

## 模型输出成本

在既有真实工作区 `docs/work/20260817_model_visible_tool_output_contract` 上，用 CLI 自有保守 Token 成本函数比较同一 status 事实：

| 命令 | model 成本 | machine 成本 | model 含 `sha256:` |
| --- | ---: | ---: | --- |
| workctl status | 84 | 580 | 否 |
| taskctl status | 52 | 464 | 否 |

该表只证明当前工作区与当前 status 动作的投影差异，不外推为所有命令或旧版本的固定收益。
