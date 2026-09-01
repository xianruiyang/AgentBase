# 快速源码关系

`srcq symbol` 在一个只读入口内组合 ripgrep 候选生成与 ast-grep 结构分类，用于低延迟取得定义候选、引用候选和有界调用树。它不实现编译器或 Language Provider，输出中的 `candidate`、`ambiguous` 与 `semantic-unknown` 是证据边界，不是精确语义的弱化文案。

每次调用都是独立进程，不依赖 VS Code、cpptools 或跨调用索引。默认一次查询共享 7500 ms 后端扫描预算，为范围解析、进程启动和输出保留到端到端 10 秒目标的余量；操作系统调度和存储状态不作绝对时延承诺。预算耗尽会终止当前后端进程树、退出 124，并明确报告结果不完整，不返回伪造的“未找到”；调用树已经取得根和部分节点时会保留它们并输出 `@cut reason=time-budget`。

## 命令

优先从源码位置发起；`PATH:LINE:COLUMN` 使用 0-based 行列：

```powershell
srcq symbol definition --at 'Source/Module/File.cpp:41:9'
srcq symbol references --at 'Source/Module/File.cpp:41:9'
srcq symbol calls --at 'Source/Module/File.cpp:41:9' --direction outgoing --depth 2
srcq symbol calls --at 'Source/Module/File.cpp:41:9' --direction incoming --depth 2
```

位置上的 `A::B` 静态限定名会直接保留为查询目标。C++ 成员调用会保留接收者；当当前函数内恰有一个在调用前声明的显式参数或局部变量类型时，输出 `Type::method [typed-member-candidate receiver=object:Type]` 并允许继续解析该候选。C# 还会使用当前词法块或 Lambda/local function 内有效的显式参数/局部变量、`var x = new Type(...)`、当前类型的字段/属性、跨 partial 文件的唯一字段/属性、短属性链及源码内唯一静态类型形成同等级的类型候选。

Go、Python、Rust、JavaScript、TypeScript/TSX 现在通过同一 typed relation 中间层取得语言等价证据：Go 使用方法 receiver、参数、`var`/`:=`、复合字面量和类型 selector；Python 使用 annotation、构造赋值、`self`/`cls` 与实例成员；Rust 使用参数/引用、`let`、struct/`new` 构造、`self`、字段和 inherent `impl` 路径；JavaScript 使用 `new` 局部/字段/构造赋值、当前实例和静态类调用；TypeScript/TSX 再增加显式参数、局部与字段类型。函数、方法、arrow/function expression、lambda、closure 等适用 callable 由各自 AST owner 归属；JavaScript、TypeScript/TSX 类方法还会从同批 AST class 范围取得调用者限定身份。相邻块的同名局部变量分别绑定，已经离开声明作用域的名称不继承旧类型，incoming 会排除已证明属于其他接收者类型的同名调用。不同类型的同名绑定、union 或复杂泛型、interface/trait object、`dynamic`、计算属性、函数值、宏/生成代码、monkey patch、返回值/索引器组成的复杂链及其他不能从当前源码直接证明的接收者仍保持 `semantic-unknown`，不会用猜测消除歧义。

只有名称时仍可查询，但名称只建立候选身份：

```powershell
srcq symbol definition 'Namespace::Type::Method'
srcq symbol references Method
```

`definition` 的 `--body auto` 在唯一小定义可落入当前模型预算时直接返回完整正文；大定义返回可直接执行的 `@body` 命令；多个定义只列紧凑候选。`references` 排除已识别的声明/定义位置，并按语言能力标记 `call`、`write` 或普通 `reference`。`calls` 只把函数、方法和其他可调用目标作为树节点；类、结构体和变量通过 `definition`/`references` 查询，显式接收者类型和变量名作为调用节点上下文返回，不伪装成调用边。调用树只递归展开唯一的直接或显式类型成员候选；重载、未解析成员分派、虚调用、函数值和其他动态关系保留为带原因的叶子。`--depth` 取 1–8，`--max-nodes` 与 `--model-token-budget` 分别限制遍历和模型输出，达到预算不表示不存在更多关系。

## 范围

