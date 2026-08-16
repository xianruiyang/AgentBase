---
name: source-query
description: 仅在 srcq 的分页或截断确实阻止当前必要证据、任务需要实际执行 AST rule/rewrite 或 srcq machine/native/artifact、文本证据仍不能确定完整语法边界或结构关系，或结论仍有真实定义身份、重载、类型、精确引用、层级或语言服务诊断歧义时使用；仅审查规则或提及工具名不触发。
---

# Source Query

## 路由

只读取当前缺口对应的引用：

- 分页使必要结果尚未展示：只有 `@more` 时保持 backend、cwd 和原生 argv，以 `srcq query <backend> exec --after <cursor> -- <原 argv...>` 沿回执续页，不读取引用；正文截断实际影响判断时先按已返回定位有界直读，无法恢复、续页异常或明确需要特殊原生、machine/native/artifact 才读取 [rg-fd.md](references/rg-fd.md)。
- 文本仍不能确定语法边界、控制流或结构关系，或明确需要 rule/rewrite：读取 [ast.md](references/ast.md)。
- 实际文本候选仍有定义身份、重载、类型、精确引用、层级或 Provider 诊断歧义：读取 [lsp.md](references/lsp.md)，只发现当前缺失能力。

若上述条件均不成立，返回普通 `srcq fd` / `srcq rg` 或已知文件有界读取；证据充分即停止，不为了解工具调用 help、doctor 或 capabilities。

当前任务只审查本规则或其他查询规则、并未执行相应查询时，不读取引用。

## 运行与证据边界

- PATH 中的 `srcq.exe` 是 fd、rg 与 AST 的唯一运行时；只有命令不可用或安装身份错误时返回安装、升级或重启宿主的恢复动作，不搜索项目构建目录、Skill、插件或 Codex 缓存中的私有副本。
- 全集、不存在或唯一结论只查询最近项目正式来源确定的权威范围；局部页不得外推，续页沿用同一 snapshot 和精确 cursor。
- AST 无匹配后先取得会改变下一次查询的源码语法证据，否则回到文本路径；LSP 不重复文本或 AST 已证明的事实。工具选择不创建写入或进程授权。
