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

`--at` 会保留可从源码直接观察到的 `A::B` 限定名。C++ `object.method` 在当前函数内存在唯一、显式且先于调用的参数或局部变量类型时，保留 `receiver=object:Type` 并形成 `typed-member-candidate`。C# 还可从当前词法块或 Lambda/local function 内有效的显式参数/局部、`var = new`、字段/属性、跨 partial 的唯一成员、短属性链和源码静态类型形成同等级候选，并用已证明的接收者类型排除其他类型的同名 incoming；离开声明作用域的名称、`dynamic`、扩展方法、重载和复杂链仍保持未知。这些都只是源码候选，不外推别名、模板实例化或运行时类型。位置是定义或静态限定调用时，优先直接查询，不先做全仓名称扫描。

没有位置才按名称查询，并把结果保持为候选。正常查询不先调用 help、doctor 或 capabilities；当前语言报 `unadapted`/`not-applicable`，或需要 machine 消费时才读取对应能力或改用 `--output machine`。

## 范围与结论

- 目录默认省略；工具从位置或 cwd 解析项目。C++ 还消费 workspace、编译数据库和 response file；C# 消费 `.sln`、Microsoft.NET.Sdk 系列 `.csproj`、Compile Include/Remove 和 ProjectReference，已解析的空 Compile 集不会退回仓库扫描；无项目、不可识别 solution/自定义 SDK、多解决方案/无锚点或同目录多项目、条件、任一祖先 Directory.Build、显式 import、影响默认排除的属性、项目外 wildcard item 或数量上限无法静态展开时返回 `scope=incomplete`。两者都不启动构建或扫描整盘。
- `--add-root` 追加自动范围，`--only-root` 替换范围，`--exclude` 排除根或子树，均可重复。
- 范围按符号真实可见性选择，而不是默认取整个仓库：`.cpp` 内 helper、匿名命名空间、`static` 定义或只需证明一个消费者时先 `--only-root <file>`；公开函数、类型和跨文件变量才扩大到持有它的模块/源码根。需要 UE/SDK 等工作区外定义时，只加入编译配置或正式项目来源确认的外部根。
- `scan=prioritized` 只证明已扫描部分中的候选；全集或不存在结论需要权威源码范围和适用根全部扫描。显式 `--only-root` 只证明该选定范围。
- 唯一小定义会直接带正文；大定义执行返回的 `@body`，多候选先按位置或范围消歧，不批量读取全部正文。
- 调用树只包含函数、方法和其他可调用节点；类、结构体、字段和变量用 `definition`/`references` 查询，显式接收者类型和变量名只作为调用节点上下文。树只递归唯一的直接或显式类型成员候选；`ambiguous`、`semantic-unknown`、虚调用、未解析成员分派、循环或预算叶子不能解释为没有关系。
- model 调用树的方括号先给解析状态，再以分号给不同的调用形式，并可附 `receiver=name:Type|unknown`；`candidate` 均是源码证据边界，不等同编译器最终绑定。同一父节点的调用点路径完全相同时只显示一次，后续 `:line:column` 只继承该父节点下已显示的路径；machine 的每个 `call.path` 仍完整保留。

## 10 秒快速路径

`srcq symbol` 每次启动独立进程，不等待 VS Code 或 cpptools 建索引。默认一次关系查询共享 7500 ms 扫描预算，为项目解析、进程启动和输出保留余量；预算耗尽时退出 124 并明确说明结果不完整，不能据此声明不存在定义、引用或调用。调用树已取得根和部分节点时会保留它们并输出 `@cut reason=time-budget`。

按以下成本顺序恢复，不无条件加长超时：

1. 已有源码位置就使用 `--at`；只有名称时，先用一次有界 `srcq rg` 在权威项目/模块范围定位定义或静态限定调用，再把位置交给 `srcq symbol`。
2. 自动范围仍超时时，用 `--only-root` 选择当前项目源码树、模块或由编译配置确认的外部模块；需要全集结论时明确列出全部权威根。
3. 调用树先取 `--depth 1`，当前路径需要下一层才取 depth 2 或从明确函数继续；C++ incoming 复用已观察到的 caller 定义，不因其他文件同名 caller 重新选名。高扇出节点不逐一扩大，只有必须取得更深整体且无法按节点收窄时才提高预算。
4. 只有当前判断确实依赖更宽范围、且无法再按模块收窄时，才显式提高 `--time-budget-ms`；这一步放弃 10 秒快速路径，不能成为普通默认。

同一输入和范围限时后不原样重跑。缩小范围、改用限定名/位置或明确提高预算，才是会改变结果的有效变化。

若快速结果已经足以支持当前动作就停止。少量候选只需判同一身份时用 LSP `verify_symbol_candidates`，需要范围内完整精确引用才用 `get_references`；重载或动态调用确实改变动作时才查 Provider 层级，空树不能推翻源码调用候选。具体边界见 [lsp.md](lsp.md)。