目录可以省略。含 `--at` 时从文件所属项目解析；名称查询从 `--cwd` 或当前目录解析。C++ 会只读消费 `.code-workspace`、`compile_commands.json`、`.vscode/compileCommands*.json` 和嵌套 MSVC response file，恢复项目外的本地源码根。C# 会只读解析 `.sln`、Microsoft.NET.Sdk 系列 `.csproj`、默认 `Compile` 集、`Compile Include/Remove` 与 `ProjectReference`，把链接源码纳入范围并排除已移除或不属于解决方案的仓库文件；唯一项目图即使解析出零个 Compile 文件也保持完整空集，不会退回仓库扫描。未发现项目、不可识别的 `.sln`/`.slnx`、多个顶层 `.sln`、无锚点或同一锚点目录发现多个 `.csproj`、自定义 SDK、显式 MSBuild import、任一祖先 Directory.Build 输入、条件 item/property、会改变默认输出排除的属性、项目外 wildcard item 或超出项目/文件上限时报告 `scope=incomplete`，不会调用 MSBuild 或把近似集合标成 resolved。

TypeScript/TSX/JavaScript 只读消费 `tsconfig.json`/`jsconfig.json` references 和 `package.json` 的本地 file/link/workspace 引用；Rust 消费 Cargo workspace 与 path dependency；Go 消费 `go.work use` 和 `go.mod replace` 的本地路径；Python 消费 `pyproject.toml` 中可静态识别的 `src`、package-dir 与 path dependency。这些 resolver 只加入已经存在的本地目录，不读取 package cache、registry、site-packages 或 `node_modules`，不展开不受支持的 workspace glob；损坏、缺失或超出静态子集的元数据产生 scope issue 并令自动范围为 `incomplete`。所有项目解析都不会启动构建器、语言服务、包管理器、下载源码或扫描整盘。位于常见 `Source` 或 `src`/`include` 布局中的关系查询优先扫描对应源码树，避免把计划证据、分发副本或其他非源码文件当作生产关系。

范围覆盖可在同一命令调整：

```powershell
--add-root PATH    # 加入自动范围，可重复
--only-root PATH   # 只用这些文件或目录，可重复
--exclude PATH     # 排除根或子树，可重复
```

范围应匹配符号的实际可见性：`.cpp` 内 helper、匿名命名空间或 `static` 定义优先限定到文件，公开符号才扩大到持有它的模块或源码根。扩大范围会增加同名词法候选和解析成本，不会自动提高身份精度。

自动定义查询按锚点、项目与已解析依赖逐步扩展，找到充分候选后停止；树内递归只在项目/显式根和当前定义文件中继续，避免一个外部库调用把整个 SDK 变成隐式扫描。自动引用和 incoming 查询也优先使用源码树；只有 machine/model 报告 `candidate_scan=complete` 或 `scan=complete` 时，结果才覆盖全部选中根。`prioritized` 表示当前候选有效但仍有已解析根未扫描；需要选定范围全集时使用 `--only-root` 明确边界。

C++ incoming 直接复用 AST 已确认的包含函数定义继续展开，不再只按 caller 短名跨文件重新选择；这消除了其他文件同名函数造成的无谓歧义。调用点仍是所选范围内的词法候选，宏、函数值、重载或动态分派会改变结论时仍需交给 Provider 核验。

默认预算内未闭合时按以下顺序恢复：已有位置直接 `--at`；名称未知位置时先用有界 `srcq rg` 在权威项目或模块内取得位置/静态限定名；再用 `--only-root` 选择当前源码树或编译配置确认的外部模块。调用树先取 `--depth 1`，高扇出节点需要更深关系时从已返回的子节点位置继续；只有必须一次取得更宽或更深的整体且无法收窄时才提高 `--time-budget-ms`，并显式放弃 10 秒快速路径。输入、范围和机制未变时不得只为期待不同结果而重跑。

## 语言与证据

`srcq symbol capabilities` 是语言能力真源，正常查询不需要预先调用。当前适配分为：

- C++：结构直接定义、词法引用候选和有界调用候选，并恢复编译范围。
- C#：outline 定义候选、词法引用候选和调用候选；显式源码类型可收窄成员调用，并恢复解决方案的静态 Compile 范围。
- Go、Python、Rust、JavaScript、TypeScript、TSX：outline 定义候选、词法引用候选和调用候选；语言等价的显式类型、构造、当前接收者、字段或静态限定可收窄成员调用，并恢复可静态识别的本地项目元数据范围。
- C、Java：outline 定义候选、词法引用候选和调用候选。
- Kotlin、PHP、Ruby、Swift：outline 定义候选。
- Bash、Dart、Elixir、Haskell、Lua、Nix、Scala、Solidity：已登记但当前 `unadapted`。
- CSS、HTML、JSON、YAML：源码符号关系 `not-applicable`。

