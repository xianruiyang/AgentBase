---
name: source-query
description: 用于 srcq 必要结果的分页恢复、缺陷诊断、特殊输出/统计投影，或 rg/fd 配合定向阅读仍难以解决的源码查询。普通 rg/fd/scc、有界文件读取、hyperfine、规则审查不触发；找定义、查调用或匹配较多本身不构成升级理由。
---

# Source Query

## 路由

只读取当前缺口对应的引用：

- 分页使必要结果尚未展示：query 的 `@more` 后直接执行 `@next` 给出的 `srcq more q<number>`，不读引用、不改写临时句柄、不重组 cursor、控制面或原生 argv，也不持久记录句柄。正文截断影响判断时按已返回定位有界直读。缺少 `@next`、续页异常或需要特殊原生、machine/native/artifact 时，rg/fd 读 [rg-fd.md](references/rg-fd.md)，scc 读 [scc.md](references/scc.md)。
- 需判断 srcq 能力、错误或投影降级是否为产品缺陷，或失败会改变查询方案：读 [diagnostics.md](references/diagnostics.md)，先核对版本、对应帮助和原命令，再区分输入、范围、正常协议、降级与产品机制。
- 实际需要 scc 的 files、hotspots、lossless、raw、machine、native、artifact、输出副作用边界或结构化续页：读取 [scc.md](references/scc.md)。
- rg/fd 配合定向阅读仍难以解决当前问题，且剩余缺口会影响结论时，读 [查询方法](references/query-methods.md)。先根据缺口判断是否需要升级，不为证明文本方法不足而重复查询；路径错误、正常分页或已定位但尚未读完的正文，先沿原查询路径解决。

否则返回普通 `srcq fd` / `srcq rg` / `srcq scc` 或已知文件有界读取；命令基准直接用 `hyperfine`。普通查询不为预防性了解工具调用 help、doctor 或 capabilities。

当前任务只审查本规则或其他查询规则、并未执行相应查询时，不读取引用。

## 运行与证据边界

- PATH 中的 `srcq.exe` 是 fd、rg、scc 的唯一运行时；只有命令不可用或安装身份错误时返回安装、升级或重启宿主的恢复动作，不搜索项目构建目录、Skill、插件或 Codex 缓存中的私有副本。
- 全集、不存在或唯一结论只查询最近项目正式来源确定的权威范围；局部页不得外推，模型只传递短句柄，srcq 内部沿用同一 snapshot 和精确 cursor。
- 工具选择不创建写入或进程授权。
- 符号范围按实际可见性选择：文件内 helper 限定文件，公共符号才扩大到模块/正式源码根。
