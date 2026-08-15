# 低成本源码查找分支用户设计

## 1. 文档职责

本文件只记录用户为实现 [requirements.md](requirements.md) 明确指定的技术选择。它们约束候选设计，但不能替代对质量、端到端总 Token 和速度的结果验收。

## UDES-SQG-001 使用统一包装能力

- 状态: confirmed
- 来源: 用户要求要么裁撤现有包装，要么认真做成统一包装
- 关联: REQ-SQG-001

直接扩展现有 sgy，由它统一承载 rg、fd 与 ast-grep 的模型侧包装能力，不继续维护质量不足或职责重复的独立包装协议。

## UDES-SQG-002 完整兼容原生命令

- 状态: confirmed
- 来源: 用户明确要求完整兼容 rg、fd 与 ast-grep 的所有指令
- 关联: REQ-SQG-001, AC-SQG-001

在明确支持的精确版本内，包装不以简化语法取代底层工具；原生命令、参数、stdin、TTY、输出、退出和副作用语义都应能够调用。不能安全结构化的模式使用透传或显式产物。

## UDES-SQG-003 根据实际结果选择低 Token 输出

- 状态: confirmed
- 来源: 用户要求根据实际情况尽可能使用最短 Token 的输出
- 关联: REQ-SQG-001, AC-SQG-002

包装依据命令语义、当前所需证据和实际结果形状选择更短的充分表示，不把固定 JSON、YAML 或文本格式用于所有查询。普通成功结果默认只显示结果与判断完整性所需的最小回执；backend、engine version、mode、view、字节数和完整查询身份等元数据仅在诊断、续页或机器消费者确有需要时显示。

## UDES-SQG-004 fd 优先使用可逆目录树

- 状态: confirmed
- 来源: 用户要求 fd 文件输出采用目录树避免重复路径头
- 关联: REQ-SQG-001, AC-SQG-002

fd 返回大量共享目录前缀时，在确实更短的条件下使用可还原全部路径的目录树表示；目录树不以抽样替代完整结果。

## UDES-SQG-005 包装质量以 sgy 为基线

- 状态: confirmed
- 来源: 用户要求若保留包装，就做到与 sgy 同等质量
- 关联: REQ-SQG-001, AC-SQG-001

新增能力应具备稳定接口、真实引擎兼容、明确错误边界、自动化测试、安装发布和来源证明，不把启发式特例堆叠为正式协议。

## UDES-SQG-006 AST 沿用现有 sgy 设计

- 状态: confirmed
- 来源: 用户明确要求 ast-grep 方面继续沿用 sgy 的设计
- 关联: REQ-SQG-001, AC-SQG-001

当前 sgy 的 AST 命令结构、argv 边界、profile、safe YAML、cache、fingerprint、`process containing`、`group-locations`、rewrite preview/apply、TTY/LSP、artifact、诊断和发布链继续作为正式基线。统一化不得把 AST 迁入另一套命令模型，也不得用 rg/fd 的需求削弱其边界。

## UDES-SQG-007 通过外部监控运行隔离 agent 对照

- 状态: confirmed
- 来源: 用户要求把既有 Token 测试固化为可重复利用的、通过监控隔离 agent 测试内容的流程
- 关联: REQ-SQG-001, AC-SQG-004

每个测试回合使用无对话历史的新鲜隔离 agent；协调方只负责按冻结输入启动、监控事件流、限时、保存原始结果和结束进程，不在运行中提示或修正被测 agent。对照 agent 不得看到另一环境的输出或聚合结论，质量复核由独立审计角色在运行完成后执行。

## UDES-SQG-008 测试流程只保留在项目内

- 状态: confirmed
- 来源: 用户明确要求项目测试不与发布到 Codex 的内容混合
- 关联: REQ-SQG-001, AC-SQG-004, CON-SQG-003

隔离 agent 测试流程及其全部输入、执行器和结果只在 AgentBase 仓库的开发边界内维护，不嵌入发布 skill、sgy 运行时或 Codex 安装目录。

## UDES-SQG-009 sgy 作为正常 Windows 命令安装和卸载

- 状态: confirmed
- 来源: 用户明确要求 sgy 具备正常安装和卸载能力，并能像 Python 一样在 PowerShell 中直接调用
- 关联: REQ-SQG-001, AC-SQG-001, CON-SQG-002

sgy 应作为独立的 Windows 用户级 CLI 安装并进入用户 `PATH`，使 PowerShell、Codex 与其他消费者都能直接调用 `sgy.exe`，不依赖项目目录、Codex 根目录或某个 skill 的私有路径。正式生命周期必须覆盖安装、状态查询、升级和卸载；升级失败可恢复，卸载只移除安装器管理的文件与 `PATH` 项，不破坏无关用户状态。skill 不再捆绑或回退到另一份私有 sgy 运行时。
