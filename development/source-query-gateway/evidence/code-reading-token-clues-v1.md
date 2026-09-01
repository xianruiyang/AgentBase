# 代码读取 Token 机制与优化线索 v1

## 1. 职责与证据边界

本文件保存现有源码读取实验的二次机制审计，供后续候选设计、实验裁决和 runner 观测设计复用；它不创建新的运行规则、工具入口或发布授权，也不把机制解释伪装成逐请求账单。

直接输入包括：

- [代码读取策略审计](audit-result-code-reading-strategy-v1.json)及其登记的 C#、C++、TypeScript experiment identity；
- 最终 TypeScript 配对探针 `d83f0dd9039447954b37eb67f33e60efba05d52906a1fca34e773add20d65519` 的原始 JSONL、summary 与 capsule；
- [跨语言配对审计](audit-result-cross-language-v11.json)及对应 C++/TypeScript 原始 JSONL；
- JSONL 中的 `turn.completed.usage`、command 顺序和每条 command 的一次性可见输出。

可见文本 Token 使用 `tiktoken` 的 `o200k_base` 对每条 command 输出各计一次，用于比较模型实际取得的工具正文；正式成本仍以 `turn.completed.usage` 和实验 identity 冻结的价格系数为准。现有事件只提供整次 subject 聚合 usage，不提供逐采样请求 usage，因此交互轮次和上下文复用只能做结构性归因，不能还原精确账单。

## 2. 最终 TypeScript 配对探针

两侧均使用 `gpt-5.6-luna`、medium、default、WebSocket、只读工作区、禁用子代理和 `srcq 0.6.0`；唯一目标差异是源码读取 skill 策略及其对应路由行。所有命令 exit 0，usage 完整，postflight 无失败。

| 指标 | control | candidate | candidate 变化 |
| --- | ---: | ---: | ---: |
| command 数 | 2 | 6 | +4 |
| 由 command 链推得的采样轮次结构估计 | 3 | 7 | +4 |
| 一次性可见 command 输出 | 73,339 bytes / 18,225 Token | 34,438 bytes / 8,450 Token | -53.043% bytes / -53.635% Token |
| input Token | 72,917 | 147,392 | +74,475 |
| cached input（input 子集） | 40,448 | 133,376 | +92,928 |
| ordinary input | 32,469 | 14,016 | -18,453 |
| output Token | 1,197 | 2,886 | +1,689 |
| reasoning output（output 子集） | 617 | 1,255 | +638 |
| visible output | 580 | 1,631 | +1,051 |
| actual total Token | 74,114 | 150,278 | +76,164（+102.766%） |
| elapsed | 33,771 ms | 76,161 ms | +125.522% |
| 短上下文价格等价量 | 43,695.8 | 44,669.6 | +973.8（+2.229%） |
| 长上下文价格等价量 | 83,800.6 | 80,681.2 | -3,119.4（-3.722%） |

短上下文价格复算为：

- control：`32469 × 1 + 40448 × 0.1 + 1197 × 6 = 43695.8`；
- candidate：`14016 × 1 + 133376 × 0.1 + 2886 × 6 = 44669.6`。

长上下文价格复算为：

- control：`32469 × 2 + 40448 × 0.2 + 1197 × 9 = 83800.6`；
- candidate：`14016 × 2 + 133376 × 0.2 + 2886 × 9 = 80681.2`。

candidate 的一次性工具正文比 control 少 9,775 Token，但聚合 input 反而多 74,475 Token。这直接否定“一次性工具正文更短即可推出端到端 Token 更低”。candidate 的 `source-query` 与 `powershell-usage` skill 正文合计约 2,083 Token，仅相当于总增量的 2.735%；skill 是改变后续轨迹的上游因素，但文件正文大小不是主要增量。

按 command 完成后进入下一次模型采样的顺序做结构性复算，control 的工具结果复现量约 31,281 Token、command 文本复现量约 234 Token，扣除后仍有 41,402 input Token；candidate 分别约 30,775 和 2,853，其中 skill 输出后续复现约 11,474 Token，扣除 command/工具复现后仍有 113,764 input Token。两侧未解释 input 相差约 72,362 Token，平均到四个额外交互轮次约 18,091 Token/轮；该差额还混有系统/开发者/AGENTS/用户指令、工具 schema、结构化包装和模型已生成上下文，不能解释为某一固定前缀的精确成本。

