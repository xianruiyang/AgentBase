# srcq 模型续页动作需求

## REQ-001 模型可以直接执行查询续页

- 状态: confirmed
- 来源: 用户 2026-08-22 根据真实使用中长 cursor/完整 argv 难以复制的反例，确认改为短句柄并要求实现、安装和发布
- 关联: AC-001, AC-002, AC-003, UDES-001

当 `srcq query` 的 model 结果未展示完时，输出必须让正常同一轮中的 Codex 只传递一个短、可辨认的句柄，不需要复制不透明 cursor、回忆控制面语法或重组原命令，就能沿同一快照取得下一页。

## AC-001 页尾同时表达不完整事实和唯一下一动作

- 状态: confirmed
- 关联: REQ-001

截断页保留 `@more shown=<N> omitted=<N>` 完整性信号，并另给一条 `@next srcq more q<number>`。模型动作不得暴露或重复 cursor、backend、cwd、wrapper 选项和原生 argv；首批正常句柄使用 `q1`、`q2` 这样的最短十进制单调编号，不固定填充到六位。

## AC-002 续页保持查询身份且不重扫原生后端

- 状态: confirmed
- 关联: REQ-001

srcq 内部句柄记录必须保持 backend、已解析 cwd/引擎、影响分页的 wrapper 值、原生 argv 和已有 snapshot cursor。参数中的空值、空白、PowerShell 元字符、引号、反引号、美元符号和控制字符不得改变；续页只能读取已持久化快照，不能再次执行原生 rg、fd 或 scc 查询。

## AC-003 真实独立 Codex 能完成正常续读

- 状态: confirmed
- 关联: REQ-001

从真实 CLI 消费入口取得第一页后，PowerShell 7 直接执行 `@next` 短命令应取得第二页。测试必须直接证明句柄动作、内部 cursor/argv 身份和原生扫描次数；仅审查格式或模型最终自述不能替代工具事件。

## CON-001 cursor 仍是唯一查询续页状态

- 状态: superseded
- 来源: 2026-08-20 旧选择；被用户 2026-08-22 确认的短句柄合同替代

历史约束曾禁止 `srcq more` 和句柄状态；真实模型交互反例证明完整长命令仍把不必要的复制责任留给模型，因此本条不再约束当前周期。machine cursor 与 snapshot 仍保留，替代边界由 CON-003 定义。

## CON-002 安装与 Publish 不在本次范围

- 状态: superseded
- 来源: 用户 2026-08-22 已针对本次明确要求“改好，然后发布”

历史周期只允许仓库候选；当前周期已授权构建正式 srcq release、升级真实安装并向实际 Codex 根目录 Publish，仍不得把本次授权继承到以后发布。

## CON-003 机器 cursor 保持兼容且模型句柄不形成隐式全局状态

- 状态: confirmed
- 来源: 用户确认短句柄方向；并发与过期安全由方案推导

machine 的 `next_cursor`、显式 `--snapshot/--after` 和 cache/process 独立分页协议不变。不提供无参数“继续最后查询”，不使用可变的当前页指针；每个后继页分配不可变新句柄。句柄在受管保留周期内不得复用，过期、损坏或 snapshot 已淘汰时必须明确失败，不得误指另一查询、猜测恢复或重扫后端。
