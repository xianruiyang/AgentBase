---
name: source-query
description: 仅在 srcq 分页或截断阻断当前必要证据，需诊断 srcq 当前能力、错误或降级是否为产品缺陷，需取得定义、引用或有界调用候选，需实际执行 AST rule/rewrite 或 srcq machine/native/artifact 与 scc 定向投影，文本仍不能确定完整语法边界或结构关系，或快速候选后真实符号语义仍有歧义时使用；AST 无匹配后尚缺能改变下一次查询的源码证据时先回到普通文本或有界读取，不触发本 skill；普通 rg/fd/scc、hyperfine、规则审查或工具名提及也不触发。
---

# Source Query

## 路由

只读取当前缺口对应的引用：

- 分页使必要结果尚未展示：query 的 `@more` 后直接执行 `@next` 提供的 `srcq more q<number>` 短命令，不改写句柄、不自行重组 cursor、控制面或原生 argv，也不读取引用；该句柄只是当前 spool 中的临时游标，不把旧句柄记录为持久引用。正文截断实际影响判断时先按已返回定位有界直读。缺少 `@next`、续页异常或明确需要特殊原生、machine/native/artifact 时，rg/fd 读取 [rg-fd.md](references/rg-fd.md)，scc 读取 [scc.md](references/scc.md)。
- 用户要求判断 srcq 是否缺少能力、错误返回或投影降级是否为产品缺陷，或当前失败会改变查询方案：读取 [diagnostics.md](references/diagnostics.md)，先核对实际版本、对应帮助和原命令，再区分输入、范围、正常协议、降级与产品机制。
- 实际需要 scc 的 files、hotspots、lossless、raw、machine、native、artifact、输出副作用边界或结构化续页：读取 [scc.md](references/scc.md)。
- 普通文本或已知正文不足，实际需要定义、引用或 incoming/outgoing 调用关系候选：读取 [symbol-relations.md](references/symbol-relations.md)，优先走位置/限定名和默认限时范围；限时返回不是无结果证据，快速结果充分即停止。
- 文本仍不能确定语法边界、控制流或结构关系，或明确需要 rule/rewrite：读取 [ast.md](references/ast.md)。
- `srcq symbol` 快速关系候选后仍有会改变结论的定义身份、重载、类型、精确引用、层级或 Provider 诊断歧义：读取 [lsp.md](references/lsp.md)，只发现当前缺失能力。

若上述条件均不成立，返回普通 `srcq fd` / `srcq rg` / `srcq scc` 或已知文件有界读取；普通命令基准直接使用 `hyperfine`；证据充分即停止，普通查询不为预防性了解工具调用 help、doctor 或 capabilities。

当前任务只审查本规则或其他查询规则、并未执行相应查询时，不读取引用。

## 运行与证据边界

- PATH 中的 `srcq.exe` 是 fd、rg、scc 与 AST 的唯一运行时；只有命令不可用或安装身份错误时返回安装、升级或重启宿主的恢复动作，不搜索项目构建目录、Skill、插件或 Codex 缓存中的私有副本。
- 全集、不存在或唯一结论只查询最近项目正式来源确定的权威范围；局部页不得外推，模型只传递短句柄，srcq 内部沿用同一 snapshot 和精确 cursor。
- AST 无匹配后先取得会改变下一次查询的源码语法证据，否则回到文本路径；`srcq symbol` 不把候选冒充 Provider 精确语义，LSP 不重复文本、关系候选或 AST 已证明的事实。工具选择不创建写入或进程授权。