control 的链路是两次文本查询后回答；candidate 依次读取 `source-query`、查询锚点、读取 `powershell-usage`、执行两批正文窗口、再补一次文本查询后回答。candidate 仍遗漏 `getSessions` 初始化、`sessionSelected=null` 清理和源码证据不能证明 VS Code 传输/运行时投递的限定，因此更多轮次同时增加成本，却没有取得完整质量。

## 3. 跨语言重复观察

早先冻结的跨语言配对身份出现同方向机制：

| Case | command 数 control → candidate | 一次性工具输出 Token control → candidate | input Token control → candidate | 观察 |
| --- | ---: | ---: | ---: | --- |
| C++ | 6 → 11 | 11,365 → 7,479 | 159,169 → 237,040 | candidate 增加 fd/help/分页/宽搜和定向补查；工具正文更少但 input 更高 |
| TypeScript | 3 → 4 | 16,099 → 7,856 | 91,850 → 108,818 | candidate 增加完整文件、定向搜索、`srcq rg --help` 与补查；工具正文更少但 input 更高 |

这些结果与最终探针共同支持“交互轮次放大固定与历史上下文成本”的机制解释，但各身份的任务、规则和调用链不同，不能从三项观察推导每增加一次 command 的统一 Token 系数。

## 4. 可复用的优化线索

| 线索 | 当前证据强度 | 后续设计含义 |
| --- | --- | --- |
| 优先减少需要模型重新决策的工具交互轮次 | 三个配对 case 同方向，最终 TS 候选只改变策略且总 Token 翻倍 | 优化完整决策链，不以单条 stdout 或单次调用为目标 |
| 一次有界批量取得已知必要证据，可能优于多轮逐步窄查 | control 以更大一次性正文和更少轮次取得更低总成本；尚未单独隔离批量机制 | 已知文件、锚点和有限范围时允许一次批取；未知规模仍先限界 |
| 高级查询必须替代后续步骤，而不能叠加在同样的 rg/正文读取之前 | candidate 多次出现 skill/高级入口后仍执行原有文本链 | 晋级前证明它实际消除哪些后续采样、失败或回退 |
| 普通文件和文本任务保留低固定成本路径，按证据缺口升级 AST/symbol/LSP | 历史 P9/P10 与本轮 skill 候选反例一致 | 已知正文直读；文本足够即停止，不为形式完整提高证据层级 |
| 稳定最小语法或正式模板应消除任务内 `--help` 探索 | C++/TS 候选均出现 help 或错形恢复成本 | 只固化跨任务稳定的最小调用边界，不把微观命令配方扩散进常驻规则 |
| 输出压缩必须连同模型轮次、缓存读取和输出 Token 一起评估 | 最终 TS 工具正文减半但总 Token +102.766%，短价格仍上升 | 用 aggregate usage 与价格等价量验收，stdout 字节和工具调用数只解释机制 |
| skill 的主要风险是诱发额外轨迹，不只是正文固定成本 | 直接 skill 正文约占总增量 2.735%，其后出现四个额外交互轮次 | skill 保持窄触发；普通路径不预读高级说明；审计触发后的真实动作链 |
| 机械且无需新判断的多锚点搜索、窗口读取和分页可由一个正式入口合并 | 当前为机制性推断，尚无独立 A/B | 只有能保持范围、完整性、失败语义和恢复能力时才实验，不先新增入口 |
| 价格优先看 ordinary/cached/output 分项，不只看总 Token | 最终 TS 总 Token 翻倍但长价格下降、短价格上升 | 缺少逐请求上下文分类时同时报告短/长场景；reasoning 是 output 子集，不重复计费 |

## 5. 未证结论与后续观测缺口

当前证据不能推出：

- 所有任务都应机械减少工具调用；必要调用仍可能是完整质量的最低成本路径；
- `rg` 总是优于 symbol/AST，或高级查询没有价值；只有能替代后续链路时才可能形成净收益；
- 每增加一次 command 固定增加约 18K Token；该数字只是最终 TS 身份中的未解释 input 均摊；
- 删除某段全局规则必然节省确定 Token；常驻上下文的重复成本机制合理，但尚未被独立 A/B 隔离；
- 长上下文价格场景下降即可采纳最终 TS candidate；其完整质量失败，且现有 runner 不能恢复每个请求实际属于短或长上下文档位。