所有名称查询、非 C++ outline 定义、引用及调用关系都不宣称 Provider 精度。C 原型、宏和条件编译，C# 重载、扩展方法、别名绑定、继承/接口分派及动态调用都不会因静态类型候选而被提升为精确关系；partial 只在唯一可定位的显式成员类型链内合并证据，不等同编译器绑定。当前 C# 限定名只完整覆盖 file-scoped namespace 与已建模类型范围；同一文件中的多个或 block-scoped namespace 不能稳定恢复完整限定名时保持候选/歧义。当前 0.44.1 证据覆盖 outline 定义、标识符词法引用、直接/成员/构造调用候选以及上述 C# 类型收窄。位置落在定义名称上时可选择该语法定义；位置落在调用或引用上且语法无法区分同名符号时仍返回歧义。只有该歧义会改变当前动作或结论时，才升级到 LSP 或领域工具。

## 输出

model 位置使用 1-based 行列，省略正常机器 envelope；范围未完整、身份歧义、动态关系和预算边界会保留最短诊断。`--output machine` 使用 0-based 行列和稳定 JSON：

调用树把证据标签放在树头的 `evidence=` 与节点方括号中；方括号由“解析状态；调用形式”和可选接收者上下文组成：

| 内容 | 含义 |
| --- | --- |
| `position-candidate` | 根目标由给定源码位置选中；只出现在树头的 evidence，不是子节点调用形式 |
| `qualified-candidate` | C++ 候选已唯一解析到源码中的限定定义；仍不等同编译器最终绑定 |
| `outline-candidate` | 非 C++ 候选已唯一解析到当前语言的结构定义 |
| `lexical-candidate` | incoming 调用者来自所选范围内的词法引用与包含函数关系 |
| `direct-candidate` | 源码直接写出了名称或静态限定调用，可继续尝试解析唯一源码定义 |
| `typed-member-candidate` | 成员调用具有唯一的显式源码接收者类型；C++ 使用函数内词法类型，C# 还可使用唯一字段/属性、partial 短链或源码静态类型；Go/Python/Rust/JavaScript/TypeScript/TSX 使用各自可直接证明的类型、构造、当前接收者、字段或静态限定，并按 `Type::method` 继续解析 |
| `member-candidate` | 观察到成员调用，但接收者类型不能由当前源码直接唯一证明 |
| `unknown` | 调用表达式过于间接，连可稳定查询的直接名称或成员形式也未取得 |
| `incoming-candidate` | 该节点是当前节点的调用者，位置是这条 incoming 调用边的调用点 |
| `semantic-unknown` | 当前源码证据不能确定唯一语义身份 |
| `ambiguous:N` | 找到 `N` 个适用定义候选，不能选择一个继续展开 |
| `cycle` | 继续展开会回到当前递归链中的既有定义 |
| `time-budget` | 解析该节点时耗尽查询预算，后续关系不完整 |
| `semantic-unknown:virtual-dispatch` | 观察到虚分派能力，但静态源码扫描不能枚举真实动态调用者 |
| `receiver=name:Type` | 接收者变量及唯一显式词法类型 |
| `receiver=name:unknown` | 保留接收者文本，但其类型未被当前证据证明 |

方括号只显示一份相同值；状态与调用形式不同时用分号连接，例如 `[qualified-candidate;direct-candidate]` 表示直接调用已唯一解析到一个 C++ 源码定义，`[semantic-unknown;member-candidate receiver=Worker:unknown]` 表示成员调用存在但接收者类型和唯一目标仍未知。

model 调用树会压缩同一父节点下完全相同的调用点路径：若该路径已出现在父节点行，子节点只显示 `:line:column`；否则第一个有位置的子节点显示完整 `path:line:column`，其余同路径兄弟节点只显示 `:line:column`。缩写只继承同一父节点下已经显示的路径，不跨父节点推断。machine 视图的每个 `call.path` 始终保留完整路径。

- `srcq.symbol.definition/v1`
- `srcq.symbol.references/v1`
- `srcq.symbol.calls/v1`
- `srcq.symbol.capabilities/v1`

调用节点的 `qualified_name`、`receiver` 与 `receiver_type` 是可空字段：`name` 保持调用者短名，`qualified_name` 只在 AST 外层类型或已解析定义直接证明限定身份时出现，model 树优先显示该限定名；`receiver` 保存源码中的成员接收者，`receiver_type` 只在上述显式源码类型链唯一时出现。它们不证明别名展开、模板实例化、重载选择、扩展方法、继承分派或运行时类型。

定义候选存在时退出 0，无定义候选退出 1；输入、引擎、转换与 I/O 故障使用 srcq 的 120–127 错误域。关系命令不写源码，也不把自动发现结果持久化为第二范围真源。
