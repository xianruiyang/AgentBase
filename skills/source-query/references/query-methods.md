# 查询方法

本页承接正文已经识别的查询缺口。按缺口选择适用方法，证据充分即返回，不逐级遍历工具。

- 普通文本或已知正文不足，需定义、引用、incoming/outgoing 调用或 workspace symbol 候选：先读 [symbol-relations.md](symbol-relations.md)，优先位置/限定名和默认限时范围；限时不等于无结果，证据充分即停止。
- 文本仍不能确定语法边界、控制流或结构关系，或明确需要 rule/rewrite：读取 [ast.md](ast.md)。
- 文本、AST 或 `srcq symbol` 候选后，仍有会改变结论的身份、重载、类型、精确引用、层级或 Provider 诊断歧义：定义、引用、调用或 workspace symbol 路径保留 [symbol-relations.md](symbol-relations.md) 并再读 [lsp.md](lsp.md)；已知位置只缺 Provider 诊断时只读 `lsp.md`。只发现当前缺失能力。

## 使用边界

- AST 无匹配后先取得会改变下一次查询的源码语法证据，否则回到文本路径；`srcq symbol` 不把候选冒充 Provider 精确语义，LSP 不重复文本、关系候选或 AST 已证明的事实。工具选择不创建写入或进程授权。
- 少量候选交给 LSP 核验，只有需要完整语义集合时才枚举。
