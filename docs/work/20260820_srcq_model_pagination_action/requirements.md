# srcq 模型续页动作需求

## REQ-001 模型可以直接执行查询续页

- 状态: confirmed
- 来源: 用户 2026-08-20 选择“保留 cursor，并返回完整 `@next` 命令”，要求迭代到模型友好
- 关联: AC-001, AC-002, AC-003, UDES-001

当 `srcq query` 的 model 结果未展示完时，输出必须让正常同一轮中的 Codex 不需要回忆控制面语法或自行重组原命令，就能沿同一快照取得下一页。

## AC-001 页尾同时表达不完整事实和唯一下一动作

- 状态: confirmed
- 关联: REQ-001

截断页保留 `@more shown=<N> omitted=<N>` 完整性信号，并另给一条 `@next <command>`。`@next` 后的内容必须是 PowerShell 7 可直接执行的完整命令；`@more` 不再单独暴露会诱导错误拼接的 query cursor。

## AC-002 续页保持查询身份且不重扫原生后端

- 状态: confirmed
- 关联: REQ-001

命令必须保持 backend、cwd、显式引擎、影响分页的非默认 wrapper 值和原生 argv，并使用已有 snapshot cursor。参数中的空值、空白、PowerShell 元字符、引号、反引号、美元符号和控制字符不得改变；续页只能读取已持久化快照，不能再次执行原生 rg、fd 或 scc 查询。

## AC-003 真实独立 Codex 能完成正常续读

- 状态: confirmed
- 关联: REQ-001

使用已经修复网络、transport、sandbox 和真实 scc 预检边界的独立评估运行时：新鲜 Codex 取得第一页后，应执行 `@next` 提供的命令、成功取得第二页并识别第二页证据。命令事件必须证明 cursor、原生 argv 和原生扫描次数正确；最终回答不能替代工具事件。

## CON-001 cursor 仍是唯一查询续页状态

- 状态: confirmed
- 来源: 用户选择第一种方案；offset + length 方案未选择

不新增 offset/length 公共查询入口、`srcq more` 命令、第二份 argv 状态或原生重扫恢复。machine 的 `next_cursor`、既有 snapshot 生命周期和 cache/process 自身的分页协议不改变。

## CON-002 安装与 Publish 不在本次范围

- 状态: confirmed
- 来源: 用户此前暂停真实安装；项目要求 Publish 逐次授权

可以修改源码、skill、文档、测试，构建隔离候选并完成 Git 维护；不得升级真实 srcq 安装，也不得向实际 Codex 根目录执行 Publish。