若下一次需要精确定位成本，runner 应在 Codex 事件能力允许时记录每次采样请求的 ordinary input、cache read、cache write、output/reasoning、前置 tool item 映射和请求上下文档位；能力不存在时必须继续把归因标为结构性估计，不伪造逐 command 账单。新的读取策略候选仍须逐 case 先通过完整质量，再严格降低适用价格等价量；一个反例即停止扩量。

## 6. 2026-09-01 交互轮次机制探针 A

实验 `8ca84971bd48216a8d8d692d5fb58fcf36e5ecfb725534839fa578e5125fa446` 只选择 TypeScript `opencode-webview-message-boundary`，使用 `gpt-5.6-luna`、medium、default、WebSocket、只读工作区、禁用子代理和两侧相同的 `srcq 0.6.0`。preflight 与 postflight 均通过，环境树唯一差异是 candidate `AGENTS.md` 增加一条通用策略：多个已知文本谓词先形成清单，再用同一 `srcq rg` 的重复 `-e` 与 `-C` 一次取得有界上下文，只有缺项、截断或结论歧义才补查。原始结果位于 `C:\Users\gzxt\AppData\Local\AgentBase\code-search-experiments\interaction-rounds-luna-m-20260901-01\ts-first`；detached capsule SHA-256 为 `0ef6b83b00a66b9041deb4eef41a87016aadac5c2b1ad0fa290e4b3888a73a18`。

| 指标 | control | candidate | candidate 变化 |
| --- | ---: | ---: | ---: |
| command / agent message | 3 / 2 | 3 / 2 | 不变 |
| 一次性可见工具正文（`o200k_base`） | 9,768 Token | 14,144 Token | +44.799% |
| input / output Token | 90,208 / 1,424 | 100,581 / 1,748 | +11.499% / +22.753% |
| actual total Token | 91,632 | 102,329 | +11.674% |
| 短 / 长价格等价量 | 42,304 / 80,336 | 50,013 / 94,782 | +18.223% / +17.982% |
| elapsed | 42,654 ms | 44,142 ms | +3.489% |

candidate 第一条仍使用宽锚点和 `-C 3`，随后以 `-C 100` 读取大窗口并第三次补查；它没有执行重复 `-e` 的完整清单批取，也没有减少 command。独立 capsule 审计还确认两侧答案都未明确说明两个处理器的不同文件/作用域身份、`sessionSelected` 空值清理和源码证据不证明 VS Code 传输/运行时交付，candidate 因而未通过完整质量。

该反例推翻“增加一条单阶段静态批取建议即可减少交互轮次”，没有推翻“在证据等价且轮次真实减少时可能降低成本”，因为操纵变量没有实际发生。后继候选不得原样重跑；最低信息增益方向是把未知谓词任务改为“两阶段索引→一次批量正文”：首次只枚举当前任务实际需要的定义、调用、分支或注册锚点与行号，第二次把已发现锚点合成一次有界上下文查询，除明确截断或缺少用户要求的事实外停止。该方向仍须新的独立 identity 先证明真实 command 数下降和完整质量，再讨论成本收益。

## 7. 2026-09-01 交互轮次机制探针 B

实验 `198016c24bdb2192fadd7c5a0d72fc0320c3414ef98159327ac656914ecfdfca` 在同一 TS case、模型、srcq、只读和单差异边界下，把候选改为强制“两阶段索引→一次批量正文”；preflight/postflight 和网络均有效，detached capsule SHA-256 为 `9327638e9e7e6a85268ecdfc54318fd3d1ec5f1be8c3fc4924950ddf6148eca9`。原始结果位于 `C:\Users\gzxt\AppData\Local\AgentBase\code-search-experiments\interaction-rounds-luna-m-20260901-02\ts-first`。

| 指标 | control | candidate | candidate 变化 |
| --- | ---: | ---: | ---: |
| command / agent message | 5 / 2 | 11 / 2 | +6 / 不变 |
| 一次性可见工具正文（`o200k_base`） | 10,332 Token | 8,689 Token | -15.902% |
| input / output Token | 91,952 / 1,487 | 260,870 / 2,396 | +183.702% / +61.130% |
| actual total Token | 93,439 | 263,266 | +181.752% |
| 短 / 长价格等价量 | 43,504.4 / 82,547.8 | 84,935.6 / 162,683.2 | +95.235% / +97.078% |
| elapsed | 40,631 ms | 70,151 ms | +72.654% |

