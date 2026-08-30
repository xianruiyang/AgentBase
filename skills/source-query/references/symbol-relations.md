# 快速符号关系

仅在需要定义、引用或调用关系候选，且普通文本或已知正文不足以完成当前判断时读取。

## 最小调用

优先使用源码位置；输入是 0-based 行列，model 定位是 1-based：

```powershell
srcq symbol definition --at '<path>:<line>:<column>'
srcq symbol references --at '<path>:<line>:<column>'
srcq symbol calls --at '<path>:<line>:<column>' --direction outgoing --depth 2
srcq symbol calls --at '<path>:<line>:<column>' --direction incoming --depth 2
```

`--at` 会保留可从源码直接观察到的 `A::B` 限定名；它不推断 `object.method` 的运行时类型。位置是定义或静态限定调用时，优先直接查询，不先做全仓名称扫描。

没有位置才按名称查询，并把结果保持为候选。正常查询不先调用 help、doctor 或 capabilities；当前语言报 `unadapted`/`not-applicable`，或需要 machine 消费时才读取对应能力或改用 `--output machine`。

## 范围与结论

- 目录默认省略；工具从位置或 cwd 解析项目，C++ 还消费 workspace、编译数据库和 response file，但不启动构建或扫描整盘。
- `--add-root` 追加自动范围，`--only-root` 替换范围，`--exclude` 排除根或子树，均可重复。
- `scan=prioritized` 只证明已扫描部分中的候选；全集或不存在结论需要权威源码范围和适用根全部扫描。显式 `--only-root` 只证明该选定范围。
- 唯一小定义会直接带正文；大定义执行返回的 `@body`，多候选先按位置或范围消歧，不批量读取全部正文。
- 调用树只递归唯一候选；`ambiguous`、`semantic-unknown`、虚调用、成员分派、循环或预算叶子不能解释为没有关系。

## 10 秒快速路径

`srcq symbol` 每次启动独立进程，不等待 VS Code 或 cpptools 建索引。默认一次关系查询共享 7500 ms 扫描预算，为项目解析、进程启动和输出保留余量；预算耗尽时退出 124 并明确说明结果不完整，不能据此声明不存在定义、引用或调用。调用树已取得根和部分节点时会保留它们并输出 `@cut reason=time-budget`。

按以下成本顺序恢复，不无条件加长超时：

1. 已有源码位置就使用 `--at`；只有名称时，先用一次有界 `srcq rg` 在权威项目/模块范围定位定义或静态限定调用，再把位置交给 `srcq symbol`。
2. 自动范围仍超时时，用 `--only-root` 选择当前项目源码树、模块或由编译配置确认的外部模块；需要全集结论时明确列出全部权威根。
3. 调用树先取 `--depth 1`；高扇出节点需要更深关系时，从已返回的子节点位置继续一次查询，不让大量子节点逐一扩大。只有必须一次取得更深整体、且无法按节点收窄时才提高预算。
4. 只有当前判断确实依赖更宽范围、且无法再按模块收窄时，才显式提高 `--time-budget-ms`；这一步放弃 10 秒快速路径，不能成为普通默认。

同一输入和范围限时后不原样重跑。缩小范围、改用限定名/位置或明确提高预算，才是会改变结果的有效变化。

若快速结果已经足以支持当前动作就停止。只有重载、类型、动态分派、跨文件绑定或真实身份歧义会改变结论时，再读取 [lsp.md](lsp.md) 并只发现一个必要 Provider 能力。
