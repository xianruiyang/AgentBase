# 用户设计

## UDES-001 scc 与 rg/fd 使用同一 srcq 入口形状

- 状态: confirmed
- 来源: 用户原话“将scc直接跟rg fd这样纳入srcq的处理”并确认后续开发
- 关联: REQ-001, AC-003

`scc` 作为 srcq 的原生 backend，普通使用和高级控制分别沿用 rg/fd 已验证的直接入口与 `srcq query` 控制面；不建立独立包装器或并行正式入口。

## UDES-002 scc 与 hyperfine 都属于主机安装需求

- 状态: confirmed
- 来源: 用户明确要求“这两个工具也纳入项目的安装需求里”
- 关联: REQ-001, AC-002

AgentBase 的 Windows 主机准备入口安装、升级并读回这两个外部工具，工具二进制不进入 AgentBase 发布 payload。

## UDES-003 当前轮不改变深度且不启动独立 Codex

- 状态: confirmed
- 来源: 用户当前轮明确约束
- 关联: CON-001, CON-002

本轮在当前推理深度内完成所有不依赖独立 Codex 额度的开发与验证；独立模型验证不尝试、不重试，也不伪装为已经通过。
