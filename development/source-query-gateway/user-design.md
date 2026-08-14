# 低成本源码查找分支用户设计

## 1. 文档职责

本文件只记录用户为实现 [requirements.md](requirements.md) 明确指定的技术选择。它们约束候选设计，但不能替代对质量、端到端总 Token 和速度的结果验收。

## UDES-SQG-001 使用统一包装能力

- 状态: confirmed
- 来源: 用户要求要么裁撤现有包装，要么认真做成统一包装
- 关联: REQ-SQG-001

rg、fd 与 ast-grep 的模型侧包装能力由同一个可维护工具承载，不继续维护质量不足或职责重复的独立包装协议。

## UDES-SQG-002 完整兼容原生命令

- 状态: confirmed
- 来源: 用户明确要求完整兼容 rg、fd 与 ast-grep 的所有指令
- 关联: REQ-SQG-001, AC-SQG-001

在明确支持的精确版本内，包装不以简化语法取代底层工具；原生命令、参数、stdin、TTY、输出、退出和副作用语义都应能够调用。不能安全结构化的模式使用透传或显式产物。

## UDES-SQG-003 根据实际结果选择低 Token 输出

- 状态: confirmed
- 来源: 用户要求根据实际情况尽可能使用最短 Token 的输出
- 关联: REQ-SQG-001, AC-SQG-002

包装依据命令语义、当前所需证据和实际结果形状选择更短的充分表示，不把固定 JSON、YAML 或文本格式用于所有查询。

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
