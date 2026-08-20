# 完成审计

| 目标 | 状态 | 直接证据 |
| --- | --- | --- |
| REQ-001 / AC-001 | verified | 页尾为数量 `@more` + 唯一完整 `@next`；独立 Codex 没有自行重组控制面 |
| AC-002 | verified | 特殊 argv 在新 PowerShell 7 进程无损往返；snapshot fingerprint 通过且 fixture scc 调用次数保持 1 |
| AC-003 / UDES-001 | verified | 有效 v6 subject 直接执行提示命令，第二页 exit 0 并正确报告首项；网络与 postflight 均有效 |
| CON-001 | satisfied | cursor/snapshot 仍是唯一 query 状态；machine、cache/process 不变；没有 offset/length 或 `srcq more` |
| CON-002 | satisfied | 只构建隔离候选并验证；真实 srcq 安装和 Codex Publish 均未执行 |

query model renderer、source-query skill、文档和静态合同已经迁移，旧 query `@more ... after=<cursor>` 不再是当前模型动作入口；machine 的结构化 `next_cursor` 和 cache/process 自身协议继续有效。当前目标没有适用失败、第二状态源、未迁移消费者或开放实施项，SOL-001 完成。正式 0.4.1 archive 与真实安装仍是后续独立生命周期，不影响本次源码和模型友善度目标完成。
