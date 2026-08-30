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

没有位置才按名称查询，并把结果保持为候选。正常查询不先调用 help、doctor 或 capabilities；当前语言报 `unadapted`/`not-applicable`，或需要 machine 消费时才读取对应能力或改用 `--output machine`。

## 范围与结论

- 目录默认省略；工具从位置或 cwd 解析项目，C++ 还消费 workspace、编译数据库和 response file，但不启动构建或扫描整盘。
- `--add-root` 追加自动范围，`--only-root` 替换范围，`--exclude` 排除根或子树，均可重复。
- `scan=prioritized` 只证明已扫描部分中的候选；全集或不存在结论需要权威源码范围和适用根全部扫描。显式 `--only-root` 只证明该选定范围。
- 唯一小定义会直接带正文；大定义执行返回的 `@body`，多候选先按位置或范围消歧，不批量读取全部正文。
- 调用树只递归唯一候选；`ambiguous`、`semantic-unknown`、虚调用、成员分派、循环或预算叶子不能解释为没有关系。

若快速结果已经足以支持当前动作就停止。只有重载、类型、动态分派、跨文件绑定或真实身份歧义会改变结论时，再读取 [lsp.md](lsp.md) 并只发现一个必要 Provider 能力。