candidate 的前两条命令符合索引与批取形状，但第二条默认 model 页返回临时续页；随后产生 6 次 `srcq more`、两次同类 Provider 补查和一次 App 分支补查。它的一次性可见工具正文比 control 少 15.902%，聚合 input 却多 183.702%，进一步支持“较短工具正文不能抵消额外交互轮次”的原线索。独立审计确认 candidate 还缺 `sessionSelected` 空值清理和源码证据不证明传输/运行时交付，质量与两种价格均失败。

这次反例推翻“只规定两阶段即可得到两次模型工具交互”；被推翻的直接原因不是 `srcq` 缺少恢复协议，而是默认 80 个证据单元硬页上限使一次宽批取转成模型逐页动作。对同一第二阶段 argv 的无模型定向探针显示：只提高 `--model-token-budget 12000` 仍返回 `@more shown=80 omitted=389`；同时设置 `--limit 1000 --model-token-budget 12000` 后完整返回且无 `@more/@cut`。因此现有 0.6.0 控制面具备单次大页能力，后继仅剩一个有新增判别信息的静态候选：两阶段第二步显式使用该控制面，并在回答前核对用户事实清单和源码语义边界；若仍不能真实降低 command、完整质量和两种价格，则停止规则层实验。

## 8. 2026-09-01 交互轮次机制探针 C 与总体裁决

[三候选结构化审计](audit-result-interaction-rounds-v1.json)登记了完整 identity、capsule、raw root、质量、usage、价格与停止理由。最终实验 `081059d7871752f250d40fe21f4edc016dfc9f28d03ee1ffa8f6f9a63aad24bb` 使用“两阶段 + 显式 `--limit 1000`/`--model-token-budget 12000` + 回答清单”；preflight/postflight 有效，detached capsule SHA-256 为 `8c8d47be12ed2eecbf2c13a503c0b7815698d4137136a695fe656fb953a8dbb9`。

| 指标 | control | candidate | candidate 变化 |
| --- | ---: | ---: | ---: |
| command / failed command | 3 / 0 | 3 / 1 | command 不变，candidate 多 1 次失败 |
| 一次性可见工具正文（`o200k_base`） | 16,067 Token | 9,684 Token | -39.727% |
| input / output Token | 92,185 / 1,570 | 83,985 / 1,655 | -8.895% / +5.414% |
| actual total Token | 93,755 | 85,640 | -8.656% |
| 短 / 长价格等价量 | 47,921.8 / 91,133.6 | 35,854.2 / 66,743.4 | -25.182% / -26.763% |
| elapsed | 40,924 ms | 45,258 ms | +10.590% |

candidate 第一条索引成功，第二条把 `--` 后的原生 argv 错写为再次包含 `rg`，exit 1；第三条用正确边界恢复并取得有界大页。因此它没有把 command 降到 2，但相对 control 的全文式读取显著减少了可见证据、ordinary input 和两种价格。独立审计确认答案仍缺初始化 `getSessions`、`sessionSelected=null` 清理和“不证明 VS Code 传输/运行时交付”的源码边界，且合并了 `agentsList`/`agentDetected` 的行号范围；质量失败阻断采纳和跨语言扩量。

三次实验把原线索收敛为：交互轮次是强放大器，但 raw command 数不是充分成本指标；一次性工具正文、每轮重复上下文、ordinary/cache 构成、输出和失败恢复共同决定价格。探针 B 在工具正文少 15.902% 时因 command `5→11` 使价格近乎翻倍，直接支持额外交互可以吞没局部压缩；探针 C 在 command 同为 3 时仍因目标正文少 39.727% 而显著降价，直接否定“只看调用数”。静态规则层连续三种形状都没有同时取得更少 command、完整质量和更低价格，当前不修改正式 `global/AGENTS.md` 或 `source-query` skill。下一次只有工具或 runner 能可靠消除 argv 错形与模型逐页动作，并以非项目特定的答案完整性入口闭合首个 case 时才重开。
