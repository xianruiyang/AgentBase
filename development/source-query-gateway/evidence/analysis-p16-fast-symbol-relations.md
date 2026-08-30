# P16 快速源码关系分析

## 职责

本文保存 2026-08-30 为 P16 设计提供依据、且重建成本较高的直接观察与边界。用户目标由 `requirements.md` 和 `user-design.md` 持有，模型设计由 `design.md` 持有，任务入口仍是 `plan.md`；本文不定义目标、接口或完成状态。

## 直接观察

1. 当前实际运行身份为 `srcq 0.4.3`、`ast-grep 0.44.1`。`srcq` 已有外部进程执行、AST JSON/YAML 适配、cache/process、rg 查询投影、分页和 model/machine 分面，但没有跨 backend 组合定义、引用或调用关系的公开命令。
2. UAI C++ 代表函数 `UUeAgentAddPrimitiveToolBuilder::CreateRampToolBuilder` 的可回滚 PowerShell 探针通过 `rg` 生成候选，以 AST 确认定义、函数内调用和候选所属外层函数。三次固定输入耗时平均 `2.654 s`，范围 `2.540–2.778 s`；同一当前 VS Code/cpptools 工作区的精确 Call Hierarchy 调用约 `57 s`。两者识别出相同 incoming caller `GetExtensionTools`，快速路径还返回直接语法调用 `NewObject<UUeAgentAddPrimitiveToolBuilder>()`。
3. 初版固定字符串候选曾把 `CanBuildTool` 中的子串误判为 `BuildTool`；改为标识符边界与调用括号后消除。`BuildTool` 没有直接文本 caller，但它是 virtual override，探针正确返回 `semantic-unknown: virtual-dispatch`，没有把未知解释为零引用。
4. 同一函数与调用概念在六种代表语言中的 Tree-sitter 节点不同：

   | 语言 | 函数定义 | 调用 | 局部变量定义 |
   | --- | --- | --- | --- |
   | C++ | `function_definition` | `call_expression` | `declaration/init_declarator` |
   | Python | `function_definition` | `call` | `assignment` |
   | TypeScript | `function_declaration` | `call_expression` | `lexical_declaration/variable_declarator` |
   | Rust | `function_item` | `call_expression` | `let_declaration` |
   | Go | `function_declaration` | `call_expression` | `short_var_declaration` |
   | Java | `method_declaration` | `method_invocation` | `local_variable_declaration/variable_declarator` |

   因此，能够解析 AST 不等于已经存在统一的符号、作用域或调用关系合同；只用一组公共 kind 会造成漏报或误报。
5. `ast-grep outline` 在 0.44.0 起作为 alpha preview 提供本地结构化 symbol/item/member JSON。本机实测它能在代表语言中提取函数、类型和部分顶层变量或字段，但不会列出函数内局部变量；官方合同也明确它不解析引用、类型、重载或调用图。它可作为定义候选和语言归一化输入，不能单独成为关系结论 owner。
6. 当前 ast-grep 官方内置语言表包含 26 种语言。HTML、CSS、JSON、YAML 等语言没有通用函数调用语义；“适配全部 AST 语言”必须表达为每种语言都具有显式 capability 与诚实的 `supported/candidate-only/not-applicable` 结果，而不是让所有命令返回同一种空集合。
7. GptProjectTest 的真实 C++ 配置证明当前工作区不等于查询所需源码范围：项目内 `.vscode/compileCommands_GptProjectTest.json` 的 UAI 编译项以 `D:/Epic Games/UE_5.6/Engine/Source` 为工作目录，并通过 `@...cpp.obj.rsp` 继续引用 `UeAgentInterfaceTests.Shared.rsp`；后者以 `Runtime/Core/Public`、`Runtime/Engine/Public` 等相对路径引入 UE 源码。`GptProjectTest.code-workspace` 还把项目根和 `D:\Epic Games\UE_5.6` 同时登记为 workspace folder。只扫描当前项目根会漏掉真实外部源码；只把编译工作目录当作一个无界递归根又会把整个引擎错误地视为当前查询必需范围。
8. C/C++ 编译数据库中的命令本身不足以恢复源码宇宙。MSVC 命令可递归引用响应文件，路径须按编译器对工作目录和响应文件引用的实际规则解析；缺失、循环或陈旧的响应文件，以及仅有二进制而没有源码的依赖，都会使范围不完整。编译项、响应文件、workspace 多根和显式查询根必须保留各自来源，不能合并成一个无法解释的目录列表。

官方依据：

- <https://ast-grep.github.io/reference/languages.html>
- <https://ast-grep.github.io/guide/outline-code>

## 结构判断

- 新能力属于 `tools/srcq` 的只读源码证据职责，不属于 VS Code Companion。VS Code/Language Provider 继续拥有编译器或语言服务支持的精确符号身份；快速关系结果是可分级的语法与候选证据。
- 正式查询应以源码位置作为唯一符号身份输入；纯名称只能得到候选集合。变量遮蔽、函数重载、成员类型和别名使“名称即符号”不成立。
- rg 适合完整生成词面候选，AST/outline 适合分类定义、声明、调用、作用域和外层 owner；两者都不能证明虚分派、函数指针、宏展开、模板实例化、动态语言绑定或跨语言生成关系。
- 查询范围应由可重建的源码宇宙解析结果持有，而不是由进程当前目录或单一 VS Code workspace 隐式决定。显式根、已有 workspace 多根、编译/响应文件、项目清单和语言依赖元数据提供不同强度的根证据；外部源码根必须能够参与同一次候选扫描，未解析依赖和缺失源码必须保持可见。
- 结果必须分别表达源码宇宙完整性、候选扫描完整性、语法分类确定性和符号身份确定性。只有已解析的适用源码根全部完成扫描，才允许在该范围内声明“无引用”；`扫描完整` 仍不得被序列化为 `精确引用完整`。
- 深度调用树只递归展开身份唯一的边；歧义边作为有原因的叶子返回。节点去重、循环检测、深度、节点数和边数预算用于控制证据规模，不裁决语义正确性。
- 不应为每种语言机械展开相同测试笛卡尔积。先按独立语法与解析失败机制选代表语言闭合，再为每个语言适配器生成最小 capability smoke；C++/UE 作为重载、虚调用、宏和大型工作区的高难度消费者，不作为语言合同本身。

## 当前开放设计问题

1. `ast-grep outline` 仍是 alpha 外部能力。P16 需先验证其 JSON 合同、缺失能力和版本降级，再决定定义候选是直接适配 outline，还是由 srcq 自有规则补足；当前证据不支持内嵌或分叉 ast-grep。
2. 需要冻结语言 capability 模型：解析、结构、位置符号、词法作用域、定义候选、引用候选、直接调用、跨文件导入、精确语义分别独立表达。
3. 需要裁决公开命令的最小表面。候选为 `srcq symbol definition|references|call-tree|capabilities`，但名称和参数只有在位置身份、范围、分页与 model/machine 输出闭合后才能确认。
4. 跨语言关系、框架生成代码和动态分派不属于第一条纵向闭环；它们必须显示为未决或升级 LSP/领域工具，不能由同名启发式静默吸收。
5. 需要冻结源码宇宙解析协议：显式范围与自动发现如何组合、编译数据库和嵌套响应文件如何解析、依赖源码与系统/生成目录如何分类、何时可声明范围完整，以及如何在不扫描整盘或默认启动构建系统的情况下覆盖 workspace 外源码。
